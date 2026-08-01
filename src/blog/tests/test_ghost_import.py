import base64
import io
import json
import re
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from bleach._vendor import html5lib
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.db import transaction
from django.test import RequestFactory, TestCase, override_settings
from django.utils.dateparse import parse_datetime
from django.views.static import serve as serve_static
from PIL import Image as PillowImage
from wagtail.contrib.redirects.models import Redirect
from wagtail.images import get_image_model
from wagtail.models import Site

from blog.ghost_import import (
    GhostImportError,
    _image_storage_target,
    _read_required_images,
    import_ghost_export,
)
from blog.html_sanitizer import sanitize_structural_html
from blog.models import (
    BlogAuthor,
    BlogIndexPage,
    BlogPage,
    BlogTag,
    ContentPage,
    GhostImageImport,
)


def _png_bytes(color=(12, 34, 56)):
    output = io.BytesIO()
    PillowImage.new("RGB", (2, 2), color=color).save(output, format="PNG")
    return output.getvalue()


def _inline_png_url(color=(12, 34, 56)):
    encoded = base64.b64encode(_png_bytes(color)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _write_archive(archive_path, files, *, archive_format=tarfile.PAX_FORMAT):
    with tarfile.open(
        archive_path,
        mode="w:gz",
        format=archive_format,
    ) as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


def _record(number, *, content_type="post", status="published"):
    published_at = f"2025-01-{number + 1:02d}T12:34:56Z" if status == "published" else None
    html = f"<p>Safe synthetic body {number}</p>"
    if number == 0:
        html = """
            <figure>
              <img
                src="__GHOST_URL__/content/images/2025/01/pixel.png"
                srcset="__GHOST_URL__/content/images/size/w600/2025/01/pixel.png 600w"
                onerror="alert(1)">
              <figcaption>Diagram</figcaption>
            </figure>
            <table><tbody><tr><th>Key</th><td>Value</td></tr></tbody></table>
            <svg viewBox="0 0 10 10" onload="alert(2)">
              <style>rect { fill: #123456; }</style>
              <foreignObject><p>unsafe SVG HTML</p></foreignObject>
              <image xlink:href="javascript:alert(5)"></image>
              <rect
                  x="0"
                  y="0"
                  width="10"
                  height="10"
                  fill="url(https://evil.example/paint.svg)"></rect>
            </svg>
            <iframe
                src="https://embed.example/lab/"
                srcdoc="<script>alert(6)</script>"
                sandbox="allow-same-origin allow-scripts"
                title="Lab"></iframe>
            <iframe src="https://evil.example/lab/"></iframe>
            <iframe src="https://embed.example.evil.test/lab/"></iframe>
            <script>window.bad = true</script>
            <p onclick="alert(3)">Still safe</p>
            <a href="javascript:alert(4)">Unsafe link</a>
            <img src="data:text/html;base64,PHNjcmlwdD4=">
        """
    return {
        "id": f"ghost-{content_type}-{number}",
        "uuid": f"00000000-0000-0000-0000-{number + 1:012d}",
        "type": content_type,
        "status": status,
        "visibility": "public",
        "slug": "about" if content_type == "page" else f"synthetic-post-{number}",
        "title": "About" if content_type == "page" else f"Synthetic post {number}",
        "created_at": f"2025-01-{number + 1:02d}T10:00:00Z",
        "updated_at": f"2025-02-{number + 1:02d}T11:00:00Z",
        "published_at": published_at,
        "custom_excerpt": f"Synthetic excerpt {number}" if content_type == "post" else None,
        "featured": 1 if content_type == "post" and number == 0 else 0,
        "feature_image": (
            "__GHOST_URL__/content/images/2025/01/pixel.png"
            if content_type == "post" and number == 0
            else None
        ),
        "html": html,
        "codeinjection_head": "<script>head injection</script>",
        "codeinjection_foot": "<script>foot injection</script>",
    }


def _export_payload():
    posts = [
        *[_record(index) for index in range(4)],
        *[_record(index, status="draft") for index in range(4, 6)],
        _record(6, content_type="page"),
    ]
    return {
        "schema_version": 1,
        "posts": posts,
        "authors": [
            {
                "id": "ghost-author-1",
                "name": "Synthetic Author",
                "slug": "synthetic-author",
                "bio": "A test author.",
                "visibility": "public",
                "website": "https://author.example/",
            }
        ],
        "tags": [
            {
                "id": "ghost-tag-1",
                "name": "Synthetic Tag",
                "slug": "synthetic-tag",
                "description": "A test tag.",
                "visibility": "public",
            },
            {
                "id": "ghost-tag-2",
                "name": "Unused Tag",
                "slug": "unused-tag",
                "description": "",
                "visibility": "public",
            },
        ],
        "posts_authors": [
            {
                "post_id": post["id"],
                "author_id": "ghost-author-1",
                "sort_order": 0,
            }
            for post in posts
        ],
        "posts_tags": [
            {
                "post_id": post["id"],
                "tag_id": "ghost-tag-1",
                "sort_order": 0,
            }
            for post in posts
            if post["type"] == "post"
        ],
    }


class GhostImportTest(TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.override = override_settings(
            MEDIA_ROOT=self.temp_directory.name,
            ALLOWED_EMBED_HOSTS=["embed.example"],
            SITE_NAME="Synthetic Site",
            SITE_DESCRIPTION="Synthetic site description.",
            SITE_AUTHOR="Fallback Author",
            ALLOWED_HOSTS=[
                "synthetic.example",
                "preview.cegarza.com",
                "cegarza.com",
                "testserver",
            ],
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

        directory = Path(self.temp_directory.name)
        self.export_path = directory / "migration.json"
        self.archive_path = directory / "files.tar.gz"
        self.export_path.write_text(json.dumps(_export_payload()), encoding="utf-8")
        image_data = _png_bytes()
        with tarfile.open(self.archive_path, mode="w:gz") as archive:
            image_info = tarfile.TarInfo("content/images/2025/01/pixel.png")
            image_info.size = len(image_data)
            archive.addfile(image_info, io.BytesIO(image_data))

    def _run_import(self):
        return import_ghost_export(
            self.export_path,
            self.archive_path,
            hostname="synthetic.example",
            port=443,
            site_name="Synthetic Site",
        )

    def test_import_preserves_content_state_and_is_idempotent(self):
        default_site = Site.objects.get(is_default_site=True)
        default_root_id = default_site.root_page_id

        first = self._run_import()

        self.assertEqual(first.published_posts, 4)
        self.assertEqual(first.draft_posts, 2)
        self.assertEqual(first.pages, 1)
        self.assertEqual(first.created_pages, 7)
        self.assertEqual(first.updated_pages, 0)
        self.assertEqual(first.unchanged_pages, 0)
        self.assertEqual(first.images, 1)
        self.assertEqual(first.archive_images, 1)
        self.assertEqual(first.inline_images, 0)

        site = Site.objects.get(hostname="synthetic.example", port=443)
        index = site.root_page.specific
        self.assertIsInstance(index, BlogIndexPage)
        self.assertEqual(index.get_url(current_site=site), "/")
        self.assertEqual(index.intro, "Synthetic site description.")
        self.assertEqual(index.default_author_name, "Synthetic Author")
        self.assertEqual(
            BlogPage.objects.descendant_of(index).live().count(),
            4,
        )
        self.assertEqual(
            BlogPage.objects.descendant_of(index).filter(live=False).count(),
            2,
        )
        self.assertEqual(ContentPage.objects.descendant_of(index).live().count(), 1)
        self.assertEqual(
            ContentPage.objects.get(ghost_id="ghost-page-6").get_url(current_site=site),
            "/about/",
        )

        first_post = BlogPage.objects.get(ghost_id="ghost-post-0")
        self.assertEqual(first_post.slug, "synthetic-post-0")
        self.assertEqual(first_post.abstract, "Synthetic excerpt 0")
        self.assertTrue(first_post.is_featured)
        self.assertEqual(BlogPage.objects.filter(is_featured=True).count(), 1)
        self.assertEqual(first_post.authors.get().ghost_id, "ghost-author-1")
        self.assertEqual(first_post.tags.get().ghost_id, "ghost-tag-1")
        self.assertEqual(first_post.featured_image_id, get_image_model().objects.get().pk)
        self.assertEqual(first_post.social_image_id, first_post.featured_image_id)
        self.assertEqual(
            first_post.ghost_published_at,
            parse_datetime("2025-01-01T12:34:56Z"),
        )
        self.assertEqual(first_post.first_published_at, first_post.ghost_published_at)

        imported_html = first_post.body.raw_data[0]["value"]
        self.assertIn("/media/original_images/", imported_html)
        self.assertIn("<figure>", imported_html)
        self.assertIn("<table>", imported_html)
        self.assertIn("<svg", imported_html)
        self.assertIn("<iframe", imported_html)
        self.assertNotIn(GhostImageImport.objects.get().ghost_path, imported_html)
        self.assertNotIn("__GHOST_URL__", imported_html)
        self.assertNotIn("srcset", imported_html)
        self.assertNotIn("<script", imported_html)
        self.assertNotIn("onclick", imported_html)
        self.assertNotIn("onerror", imported_html)
        self.assertNotIn("javascript:", imported_html)
        self.assertNotIn("head injection", imported_html)
        self.assertNotIn("foot injection", imported_html)

        page_primary_keys = {
            page.ghost_id: page.pk
            for page in [
                *BlogPage.objects.descendant_of(index),
                *ContentPage.objects.descendant_of(index),
            ]
        }
        revision_counts = {
            page.pk: page.revisions.count()
            for page in [
                *BlogPage.objects.descendant_of(index),
                *ContentPage.objects.descendant_of(index),
            ]
        }
        image = get_image_model().objects.get()
        image_pk = image.pk
        image_name = image.file.name
        stored_files = {
            path.relative_to(self.temp_directory.name)
            for path in Path(self.temp_directory.name).rglob("*")
            if path.is_file() and path != self.export_path and path != self.archive_path
        }

        second = self._run_import()

        self.assertEqual(second.created_pages, 0)
        self.assertEqual(second.updated_pages, 0)
        self.assertEqual(second.unchanged_pages, 7)
        self.assertEqual(BlogPage.objects.descendant_of(index).count(), 6)
        self.assertEqual(ContentPage.objects.descendant_of(index).count(), 1)
        self.assertEqual(BlogAuthor.objects.count(), 1)
        self.assertEqual(BlogTag.objects.count(), 2)
        self.assertEqual(GhostImageImport.objects.count(), 1)
        self.assertEqual(get_image_model().objects.count(), 1)
        self.assertEqual(
            {
                page.ghost_id: page.pk
                for page in [
                    *BlogPage.objects.descendant_of(index),
                    *ContentPage.objects.descendant_of(index),
                ]
            },
            page_primary_keys,
        )
        self.assertEqual(
            {
                page.pk: page.revisions.count()
                for page in [
                    *BlogPage.objects.descendant_of(index),
                    *ContentPage.objects.descendant_of(index),
                ]
            },
            revision_counts,
        )
        image.refresh_from_db()
        self.assertEqual(image.pk, image_pk)
        self.assertEqual(image.file.name, image_name)
        self.assertEqual(
            {
                path.relative_to(self.temp_directory.name)
                for path in Path(self.temp_directory.name).rglob("*")
                if path.is_file() and path != self.export_path and path != self.archive_path
            },
            stored_files,
        )
        default_site.refresh_from_db()
        self.assertEqual(default_site.root_page_id, default_root_id)
        self.assertTrue(default_site.is_default_site)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_site_identity_defaults_to_validated_ghost_metadata(self):
        payload = _export_payload()
        payload["settings"] = {
            "title": "Ghost Publication",
            "description": "Ghost publication description.",
            "default_content_visibility": "public",
        }
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")

        import_ghost_export(
            self.export_path,
            self.archive_path,
            hostname="synthetic.example",
            port=443,
        )

        site = Site.objects.get(hostname="synthetic.example")
        index = site.root_page.specific
        self.assertEqual(site.site_name, "Ghost Publication")
        self.assertEqual(index.title, "Ghost Publication")
        self.assertEqual(index.intro, "Ghost publication description.")
        self.assertEqual(index.default_author_name, "Synthetic Author")
        response = self.client.get("/", HTTP_HOST="synthetic.example")
        self.assertContains(response, "Ghost Publication")
        self.assertContains(response, "Ghost publication description.")
        self.assertContains(response, "Synthetic Author")
        self.assertNotContains(response, "Fallback Author")

    def test_non_public_content_and_settings_fail_before_writes(self):
        cases = (
            ("post", "members"),
            ("author", "paid"),
            ("tag", "tiers"),
            ("settings", "members"),
        )
        for record_type, visibility in cases:
            with self.subTest(record_type=record_type, visibility=visibility):
                payload = _export_payload()
                if record_type == "post":
                    payload["posts"][0]["visibility"] = visibility
                elif record_type == "author":
                    payload["authors"][0]["visibility"] = visibility
                elif record_type == "tag":
                    payload["tags"][0]["visibility"] = visibility
                else:
                    payload["settings"] = {
                        "default_content_visibility": visibility,
                        "title": "Synthetic Site",
                    }
                self.export_path.write_text(json.dumps(payload), encoding="utf-8")

                with self.assertRaisesRegex(GhostImportError, "non-public"):
                    self._run_import()

                self.assertFalse(Site.objects.filter(hostname="synthetic.example").exists())
                self.assertEqual(BlogPage.objects.count(), 0)
                self.assertEqual(ContentPage.objects.count(), 0)
                self.assertEqual(GhostImageImport.objects.count(), 0)
                self.assertEqual(get_image_model().objects.count(), 0)

    def test_multiple_authors_fail_closed_before_writes(self):
        payload = _export_payload()
        payload["authors"].append(
            {
                "id": "ghost-author-2",
                "name": "Second Synthetic Author",
                "slug": "second-synthetic-author",
                "bio": "",
                "visibility": "public",
                "website": "",
            }
        )
        payload["posts_authors"].append(
            {
                "post_id": payload["posts"][0]["id"],
                "author_id": "ghost-author-2",
                "sort_order": 1,
            }
        )
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(GhostImportError, "multiple authors"):
            self._run_import()

        self.assertFalse(Site.objects.filter(hostname="synthetic.example").exists())
        self.assertEqual(BlogAuthor.objects.count(), 0)
        self.assertEqual(GhostImageImport.objects.count(), 0)
        self.assertEqual(get_image_model().objects.count(), 0)

    def test_polyglot_media_is_reencoded_with_a_safe_opaque_name(self):
        ghost_path = "content/images/2025/01/browser-payload.html"
        ghost_url = f"__GHOST_URL__/{ghost_path}"
        payload = _export_payload()
        payload["posts"][0]["html"] = f'<img src="{ghost_url}">'
        payload["posts"][0]["feature_image"] = ghost_url
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")
        appended_html = b"<html><script>window.polyglot = true</script></html>"
        _write_archive(
            self.archive_path,
            {ghost_path: _png_bytes() + appended_html},
        )

        self._run_import()

        mapping = GhostImageImport.objects.get(ghost_path=ghost_path)
        image = mapping.image
        self.assertRegex(
            image.file.name,
            r"^original_images/ghost-[0-9a-f]{64}\.png$",
        )
        self.assertNotIn("browser-payload", image.file.name)
        with image.file.open("rb") as imported_file:
            canonical_bytes = imported_file.read()
        self.assertNotIn(appended_html, canonical_bytes)
        with PillowImage.open(io.BytesIO(canonical_bytes)) as canonical_image:
            self.assertEqual(canonical_image.format, "PNG")
            canonical_image.verify()

        response = serve_static(
            RequestFactory().get(image.file.url),
            image.file.name,
            document_root=self.temp_directory.name,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertFalse(image.file.storage.exists(ghost_path))
        self.assertFalse(image.file.storage.exists("original_images/browser-payload.html"))

    def test_drawio_inline_png_fallbacks_are_extracted_and_namespace_safe(self):
        inline_url = _inline_png_url()
        payload = _export_payload()
        payload["posts"][0]["feature_image"] = None
        payload["posts"][0]["html"] = f"""
            <svg class="ge-export-svg-dark" viewBox="0 0 100 100">
              <defs><style>svg {{ filter: invert(100%); }}</style></defs>
              <g id="first-group">
                <switch>
                  <foreignObject width="100%" height="100%">
                    <div xmlns="http://www.w3.org/1999/xhtml">Unsafe HTML label</div>
                  </foreignObject>
                  <image x="1" y="2" width="20" height="10"
                         xlink:href="{inline_url}"></image>
                </switch>
                <ellipse cx="10" cy="10" rx="5" ry="4"></ellipse>
              </g>
              <g id="second-group">
                <switch>
                  <foreignObject><div>Duplicate label</div></foreignObject>
                  <image x="3" y="4" width="20" height="10"
                         xlink:href="{inline_url}"></image>
                </switch>
                <ellipse cx="20" cy="20" rx="5" ry="4"></ellipse>
              </g>
            </svg>
        """
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")

        first = self._run_import()

        self.assertEqual(first.archive_images, 0)
        self.assertEqual(first.inline_images, 1)
        self.assertEqual(first.images, 1)
        self.assertEqual(GhostImageImport.objects.count(), 1)
        mapping = GhostImageImport.objects.select_related("image").get()
        self.assertRegex(
            mapping.ghost_path,
            r"^inline-images/[0-9a-f]{64}\.png$",
        )
        self.assertRegex(
            mapping.image.file.name,
            r"^original_images/ghost-[0-9a-f]{64}\.png$",
        )

        post = BlogPage.objects.get(ghost_id="ghost-post-0")
        imported_html = post.body.raw_data[0]["value"]
        self.assertNotIn("data:image", imported_html)
        self.assertNotIn("xlink:href", imported_html)
        self.assertNotIn("foreignObject", imported_html)
        self.assertNotIn("Unsafe HTML label", imported_html)
        self.assertNotIn("<style", imported_html)
        self.assertIn('class="ge-export-svg-dark"', imported_html)
        self.assertEqual(imported_html.count("<image "), 2)
        self.assertEqual(imported_html.count(f'href="{mapping.image.file.url}"'), 2)
        site_css = (Path(__file__).parents[2] / "static" / "css" / "site.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            ".post-content svg.ge-export-svg-dark:not(mjx-container > svg)",
            site_css,
        )
        self.assertIn("filter: invert(100%) hue-rotate(180deg);", site_css)

        fragment = html5lib.parseFragment(
            imported_html,
            namespaceHTMLElements=True,
        )
        svg_namespace = "{http://www.w3.org/2000/svg}"
        svg = next(element for element in fragment.iter() if element.tag == f"{svg_namespace}svg")
        expected_counts = {
            "g": 2,
            "switch": 2,
            "image": 2,
            "ellipse": 2,
        }
        for local_name, expected_count in expected_counts.items():
            elements = [
                element for element in svg.iter() if element.tag == f"{svg_namespace}{local_name}"
            ]
            self.assertEqual(len(elements), expected_count)

        image_name = mapping.image.file.name
        second = self._run_import()
        mapping.refresh_from_db()
        self.assertEqual(second.unchanged_pages, 7)
        self.assertEqual(second.inline_images, 1)
        self.assertEqual(GhostImageImport.objects.count(), 1)
        self.assertEqual(mapping.image.file.name, image_name)

    def test_inline_svg_image_must_be_strict_valid_png(self):
        invalid_urls = (
            "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
            "data:image/png;base64,not-valid-***",
            "data:image/png;base64," + base64.b64encode(b"not actually a PNG").decode("ascii"),
        )
        for invalid_url in invalid_urls:
            with self.subTest(invalid_url=invalid_url[:40]):
                payload = _export_payload()
                payload["posts"][0]["feature_image"] = None
                payload["posts"][0]["html"] = (
                    f'<svg><switch><image href="{invalid_url}"></image></switch></svg>'
                )
                self.export_path.write_text(json.dumps(payload), encoding="utf-8")

                with self.assertRaises(GhostImportError):
                    self._run_import()

                self.assertFalse(Site.objects.filter(hostname="synthetic.example").exists())
                self.assertEqual(GhostImageImport.objects.count(), 0)
                self.assertEqual(get_image_model().objects.count(), 0)

    def test_inline_and_archive_images_share_aggregate_pixel_budget(self):
        inline_url = _inline_png_url((90, 80, 70))
        payload = _export_payload()
        payload["posts"][0]["html"] = f"""
            <img src="__GHOST_URL__/content/images/2025/01/pixel.png">
            <svg><switch><image href="{inline_url}"></image></switch></svg>
        """
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")

        with patch("blog.ghost_import.MAX_TOTAL_IMAGE_PIXELS", 7):
            with self.assertRaisesRegex(GhostImportError, "aggregate limit"):
                self._run_import()

        self.assertFalse(Site.objects.filter(hostname="synthetic.example").exists())
        self.assertEqual(GhostImageImport.objects.count(), 0)
        self.assertEqual(get_image_model().objects.count(), 0)

    def test_distinct_inline_variants_count_work_before_canonical_deduplication(
        self,
    ):
        png_data = _png_bytes((70, 80, 90))
        variant_urls = [
            "data:image/png;base64," + base64.b64encode(png_data + bytes([variant])).decode("ascii")
            for variant in range(5)
        ]
        payload = _export_payload()
        payload["posts"][0]["html"] = (
            '<img src="__GHOST_URL__/content/images/2025/01/pixel.png">'
            "<svg>"
            + "".join(
                f'<switch><image href="{variant_url}"></image></switch>'
                for variant_url in variant_urls
            )
            + "</svg>"
        )
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")

        # Archive image: 4px. Five distinct data URIs: 5 * 4px. Although
        # canonical re-encoding deduplicates all five to one stored PNG, the
        # 24px of actual processing must exceed this shared 23px budget.
        with patch("blog.ghost_import.MAX_TOTAL_IMAGE_PIXELS", 23):
            with self.assertRaisesRegex(GhostImportError, "aggregate limit"):
                self._run_import()

        self.assertFalse(Site.objects.filter(hostname="synthetic.example").exists())
        self.assertEqual(GhostImageImport.objects.count(), 0)
        self.assertEqual(get_image_model().objects.count(), 0)

    def test_same_basename_media_gets_distinct_stable_names(self):
        first_path = "content/images/2025/one/shared.png"
        second_path = "content/images/2025/two/shared.png"
        payload = _export_payload()
        payload["posts"][0]["html"] = f'<img src="__GHOST_URL__/{first_path}">'
        payload["posts"][0]["feature_image"] = f"__GHOST_URL__/{first_path}"
        payload["posts"][1]["html"] = f'<img src="__GHOST_URL__/{second_path}">'
        payload["posts"][1]["feature_image"] = f"__GHOST_URL__/{second_path}"
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")
        _write_archive(
            self.archive_path,
            {
                first_path: _png_bytes((1, 2, 3)),
                second_path: _png_bytes((4, 5, 6)),
            },
        )

        first = self._run_import()
        names = {
            mapping.ghost_path: mapping.image.file.name
            for mapping in GhostImageImport.objects.select_related("image")
        }
        second = self._run_import()

        self.assertEqual(first.images, 2)
        self.assertEqual(second.unchanged_pages, 7)
        self.assertEqual(set(names), {first_path, second_path})
        self.assertNotEqual(names[first_path], names[second_path])
        for name in names.values():
            self.assertRegex(
                name,
                r"^original_images/ghost-[0-9a-f]{64}\.png$",
            )
            self.assertNotIn("shared", name)
        self.assertEqual(
            {
                mapping.ghost_path: mapping.image.file.name
                for mapping in GhostImageImport.objects.select_related("image")
            },
            names,
        )
        self.assertEqual(get_image_model().objects.count(), 2)

    def test_draft_only_media_uses_an_opaque_but_public_capability_url(self):
        ghost_path = "content/images/private/draft-secret.html"
        payload = _export_payload()
        payload["posts"][0]["html"] = "<p>No image.</p>"
        payload["posts"][0]["feature_image"] = None
        payload["posts"][4]["feature_image"] = f"__GHOST_URL__/{ghost_path}"
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")
        _write_archive(self.archive_path, {ghost_path: _png_bytes()})

        self._run_import()

        draft = BlogPage.objects.get(ghost_id="ghost-post-4")
        mapping = GhostImageImport.objects.get(ghost_path=ghost_path)
        self.assertFalse(draft.live)
        self.assertEqual(draft.featured_image_id, mapping.image_id)
        self.assertEqual(draft.social_image_id, mapping.image_id)
        self.assertRegex(
            mapping.image.file.name,
            r"^original_images/ghost-[0-9a-f]{64}\.png$",
        )
        self.assertNotIn("draft-secret", mapping.image.file.name)
        self.assertFalse(mapping.image.file.storage.exists(ghost_path))
        self.assertFalse(mapping.image.file.storage.exists("original_images/draft-secret.html"))
        capability_response = serve_static(
            RequestFactory().get(mapping.image.file.url),
            mapping.image.file.name,
            document_root=self.temp_directory.name,
        )
        self.assertEqual(capability_response.status_code, 200)
        self.assertEqual(capability_response["Content-Type"], "image/png")

    def test_mismatched_stable_media_target_is_not_overwritten_or_deleted(self):
        image_payload = _read_required_images(
            self.archive_path,
            {"content/images/2025/01/pixel.png"},
        )["content/images/2025/01/pixel.png"]
        _, storage, expected_name = _image_storage_target(
            get_image_model(),
            "content/images/2025/01/pixel.png",
            image_payload,
        )
        stored_name = storage.save(expected_name, ContentFile(b"preexisting"))
        self.assertEqual(stored_name, expected_name)

        with self.assertRaisesRegex(GhostImportError, "unexpected bytes"):
            self._run_import()

        with storage.open(expected_name, "rb") as stored_file:
            self.assertEqual(stored_file.read(), b"preexisting")
        self.assertEqual(GhostImageImport.objects.count(), 0)
        self.assertEqual(get_image_model().objects.count(), 0)
        self.assertFalse(Site.objects.filter(hostname="synthetic.example").exists())

    def test_matching_mappingless_media_target_is_adopted_on_retry(self):
        ghost_path = "content/images/2025/01/pixel.png"
        image_payload = _read_required_images(
            self.archive_path,
            {ghost_path},
        )[ghost_path]
        _, storage, expected_name = _image_storage_target(
            get_image_model(),
            ghost_path,
            image_payload,
        )
        stored_name = storage.save(
            expected_name,
            ContentFile(image_payload.data),
        )
        self.assertEqual(stored_name, expected_name)

        first = self._run_import()
        mapping = GhostImageImport.objects.select_related("image").get(ghost_path=ghost_path)
        second = self._run_import()

        self.assertEqual(first.created_pages, 7)
        self.assertEqual(second.unchanged_pages, 7)
        self.assertEqual(mapping.image.file.name, expected_name)
        self.assertEqual(get_image_model().objects.count(), 1)
        with storage.open(expected_name, "rb") as stored_file:
            self.assertEqual(stored_file.read(), image_payload.data)

    def test_storage_save_side_effect_then_error_is_verified_and_adopted(self):
        ghost_path = "content/images/2025/01/pixel.png"
        image_payload = _read_required_images(
            self.archive_path,
            {ghost_path},
        )[ghost_path]
        _, storage, expected_name = _image_storage_target(
            get_image_model(),
            ghost_path,
            image_payload,
        )
        original_save = storage.save

        def save_then_lose_response(name, content, max_length=None):
            stored_name = original_save(
                name,
                content,
                max_length=max_length,
            )
            self.assertEqual(stored_name, expected_name)
            raise OSError("synthetic lost storage response")

        with patch.object(
            storage,
            "save",
            side_effect=save_then_lose_response,
        ):
            first = self._run_import()

        mapping = GhostImageImport.objects.select_related("image").get(ghost_path=ghost_path)
        second = self._run_import()
        self.assertEqual(first.created_pages, 7)
        self.assertEqual(second.unchanged_pages, 7)
        self.assertEqual(mapping.image.file.name, expected_name)
        with storage.open(expected_name, "rb") as stored_file:
            self.assertEqual(stored_file.read(), image_payload.data)

    def test_storage_collision_race_keeps_winner_and_cleans_loser(self):
        ghost_path = "content/images/2025/01/pixel.png"
        image_payload = _read_required_images(
            self.archive_path,
            {ghost_path},
        )[ghost_path]
        _, storage, expected_name = _image_storage_target(
            get_image_model(),
            ghost_path,
            image_payload,
        )
        original_save = storage.save

        def create_collision_then_save(name, content, max_length=None):
            original_save(name, ContentFile(b"winner"), max_length=max_length)
            return original_save(name, content, max_length=max_length)

        with patch.object(
            storage,
            "save",
            side_effect=create_collision_then_save,
        ):
            with self.assertRaisesRegex(GhostImportError, "changed.*target name"):
                self._run_import()

        with storage.open(expected_name, "rb") as winner:
            self.assertEqual(winner.read(), b"winner")
        stored_files = [
            path
            for path in (Path(self.temp_directory.name) / "original_images").rglob("*")
            if path.is_file()
        ]
        self.assertEqual(
            [path.relative_to(self.temp_directory.name).as_posix() for path in stored_files],
            [expected_name],
        )
        self.assertEqual(GhostImageImport.objects.count(), 0)
        self.assertEqual(get_image_model().objects.count(), 0)

    def test_anonymous_routes_never_leak_drafts(self):
        self._run_import()

        published = self.client.get(
            "/synthetic-post-0/",
            HTTP_HOST="synthetic.example",
        )
        about = self.client.get("/about/", HTTP_HOST="synthetic.example")
        draft = self.client.get(
            "/synthetic-post-4/",
            HTTP_HOST="synthetic.example",
        )
        draft_markdown = self.client.get(
            "/synthetic-post-4.md",
            HTTP_HOST="synthetic.example",
        )
        index = self.client.get("/writing/", HTTP_HOST="synthetic.example")
        feed = self.client.get("/feed/", HTTP_HOST="synthetic.example")
        rss = self.client.get("/rss/", HTTP_HOST="synthetic.example", follow=True)
        sitemap = self.client.get("/sitemap.xml", HTTP_HOST="synthetic.example")

        self.assertEqual(published.status_code, 200)
        self.assertContains(published, "Synthetic post 0")
        self.assertContains(published, "Synthetic Site")
        self.assertContains(published, "Synthetic Author")
        self.assertEqual(about.status_code, 200)
        self.assertEqual(draft.status_code, 404)
        self.assertEqual(draft_markdown.status_code, 404)
        rendered_html = published.content.decode("utf-8").lower()
        post_content = rendered_html.split(
            '<div class="content post-content">',
            maxsplit=1,
        )[1].split("</div>", maxsplit=1)[0]
        self.assertNotIn("<script", post_content)
        for poison in (
            "window.bad",
            "onclick=",
            "onerror=",
            "onload=",
            "javascript:",
            "data:text/html",
            "srcdoc",
            "foreignobject",
            "xlink",
            "evil.example",
            "embed.example.evil.test",
            "allow-same-origin",
        ):
            self.assertNotIn(poison, rendered_html)
        self.assertIn(
            'sandbox="allow-forms allow-popups allow-scripts"',
            rendered_html,
        )
        self.assertIn(
            "frame-src 'self' https://embed.example",
            published["Content-Security-Policy-Report-Only"],
        )
        self.assertContains(index, "Synthetic post 0")
        writing_index_html = index.content.decode("utf-8").split(
            '<section class="writing-index"',
            maxsplit=1,
        )[1].split("</section>", maxsplit=1)[0]
        self.assertNotIn('href="/about/"', writing_index_html)
        for response in (index, feed, rss, sitemap):
            self.assertNotContains(response, "Synthetic post 4")
            self.assertNotContains(response, "Synthetic post 5")
        self.assertEqual(rss.redirect_chain[0][1], 301)
        self.assertEqual(rss.redirect_chain[0][0], "/feed/")
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_shared_root_urls_follow_the_current_preview_or_apex_site(self):
        import_ghost_export(
            self.export_path,
            self.archive_path,
            hostname="preview.cegarza.com",
            port=443,
            site_name="Synthetic Site",
        )
        call_command("activate_cegarza_hostname", stdout=io.StringIO())

        for hostname, other_hostname in (
            ("preview.cegarza.com", "cegarza.com"),
            ("cegarza.com", "preview.cegarza.com"),
        ):
            root_url = f"https://{hostname}"
            other_root_url = f"https://{other_hostname}"
            page_url = f"{root_url}/synthetic-post-0/"
            response = self.client.get(
                "/synthetic-post-0/",
                HTTP_HOST=hostname,
                secure=True,
            )

            self.assertEqual(response.status_code, 200)
            body = response.content.decode("utf-8")
            self.assertIn(
                f'<link rel="canonical" href="{page_url}">',
                body,
            )
            self.assertIn(
                f'<meta property="og:url" content="{page_url}">',
                body,
            )
            structured_data_match = re.search(
                r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
                body,
                re.DOTALL,
            )
            self.assertIsNotNone(structured_data_match)
            structured_data = json.loads(structured_data_match.group(1))
            self.assertEqual(structured_data["url"], page_url)
            self.assertNotIn(other_root_url, body)

            feed = self.client.get(
                "/feed/",
                HTTP_HOST=hostname,
                secure=True,
            )
            self.assertEqual(feed.status_code, 200)
            feed_body = feed.content.decode("utf-8")
            self.assertIn(page_url, feed_body)
            self.assertNotIn(other_root_url, feed_body)

    def test_same_slug_with_different_ghost_id_fails_before_writes(self):
        self._run_import()
        payload = _export_payload()
        original_id = payload["posts"][0]["id"]
        payload["posts"][0]["id"] = "replacement-ghost-id"
        for relation in [*payload["posts_authors"], *payload["posts_tags"]]:
            if relation["post_id"] == original_id:
                relation["post_id"] = "replacement-ghost-id"
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")
        counts_before = (
            BlogPage.objects.count(),
            ContentPage.objects.count(),
            GhostImageImport.objects.count(),
            get_image_model().objects.count(),
        )

        with self.assertRaisesRegex(GhostImportError, "different Ghost ID"):
            self._run_import()

        self.assertEqual(
            (
                BlogPage.objects.count(),
                ContentPage.objects.count(),
                GhostImageImport.objects.count(),
                get_image_model().objects.count(),
            ),
            counts_before,
        )

    def test_split_id_and_slug_matches_are_fatal(self):
        self._run_import()
        payload = _export_payload()
        payload["posts"][0]["slug"], payload["posts"][1]["slug"] = (
            payload["posts"][1]["slug"],
            payload["posts"][0]["slug"],
        )
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")
        page_ids_before = dict(BlogPage.objects.values_list("ghost_id", "pk"))

        with self.assertRaisesRegex(GhostImportError, "different pages"):
            self._run_import()

        self.assertEqual(
            dict(BlogPage.objects.values_list("ghost_id", "pk")),
            page_ids_before,
        )

    def test_cross_page_type_uuid_collision_fails_before_writes(self):
        self._run_import()
        collision_uuid = "11111111-1111-4111-8111-111111111111"
        content_page = ContentPage.objects.get(ghost_id="ghost-page-6")
        content_page.ghost_uuid = collision_uuid
        content_page.save(update_fields=["ghost_uuid"])

        payload = _export_payload()
        payload["posts"][0]["uuid"] = collision_uuid
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")
        page_state_before = {
            page.pk: (page.ghost_id, str(page.ghost_uuid), page.title)
            for page in [
                *BlogPage.objects.all(),
                *ContentPage.objects.all(),
            ]
        }

        with self.assertRaisesRegex(GhostImportError, "already belongs to ContentPage"):
            self._run_import()

        self.assertEqual(
            {
                page.pk: (page.ghost_id, str(page.ghost_uuid), page.title)
                for page in [
                    *BlogPage.objects.all(),
                    *ContentPage.objects.all(),
                ]
            },
            page_state_before,
        )

    def test_storage_file_is_cleaned_if_transaction_fails(self):
        with patch(
            "blog.ghost_import._import_record",
            side_effect=GhostImportError("synthetic failure"),
        ):
            with self.assertRaisesRegex(GhostImportError, "synthetic failure"):
                self._run_import()

        self.assertEqual(GhostImageImport.objects.count(), 0)
        self.assertEqual(get_image_model().objects.count(), 0)
        self.assertFalse(
            any(
                path.is_file()
                for path in (Path(self.temp_directory.name) / "original_images").glob("**/*")
            )
        )

    def test_unknown_rolled_back_commit_preserves_media_for_retry_recovery(self):
        @contextmanager
        def commit_failure():
            with transaction.atomic():
                yield
                transaction.set_rollback(True)
            raise GhostImportError("synthetic commit failure")

        with patch(
            "blog.ghost_import._ghost_import_transaction",
            side_effect=commit_failure,
        ):
            with self.assertRaisesRegex(GhostImportError, "outcome is unknown"):
                self._run_import()

        self.assertEqual(GhostImageImport.objects.count(), 0)
        self.assertEqual(get_image_model().objects.count(), 0)
        preserved_files = [
            path
            for path in (Path(self.temp_directory.name) / "original_images").glob("**/*")
            if path.is_file()
        ]
        self.assertEqual(len(preserved_files), 1)

        recovered = self._run_import()

        self.assertEqual(recovered.created_pages, 7)
        self.assertEqual(GhostImageImport.objects.count(), 1)
        self.assertEqual(get_image_model().objects.count(), 1)
        self.assertEqual(
            GhostImageImport.objects.get().image.file.name,
            preserved_files[0].relative_to(self.temp_directory.name).as_posix(),
        )

    def test_lost_commit_ack_preserves_media_referenced_by_committed_rows(self):
        @contextmanager
        def commit_then_lose_ack():
            with transaction.atomic():
                yield
            raise OSError("synthetic lost commit acknowledgement")

        with patch(
            "blog.ghost_import._ghost_import_transaction",
            side_effect=commit_then_lose_ack,
        ):
            with self.assertRaisesRegex(GhostImportError, "outcome is unknown"):
                self._run_import()

        mapping = GhostImageImport.objects.select_related("image").get()
        self.assertTrue(mapping.image.file.storage.exists(mapping.image.file.name))

        reconciled = self._run_import()

        self.assertEqual(reconciled.unchanged_pages, 7)
        self.assertEqual(GhostImageImport.objects.count(), 1)
        self.assertTrue(mapping.image.file.storage.exists(mapping.image.file.name))

    def test_explicit_aliases_rewrite_links_and_create_permanent_redirects(self):
        payload = _export_payload()
        payload["posts"][0]["slug"] = "splatgpt-part-1"
        payload["posts"][1]["slug"] = "splatgpt-part-2b"
        payload["posts"][2]["html"] = """
            <a href="__GHOST_URL__/the-deceptive-difficulty-of-splatoon-3-gear-optimization/">
              Canonical one
            </a>
            <a href="__GHOST_URL__/splatgpt-part-02b/?from=old#section">
              Canonical two
            </a>
        """
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")

        first = self._run_import()

        self.assertEqual(first.redirects, 2)
        imported_html = BlogPage.objects.get(ghost_id="ghost-post-2").body.raw_data[0]["value"]
        self.assertIn('href="/splatgpt-part-1/"', imported_html)
        self.assertIn('href="/splatgpt-part-2b/?from=old#section"', imported_html)
        redirects = {
            redirect.old_path: redirect
            for redirect in Redirect.objects.select_related("redirect_page")
        }
        self.assertEqual(
            set(redirects),
            {
                "/splatgpt-part-02b",
                "/the-deceptive-difficulty-of-splatoon-3-gear-optimization",
            },
        )
        self.assertEqual(
            redirects["/splatgpt-part-02b"].redirect_page.specific.slug,
            "splatgpt-part-2b",
        )
        self.assertEqual(
            redirects[
                "/the-deceptive-difficulty-of-splatoon-3-gear-optimization"
            ].redirect_page.specific.slug,
            "splatgpt-part-1",
        )
        self.assertTrue(all(redirect.is_permanent for redirect in redirects.values()))
        redirect_ids = set(Redirect.objects.values_list("pk", flat=True))

        second = self._run_import()

        self.assertEqual(second.redirects, 2)
        self.assertEqual(
            set(Redirect.objects.values_list("pk", flat=True)),
            redirect_ids,
        )
        response = self.client.get(
            "/splatgpt-part-02b/",
            HTTP_HOST="synthetic.example",
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            "https://synthetic.example/splatgpt-part-2b/",
        )

    def test_explicit_alias_cannot_target_draft_or_collide(self):
        payload = _export_payload()
        payload["posts"][0]["slug"] = "splatgpt-part-1"
        payload["posts"][0]["status"] = "draft"
        payload["posts"][0]["published_at"] = None
        payload["posts"][1]["html"] = (
            '<a href="__GHOST_URL__/'
            'the-deceptive-difficulty-of-splatoon-3-gear-optimization/">old</a>'
        )
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(GhostImportError, "published Ghost post"):
            self._run_import()

        self.assertEqual(Redirect.objects.count(), 0)
        self.assertFalse(Site.objects.filter(hostname="synthetic.example").exists())
        self.assertEqual(get_user_model().objects.count(), 0)

        payload["posts"][0]["status"] = "published"
        payload["posts"][0]["published_at"] = "2025-01-01T12:34:56Z"
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")
        self._run_import()
        redirect = Redirect.objects.get(
            old_path="/the-deceptive-difficulty-of-splatoon-3-gear-optimization"
        )
        redirect.redirect_page = BlogPage.objects.get(ghost_id="ghost-post-1")
        redirect.save(update_fields=["redirect_page"])

        with self.assertRaisesRegex(GhostImportError, "existing redirect"):
            self._run_import()

    def test_dry_run_validates_without_database_or_media_writes(self):
        summary = import_ghost_export(
            self.export_path,
            self.archive_path,
            hostname="synthetic.example",
            dry_run=True,
        )

        self.assertEqual(summary.posts, 6)
        self.assertEqual(summary.pages, 1)
        self.assertEqual(summary.images, 1)
        self.assertFalse(Site.objects.filter(hostname="synthetic.example").exists())
        self.assertEqual(GhostImageImport.objects.count(), 0)
        self.assertEqual(get_image_model().objects.count(), 0)

    def test_dry_run_detects_database_collision_without_writes(self):
        self._run_import()
        payload = _export_payload()
        original_id = payload["posts"][0]["id"]
        payload["posts"][0]["id"] = "replacement-ghost-id"
        for relation in [*payload["posts_authors"], *payload["posts_tags"]]:
            if relation["post_id"] == original_id:
                relation["post_id"] = "replacement-ghost-id"
        self.export_path.write_text(json.dumps(payload), encoding="utf-8")
        pages_before = {
            page.pk: (page.ghost_id, page.slug, page.title)
            for page in [
                *BlogPage.objects.all(),
                *ContentPage.objects.all(),
            ]
        }
        files_before = {
            path.relative_to(self.temp_directory.name)
            for path in Path(self.temp_directory.name).rglob("*")
            if path.is_file()
        }

        with self.assertRaisesRegex(GhostImportError, "different Ghost ID"):
            import_ghost_export(
                self.export_path,
                self.archive_path,
                hostname="synthetic.example",
                dry_run=True,
            )

        self.assertEqual(
            {
                page.pk: (page.ghost_id, page.slug, page.title)
                for page in [
                    *BlogPage.objects.all(),
                    *ContentPage.objects.all(),
                ]
            },
            pages_before,
        )
        self.assertEqual(
            {
                path.relative_to(self.temp_directory.name)
                for path in Path(self.temp_directory.name).rglob("*")
                if path.is_file()
            },
            files_before,
        )


class GhostArchiveSafetyTest(TestCase):
    def test_rejects_referenced_symlink(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            archive_path = Path(temp_directory) / "files.tar.gz"
            with tarfile.open(archive_path, mode="w:gz") as archive:
                link = tarfile.TarInfo("content/images/linked.png")
                link.type = tarfile.SYMTYPE
                link.linkname = "/etc/passwd"
                archive.addfile(link)

            with self.assertRaisesRegex(GhostImportError, "not a regular file"):
                _read_required_images(archive_path, {"content/images/linked.png"})

    def test_rejects_out_of_scope_archive_members(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            archive_path = Path(temp_directory) / "files.tar.gz"
            data = b"not media"
            with tarfile.open(archive_path, mode="w:gz") as archive:
                member = tarfile.TarInfo("content/themes/theme.txt")
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))

            with self.assertRaisesRegex(GhostImportError, "out-of-scope"):
                _read_required_images(archive_path, {"content/images/missing.png"})

    def test_rejects_path_traversal_member(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            archive_path = Path(temp_directory) / "files.tar.gz"
            with tarfile.open(archive_path, mode="w:gz") as archive:
                traversal = tarfile.TarInfo("../outside.png")
                traversal_data = _png_bytes()
                traversal.size = len(traversal_data)
                archive.addfile(traversal, io.BytesIO(traversal_data))

            with self.assertRaisesRegex(GhostImportError, "path-traversal"):
                _read_required_images(archive_path, {"content/images/missing.png"})

    def test_rejects_pax_metadata_and_pixel_limit(self):
        image_data = _png_bytes()
        with tempfile.TemporaryDirectory() as temp_directory:
            archive_path = Path(temp_directory) / "files.tar.gz"
            with tarfile.open(archive_path, mode="w:gz") as archive:
                member = tarfile.TarInfo("content/images/pixel.png")
                member.pax_headers = {"comment": "unexpected"}
                member.size = len(image_data)
                archive.addfile(member, io.BytesIO(image_data))

            with self.assertRaisesRegex(GhostImportError, "GNU/PAX"):
                _read_required_images(archive_path, {"content/images/pixel.png"})

            with tarfile.open(archive_path, mode="w:gz") as archive:
                member = tarfile.TarInfo("content/images/pixel.png")
                member.size = len(image_data)
                archive.addfile(member, io.BytesIO(image_data))

            with patch("blog.ghost_import.MAX_IMAGE_PIXELS", 1):
                with self.assertRaisesRegex(GhostImportError, "pixel limit"):
                    _read_required_images(archive_path, {"content/images/pixel.png"})

    def test_rejects_gnu_long_name_metadata_before_tar_expansion(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            archive_path = Path(temp_directory) / "files.tar.gz"
            long_name = "content/images/" + ("a" * (2 * 1024 * 1024)) + ".png"
            _write_archive(
                archive_path,
                {long_name: _png_bytes()},
                archive_format=tarfile.GNU_FORMAT,
            )

            with self.assertRaisesRegex(GhostImportError, "GNU/PAX"):
                _read_required_images(
                    archive_path,
                    {"content/images/missing.png"},
                )

    def test_bounds_total_decompressed_archive_size(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            archive_path = Path(temp_directory) / "files.tar.gz"
            _write_archive(
                archive_path,
                {"content/images/pixel.png": _png_bytes()},
            )

            with patch(
                "blog.ghost_import.MAX_ARCHIVE_DECOMPRESSED_BYTES",
                1024,
            ):
                with self.assertRaisesRegex(GhostImportError, "decompressed limit"):
                    _read_required_images(
                        archive_path,
                        {"content/images/pixel.png"},
                    )

    def test_bounds_aggregate_decoded_pixels_and_canonical_bytes(self):
        first_path = "content/images/first.png"
        second_path = "content/images/second.png"
        with tempfile.TemporaryDirectory() as temp_directory:
            archive_path = Path(temp_directory) / "files.tar.gz"
            _write_archive(
                archive_path,
                {
                    first_path: _png_bytes((1, 2, 3)),
                    second_path: _png_bytes((4, 5, 6)),
                },
            )

            with patch("blog.ghost_import.MAX_TOTAL_IMAGE_PIXELS", 7):
                with self.assertRaisesRegex(GhostImportError, "aggregate limit"):
                    _read_required_images(
                        archive_path,
                        {first_path, second_path},
                    )

            with patch("blog.ghost_import.MAX_TOTAL_CANONICAL_IMAGE_BYTES", 1):
                with self.assertRaisesRegex(GhostImportError, "aggregate limit"):
                    _read_required_images(
                        archive_path,
                        {first_path, second_path},
                    )


@override_settings(ALLOWED_EMBED_HOSTS=["embed.example"])
class StructuralHtmlSanitizerTest(TestCase):
    def test_preserves_prior_inert_markdown_and_table_structure(self):
        inert = """
            <dl><dt>Term</dt><dd>Definition<sup>1</sup><sub>x</sub></dd></dl>
            <table>
              <caption>Caption</caption>
              <colgroup><col></colgroup>
              <tbody><tr><td><del>old</del><ins>new</ins><tt>code</tt></td></tr></tbody>
            </table>
            <abbr>abbr</abbr><acronym>api</acronym>
        """

        cleaned = sanitize_structural_html(inert)

        for tag in (
            "abbr",
            "acronym",
            "caption",
            "col",
            "colgroup",
            "dd",
            "del",
            "dl",
            "dt",
            "ins",
            "sub",
            "sup",
            "tt",
        ):
            self.assertIn(f"<{tag}", cleaned)

    def test_strips_executable_html_and_preserves_explicit_structure(self):
        dirty = """
            <script>alert(1)</script>
            <p onclick="alert(2)">Text</p>
            <a href="javascript:alert(3)">bad</a>
            <img src="javascript:alert(4)" onerror="alert(5)">
            <figure><figcaption>Caption</figcaption></figure>
            <table><tbody><tr><td>Cell</td></tr></tbody></table>
            <svg viewBox="0 0 1 1" onload="alert(6)">
              <style>path { fill: #fff; }</style>
              <foreignObject><p>Foreign</p></foreignObject>
              <image xlink:href="javascript:alert(7)"></image>
              <path
                  d="M0 0"
                  fill="url(javascript:alert(9))"
                  stroke="url(https://evil.example/paint.svg)"></path>
            </svg>
            <a href="https://example.com/" target="_blank">external</a>
            <iframe
                src="https://embed.example/lab/"
                srcdoc="<script>alert(8)</script>"
                sandbox="allow-same-origin allow-scripts"
                title="Lab"></iframe>
            <iframe src="https://evil.example/lab/"></iframe>
            <iframe src="https://embed.example.evil.test/lab/"></iframe>
        """

        cleaned = sanitize_structural_html(dirty)

        self.assertNotIn("<script", cleaned)
        self.assertNotIn("onclick", cleaned)
        self.assertNotIn("onerror", cleaned)
        self.assertNotIn("onload", cleaned)
        self.assertNotIn("javascript:", cleaned)
        self.assertIn("<figure>", cleaned)
        self.assertIn("<table>", cleaned)
        self.assertIn("<svg", cleaned)
        self.assertIn("<path", cleaned)
        self.assertNotIn("<style", cleaned)
        self.assertNotIn("foreignObject", cleaned)
        self.assertNotIn("xlink", cleaned)
        self.assertNotIn("url(", cleaned)
        self.assertNotIn('target="_blank"', cleaned)
        self.assertNotIn("srcdoc", cleaned)
        self.assertIn('src="https://embed.example/lab/"', cleaned)
        self.assertNotIn('src="https://evil.example/lab/"', cleaned)
        self.assertNotIn("embed.example.evil.test", cleaned)
        self.assertIn('sandbox="allow-forms allow-popups allow-scripts"', cleaned)
        self.assertNotIn("allow-same-origin", cleaned)

    def test_removes_dangerous_style_content_and_data_document_urls(self):
        dirty = """
            <style>@import url(https://evil.example/style.css);</style>
            <div style="background: url(javascript:alert(1))">Text</div>
            <img src="data:text/html;base64,PHNjcmlwdD4=">
            <a href="JaVaScRiPt&#58;alert(2)">mixed</a>
            <a href="jav&#x09;ascript:alert(3)">entity</a>
        """

        cleaned = sanitize_structural_html(dirty)

        self.assertNotIn("@import", cleaned)
        self.assertNotIn("javascript:", cleaned)
        self.assertNotIn("data:text/html", cleaned)
