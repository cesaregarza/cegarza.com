"""Metadata, title, description, and social-preview contracts (CES-674)."""

import re
from datetime import date

from django.test import TestCase, override_settings
from wagtail.images.tests.utils import get_test_image_file
from wagtail.models import Site

from blog.context_processors import site_identity_values
from blog.models import BlogIndexPage, BlogPage, ContentPage


def _meta(html, attr, name):
    """Return the content of a <meta {attr}="{name}" content="..."> tag."""
    match = re.search(
        rf'<meta {attr}="{re.escape(name)}" content="(.*?)"',
        html,
    )
    return match.group(1) if match else None


def _title(html):
    match = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    return match.group(1) if match else None


def _canonical(html):
    match = re.search(r'<link rel="canonical" href="(.*?)"', html)
    return match.group(1) if match else None


@override_settings(
    ALLOWED_HOSTS=["meta.test"],
    SECURE_SSL_REDIRECT=False,
    SITE_ROLE="ML / Data / Infra Engineer",
    SITE_ROLE_DESCRIPTION="A real one-line self description.",
)
class MetadataTemplateTest(TestCase):
    def setUp(self):
        default_site = Site.objects.get(is_default_site=True)
        tree_root = default_site.root_page
        self.index = BlogIndexPage(
            title="Bringing Down The Gauss",
            slug="blog",
            intro="Open notebook description",
            default_author_name="Cesar Garza",
            signpost_heading="Cesar Garza",
            signpost_intro="I build ML systems and write about them.",
        )
        tree_root.add_child(instance=self.index)
        self.index.save_revision().publish()

        self.post = BlogPage(
            title="A representative note",
            slug="representative-note",
            date=date(2026, 7, 30),
            abstract="A compact abstract for the article masthead.",
            body=[("heading", "First observation")],
        )
        self.index.add_child(instance=self.post)
        self.post.save_revision().publish()

        self.plain_post = BlogPage(
            title="Untitled thoughts",
            slug="plain-post",
            date=date(2026, 7, 29),
            body=[("heading", "Only a heading")],
        )
        self.index.add_child(instance=self.plain_post)
        self.plain_post.save_revision().publish()

        self.desc_only_post = BlogPage(
            title="Search desc post",
            slug="desc-only-post",
            date=date(2026, 7, 28),
            search_description="Only a search description here.",
            body=[("heading", "Heading")],
        )
        self.index.add_child(instance=self.desc_only_post)
        self.desc_only_post.save_revision().publish()

        self.featured_post = BlogPage(
            title="Featured post",
            slug="featured-post",
            date=date(2026, 7, 27),
            featured_image=self._image("hero"),
            body=[("heading", "Heading")],
        )
        self.index.add_child(instance=self.featured_post)
        self.featured_post.save_revision().publish()

        self.about = ContentPage(
            title="About",
            slug="about",
            body=[("markdown", "An independent technical notebook.")],
        )
        self.index.add_child(instance=self.about)
        self.about.save_revision().publish()

        default_site.root_page = self.index
        default_site.hostname = "meta.test"
        default_site.port = 443
        default_site.site_name = "cegarza.com"
        default_site.save()
        self.site = default_site

    def _image(self, name):
        from wagtail.images.models import Image

        return Image.objects.create(
            title=name,
            file=get_test_image_file(filename=f"{name}.png"),
        )

    def get(self, path):
        return self.client.get(path, secure=True, HTTP_HOST="meta.test").content.decode(
            "utf-8"
        )

    # --- Titles -------------------------------------------------------------

    def test_home_title_is_name_first_with_no_site_suffix(self):
        html = self.get("/")
        self.assertEqual(_title(html), "Cesar Garza — ML / Data / Infra Engineer")
        self.assertNotIn(" | cegarza.com", html.split("</title>")[0])
        self.assertEqual(
            _meta(html, "property", "og:title"),
            "Cesar Garza — ML / Data / Infra Engineer",
        )
        self.assertEqual(
            _meta(html, "name", "twitter:title"),
            "Cesar Garza — ML / Data / Infra Engineer",
        )
        self.assertNotEqual(
            _meta(html, "name", "description"), "Thoughts, stories and ideas."
        )

    def test_writing_title_is_writing_dash_name(self):
        html = self.get("/writing/")
        self.assertEqual(_title(html), "Writing — Cesar Garza")
        self.assertEqual(_meta(html, "property", "og:title"), "Writing — Cesar Garza")
        self.assertEqual(_meta(html, "name", "twitter:title"), "Writing — Cesar Garza")

    def test_post_title_appends_site_suffix_once(self):
        html = self.get("/representative-note/")
        self.assertEqual(_title(html), "A representative note | cegarza.com")
        # Regression guard: dedup did not drop the legitimate suffix.
        self.assertEqual(html.count("A representative note | cegarza.com"), 1)

    def test_title_dedup_when_page_title_equals_site_name(self):
        # Rename the index so its page title equals the site name.
        self.index.title = "cegarza.com"
        self.index.save_revision().publish()
        html = self.get("/writing/")
        # Writing route overrides the whole title block, so it is always
        # "Writing — Cesar Garza" with no doubled site name.
        self.assertNotIn("cegarza.com | cegarza.com", html)

    # --- Descriptions -------------------------------------------------------

    def test_description_uses_abstract_never_tagline(self):
        html = self.get("/representative-note/")
        expected = "A compact abstract for the article masthead."
        self.assertEqual(_meta(html, "name", "description"), expected)
        self.assertEqual(_meta(html, "property", "og:description"), expected)
        self.assertEqual(_meta(html, "name", "twitter:description"), expected)
        self.assertNotIn("Thoughts, stories and ideas.", html)

    def test_description_falls_back_to_search_description(self):
        html = self.get("/desc-only-post/")
        expected = "Only a search description here."
        self.assertEqual(_meta(html, "name", "description"), expected)
        self.assertEqual(_meta(html, "property", "og:description"), expected)
        self.assertEqual(_meta(html, "name", "twitter:description"), expected)

    def test_description_empty_when_no_abstract_or_search_description(self):
        html = self.get("/plain-post/")
        self.assertEqual(_meta(html, "name", "description"), "")
        self.assertEqual(_meta(html, "property", "og:description"), "")
        self.assertEqual(_meta(html, "name", "twitter:description"), "")
        self.assertNotIn("Thoughts, stories and ideas.", html)

    # --- Social image default ----------------------------------------------

    def test_about_page_uses_default_og_card(self):
        html = self.get("/about/")
        self.assertIn(
            'content="https://meta.test/static/img/og-default.png"', html
        )
        self.assertEqual(_meta(html, "property", "og:image:width"), "1200")
        self.assertEqual(_meta(html, "property", "og:image:height"), "630")
        self.assertIn(
            '<meta name="twitter:image" content="https://meta.test/static/img/og-default.png"',
            html,
        )

    def test_featured_post_uses_rendition_not_default(self):
        html = self.get("/featured-post/")
        self.assertNotIn("og-default.png", html)
        self.assertIn("fill-1200x630", _meta(html, "property", "og:image"))

    # --- og:url == canonical ------------------------------------------------

    def test_og_url_equals_canonical(self):
        html = self.get("/representative-note/")
        self.assertEqual(
            _meta(html, "property", "og:url"),
            _canonical(html),
        )
        self.assertEqual(
            _meta(html, "property", "og:url"),
            "https://meta.test/representative-note/",
        )


class SiteIdentityContextTest(TestCase):
    @override_settings(
        SITE_ROLE="ML / Data / Infra Engineer",
        SITE_ROLE_DESCRIPTION="Self description line.",
        SITE_AUTHOR="Cesar Garza",
    )
    def test_derived_titles_and_role(self):
        default_site = Site.objects.get(is_default_site=True)
        tree_root = default_site.root_page
        index = BlogIndexPage(
            title="Index",
            slug="idx",
            default_author_name="Cesar Garza",
        )
        tree_root.add_child(instance=index)
        default_site.root_page = index
        default_site.save()

        values = site_identity_values(default_site)
        self.assertEqual(
            values["site_home_title"], "Cesar Garza — ML / Data / Infra Engineer"
        )
        self.assertEqual(values["site_writing_title"], "Writing — Cesar Garza")
        self.assertEqual(values["site_role"], "ML / Data / Infra Engineer")
        self.assertEqual(values["site_role_description"], "Self description line.")

    @override_settings(SITE_AUTHOR="Fallback Author", SITE_ROLE="Engineer")
    def test_author_honors_index_default_author_name(self):
        default_site = Site.objects.get(is_default_site=True)
        tree_root = default_site.root_page
        index = BlogIndexPage(
            title="Index",
            slug="idx2",
            default_author_name="Real Name",
        )
        tree_root.add_child(instance=index)
        default_site.root_page = index
        default_site.save()

        values = site_identity_values(default_site)
        self.assertEqual(values["site_author"], "Real Name")
        self.assertEqual(values["site_home_title"], "Real Name — Engineer")
