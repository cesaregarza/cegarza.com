import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image as PillowImage
from wagtail.images import get_image_model
from wagtail.models import Page, PageViewRestriction, Site

from blog.models import (
    BlogIndexPage,
    BlogPage,
    WagtailImageImport,
    WagtailPageImport,
)
from blog.wagtail_port import (
    WagtailPortError,
    _stable_image_storage_target,
    import_wagtail_bundle,
    load_wagtail_bundle,
    set_imported_page_password,
    snapshot_sha256,
)
from home.models import HomePage


def _png_bytes(color):
    output = io.BytesIO()
    PillowImage.new("RGB", (2, 2), color=color).save(output, format="PNG")
    return output.getvalue()


def _block(block_type, value):
    return {
        "type": block_type,
        "value": value,
        "id": str(uuid4()),
    }


def _snapshot(slug, title, image_id, markdown):
    return {
        "title": title,
        "slug": slug,
        "seo_title": "",
        "search_description": f"{title} description",
        "show_in_menus": False,
        "date": "2026-01-17",
        "is_featured": False,
        "abstract": f"{title} abstract",
        "body": [
            _block("markdown", markdown),
            _block(
                "image",
                {
                    "image": image_id,
                    "caption": "Synthetic diagram",
                },
            ),
            _block(
                "applet_embed",
                {
                    "title": "Synthetic applet",
                    "src": "/static/applets/loser-winner.html",
                    "lazy_load": True,
                    "use_full_height": False,
                    "max_height": 700,
                    "style_overrides": "",
                },
            ),
        ],
        "featured_image_id": image_id,
        "social_image_id": None,
    }


def _state(snapshot):
    return {
        "snapshot": snapshot,
        "sha256": snapshot_sha256(snapshot),
    }


def _manifest():
    first_image = _png_bytes((10, 20, 30))
    second_image = _png_bytes((40, 50, 60))
    images = []
    files = {}
    for source_id, filename, data, source_url in (
        (101, "first.png", first_image, "https://assets.example/first.png"),
        (102, "second.png", second_image, "https://assets.example/second.png"),
    ):
        digest = hashlib.sha256(data).hexdigest()
        member = f"media/{source_id}/{digest}/{filename}"
        images.append(
            {
                "source_image_id": source_id,
                "source_name": f"original_images/{filename}",
                "source_urls": [source_url, f"/media/original_images/{filename}"],
                "filename": filename,
                "member": member,
                "title": filename,
                "sha256": digest,
                "size": len(data),
                "width": 2,
                "height": 2,
            }
        )
        files[member] = data

    public_snapshot = _snapshot(
        "public-source-post",
        "Public source post",
        101,
        "Public body ![](https://assets.example/first.png)",
    )
    restricted_live = _snapshot(
        "restricted-source-post",
        "Restricted source post",
        102,
        "Published restricted body",
    )
    restricted_draft = deepcopy(restricted_live)
    restricted_draft["abstract"] = "Unpublished draft abstract"
    restricted_draft["body"][0]["value"] = "Newer unpublished body"
    return (
        {
            "schema_version": 1,
            "source_namespace": "source-primary",
            "source_index_page_id": 40,
            "exported_at": "2026-07-30T12:00:00+00:00",
            "pages": [
                {
                    "source_page_id": 41,
                    "live": _state(public_snapshot),
                    "draft": None,
                    "first_published_at": "2026-01-16T09:02:41+00:00",
                    "last_published_at": "2026-01-16T09:02:41+00:00",
                    "restriction": {"type": "none"},
                },
                {
                    "source_page_id": 42,
                    "live": _state(restricted_live),
                    "draft": _state(restricted_draft),
                    "first_published_at": "2026-01-20T17:47:18+00:00",
                    "last_published_at": "2026-02-09T06:28:35+00:00",
                    "restriction": {"type": "password"},
                },
            ],
            "images": images,
        },
        files,
    )


def _write_bundle(path, manifest, files, *, extra_files=None):
    with tarfile.open(path, mode="w:gz", format=tarfile.USTAR_FORMAT) as archive:
        manifest_data = json.dumps(
            manifest,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        member = tarfile.TarInfo("manifest.json")
        member.size = len(manifest_data)
        archive.addfile(member, io.BytesIO(manifest_data))
        for name, data in {**files, **(extra_files or {})}.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


def _bundle_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class WagtailPortTests(TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.override = override_settings(
            MEDIA_ROOT=self.temp_directory.name,
            ALLOWED_HOSTS=["destination.example", "testserver"],
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

        root = Page.get_first_root_node()
        home = HomePage(title="Destination", slug="destination")
        root.add_child(instance=home)
        self.index = BlogIndexPage(title="Articles", slug="articles")
        home.add_child(instance=self.index)
        site = Site.objects.get(is_default_site=True)
        site.hostname = "destination.example"
        site.port = 443
        site.root_page = home
        site.save()

        placeholder = get_image_model()(
            title="Dry-run validation image",
            width=2,
            height=2,
        )
        placeholder.file.save(
            "dry-run-validation.png",
            ContentFile(_png_bytes((1, 2, 3))),
            save=False,
        )
        placeholder.width = 2
        placeholder.height = 2
        placeholder.save()
        self.manifest, self.files = _manifest()
        self.bundle_path = Path(self.temp_directory.name) / "bundle.tar.gz"
        _write_bundle(self.bundle_path, self.manifest, self.files)
        self.initial_media_files = {
            path.relative_to(self.temp_directory.name)
            for path in Path(self.temp_directory.name).rglob("*")
            if path.is_file()
        }

    def _run(self, *, dry_run=False):
        return import_wagtail_bundle(
            self.bundle_path,
            hostname="destination.example",
            port=443,
            expected_namespace="source-primary",
            expected_bundle_sha256=_bundle_sha256(self.bundle_path),
            dry_run=dry_run,
        )

    def test_import_preserves_live_draft_restriction_media_and_is_idempotent(self):
        dry_run = self._run(dry_run=True)
        self.assertTrue(dry_run.dry_run)
        self.assertEqual(dry_run.created_pages, 2)
        self.assertEqual(dry_run.created_images, 2)
        self.assertEqual(BlogPage.objects.descendant_of(self.index).count(), 0)

        first = self._run()
        self.assertEqual(first.created_pages, 2)
        self.assertEqual(first.updated_pages, 0)
        self.assertEqual(first.unchanged_pages, 0)
        self.assertEqual(first.created_images, 2)
        self.assertEqual(WagtailPageImport.objects.count(), 2)
        self.assertEqual(WagtailImageImport.objects.count(), 2)

        public = BlogPage.objects.get(slug="public-source-post")
        restricted = BlogPage.objects.get(slug="restricted-source-post")
        self.assertTrue(public.live)
        self.assertTrue(restricted.live)
        self.assertFalse(public.has_unpublished_changes)
        self.assertTrue(restricted.has_unpublished_changes)
        self.assertEqual(
            PageViewRestriction.objects.get(page=restricted).restriction_type,
            PageViewRestriction.PASSWORD,
        )
        self.assertFalse(PageViewRestriction.objects.filter(page=public).exists())

        restricted_live = restricted.live_revision.as_object().specific
        restricted_draft = restricted.get_latest_revision().as_object().specific
        self.assertEqual(restricted_live.abstract, "Restricted source post abstract")
        self.assertEqual(restricted_draft.abstract, "Unpublished draft abstract")
        self.assertEqual(
            restricted_live.first_published_at.isoformat(),
            "2026-01-20T17:47:18+00:00",
        )

        public_markdown = public.live_revision.as_object().specific.body.raw_data[0][
            "value"
        ]
        self.assertNotIn("https://assets.example/first.png", public_markdown)
        self.assertIn("/media/original_images/", public_markdown)

        for mapping in WagtailImageImport.objects.select_related("image"):
            with mapping.image.file.storage.open(mapping.image.file.name, "rb") as stored:
                self.assertEqual(
                    hashlib.sha256(stored.read()).hexdigest(),
                    mapping.source_sha256,
                )

        revision_counts = {
            page.pk: page.revisions.count() for page in (public, restricted)
        }
        image_count = get_image_model().objects.count()
        second = self._run()
        self.assertEqual(second.created_pages, 0)
        self.assertEqual(second.updated_pages, 0)
        self.assertEqual(second.unchanged_pages, 2)
        self.assertEqual(second.created_images, 0)
        self.assertEqual(second.unchanged_images, 2)
        self.assertEqual(get_image_model().objects.count(), image_count)
        self.assertEqual(
            {
                page.pk: page.revisions.count()
                for page in BlogPage.objects.filter(pk__in=revision_counts)
            },
            revision_counts,
        )

    def test_destination_editorial_drift_fails_closed(self):
        self._run()
        page = BlogPage.objects.get(slug="public-source-post")
        page.abstract = "Destination editor changed this"
        page.save_revision()

        with self.assertRaisesRegex(WagtailPortError, "editorial drift"):
            self._run()

    def test_destination_publication_timestamp_drift_fails_closed(self):
        self._run()
        page = BlogPage.objects.get(slug="public-source-post")
        Page.objects.filter(pk=page.pk).update(
            first_published_at=page.first_published_at + timedelta(seconds=1)
        )

        with self.assertRaisesRegex(WagtailPortError, "timestamps drifted"):
            self._run()

    def test_password_transfer_changes_only_existing_restriction(self):
        self._run()
        mapping = WagtailPageImport.objects.get(
            source_namespace="source-primary",
            source_page_id=42,
        )
        restriction = PageViewRestriction.objects.get(page=mapping.page)
        rotated_password = restriction.password

        set_imported_page_password("source-primary", 42, "synthetic-shared-password")

        restriction.refresh_from_db()
        self.assertNotEqual(restriction.password, rotated_password)
        self.assertEqual(restriction.password, "synthetic-shared-password")
        with self.assertRaisesRegex(WagtailPortError, "does not have one"):
            set_imported_page_password("source-primary", 41, "must-fail")

    def test_bundle_rejects_sensitive_fields_before_writes(self):
        manifest = deepcopy(self.manifest)
        manifest["pages"][1]["restriction"]["password"] = "must-not-import"
        _write_bundle(self.bundle_path.with_name("sensitive.tar.gz"), manifest, self.files)

        with self.assertRaisesRegex(WagtailPortError, "unsupported fields|sensitive"):
            path = self.bundle_path.with_name("sensitive.tar.gz")
            import_wagtail_bundle(
                path,
                hostname="destination.example",
                port=443,
                expected_namespace="source-primary",
                expected_bundle_sha256=_bundle_sha256(path),
            )
        self.assertEqual(WagtailPageImport.objects.count(), 0)

    def test_bundle_rejects_unreferenced_and_unsafe_members(self):
        path = self.bundle_path.with_name("unsafe.tar.gz")
        _write_bundle(
            path,
            self.manifest,
            self.files,
            extra_files={"../escape.txt": b"no"},
        )
        with self.assertRaises(WagtailPortError):
            import_wagtail_bundle(
                path,
                hostname="destination.example",
                port=443,
                expected_namespace="source-primary",
                expected_bundle_sha256=_bundle_sha256(path),
            )

    def test_bundle_sha_pin_is_required_and_enforced(self):
        with self.assertRaisesRegex(WagtailPortError, "SHA-256 does not match"):
            import_wagtail_bundle(
                self.bundle_path,
                hostname="destination.example",
                port=443,
                expected_namespace="source-primary",
                expected_bundle_sha256="0" * 64,
            )
        self.assertEqual(WagtailPageImport.objects.count(), 0)

    def test_dry_run_rejects_storage_collision_before_database_writes(self):
        _manifest_payload, image_payloads = load_wagtail_bundle(
            self.bundle_path,
            expected_namespace="source-primary",
            expected_sha256=_bundle_sha256(self.bundle_path),
        )
        payload = image_payloads[101]
        _image, storage, expected_name = _stable_image_storage_target(
            "source-primary",
            payload,
        )
        storage.save(expected_name, ContentFile(b"unexpected"))
        self.addCleanup(storage.delete, expected_name)

        with self.assertRaisesRegex(WagtailPortError, "unexpected bytes"):
            self._run(dry_run=True)

        self.assertEqual(WagtailPageImport.objects.count(), 0)
        self.assertEqual(WagtailImageImport.objects.count(), 0)

    def test_dry_run_exercises_rewritten_revision_validation(self):
        body_block = BlogPage._meta.get_field("body").stream_block
        with patch.object(
            body_block,
            "clean",
            side_effect=ValidationError("synthetic rewritten body failure"),
        ):
            with self.assertRaisesRegex(
                WagtailPortError,
                "rewritten revision validation",
            ):
                self._run(dry_run=True)

        self.assertEqual(WagtailPageImport.objects.count(), 0)
        self.assertEqual(WagtailImageImport.objects.count(), 0)

    def test_media_files_are_removed_when_database_import_rolls_back(self):
        with patch(
            "blog.wagtail_port._import_page",
            side_effect=RuntimeError("synthetic failure"),
        ):
            with self.assertRaisesRegex(WagtailPortError, "import failed"):
                self._run()

        self.assertEqual(WagtailPageImport.objects.count(), 0)
        self.assertEqual(WagtailImageImport.objects.count(), 0)
        self.assertEqual(
            {
                path.relative_to(self.temp_directory.name)
                for path in Path(self.temp_directory.name).rglob("*")
                if path.is_file()
            },
            self.initial_media_files,
        )

    @unittest.skipUnless(
        os.environ.get("WAGTAIL_PORT_OPERATOR_BUNDLE")
        and os.environ.get("WAGTAIL_PORT_OPERATOR_BUNDLE_SHA256"),
        "operator bundle and its pinned SHA-256 are not available",
    )
    def test_operator_bundle_imports_and_repeats_as_noop(self):
        bundle = os.environ["WAGTAIL_PORT_OPERATOR_BUNDLE"]
        dry_run = import_wagtail_bundle(
            bundle,
            hostname="destination.example",
            port=443,
            expected_namespace="legacy-wagtail-primary",
            expected_bundle_sha256=os.environ[
                "WAGTAIL_PORT_OPERATOR_BUNDLE_SHA256"
            ],
            dry_run=True,
        )
        self.assertEqual(dry_run.pages, 2)
        self.assertEqual(dry_run.images, 14)
        self.assertEqual(dry_run.restricted_pages, 1)
        self.assertEqual(dry_run.draft_pages, 1)

        first = import_wagtail_bundle(
            bundle,
            hostname="destination.example",
            port=443,
            expected_namespace="legacy-wagtail-primary",
            expected_bundle_sha256=os.environ[
                "WAGTAIL_PORT_OPERATOR_BUNDLE_SHA256"
            ],
        )
        self.assertEqual(first.created_pages, 2)
        self.assertEqual(first.created_images, 14)

        second = import_wagtail_bundle(
            bundle,
            hostname="destination.example",
            port=443,
            expected_namespace="legacy-wagtail-primary",
            expected_bundle_sha256=os.environ[
                "WAGTAIL_PORT_OPERATOR_BUNDLE_SHA256"
            ],
        )
        self.assertEqual(second.created_pages, 0)
        self.assertEqual(second.created_images, 0)
        self.assertEqual(second.unchanged_pages, 2)
        self.assertEqual(second.unchanged_images, 14)
