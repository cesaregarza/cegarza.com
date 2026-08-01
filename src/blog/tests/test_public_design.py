from datetime import date
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from wagtail.models import Site

from blog.models import BlogIndexPage, BlogPage, ContentPage


@override_settings(
    ALLOWED_HOSTS=["design.test"],
    SECURE_SSL_REDIRECT=False,
)
class PublicDesignTemplateTest(TestCase):
    def setUp(self):
        default_site = Site.objects.get(is_default_site=True)
        tree_root = default_site.root_page

        self.index = BlogIndexPage(
            title="Bringing Down The Gauss",
            slug="notes",
            intro="Thoughts, stories and ideas.",
            default_author_name="Cesar Garza",
        )
        tree_root.add_child(instance=self.index)
        self.index.save_revision().publish()

        self.post = BlogPage(
            title="A representative technical field note",
            slug="representative-note",
            date=date(2026, 7, 30),
            abstract="A compact summary for the redesigned article masthead.",
            body=[
                ("heading", "First observation"),
                (
                    "markdown",
                    "Readable long-form copy with a [reference](https://example.com).\n\n"
                    "| Signal | Value |\n| --- | ---: |\n| alpha | 0.42 |",
                ),
                (
                    "code",
                    {
                        "language": "python",
                        "code": "signal = observations.mean()",
                    },
                ),
            ],
        )
        self.index.add_child(instance=self.post)
        self.post.save_revision().publish()

        self.about = ContentPage(
            title="About",
            slug="about",
            body=[
                (
                    "markdown",
                    "An independent technical notebook about models and systems.",
                )
            ],
        )
        self.index.add_child(instance=self.about)
        self.about.save_revision().publish()

        self.site = Site.objects.create(
            hostname="design.test",
            port=443,
            site_name="Bringing Down The Gauss",
            root_page=self.index,
        )

    def get_page(self, path):
        return self.client.get(path, secure=True, HTTP_HOST="design.test")

    def test_index_composes_the_shared_editorial_system(self):
        response = self.get_page("/writing/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="skip-link"')
        self.assertContains(response, 'class="site-nav"')
        self.assertContains(response, 'class="index-hero"')
        self.assertContains(response, 'class="index-stats"')
        self.assertContains(response, 'class="lead-post"')
        self.assertContains(response, 'id="applets"')
        self.assertContains(response, "3 interactive notes")
        self.assertContains(response, "A representative technical field note")
        self.assertContains(response, "site-footer__inner")

    def test_article_keeps_rich_content_and_accessible_outline_landmarks(self):
        response = self.get_page("/representative-note/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="post-header"')
        self.assertContains(response, 'class="content post-content"')
        self.assertContains(response, "First observation")
        self.assertContains(response, "<table>")
        self.assertContains(response, "signal = observations.mean()")
        self.assertContains(response, 'class="code-block"')
        self.assertContains(response, 'id="postTocProgress"')
        self.assertContains(response, 'id="readingStatus"')
        self.assertContains(response, 'aria-controls="postOutline"')
        self.assertContains(response, 'id="postOutline"')
        self.assertContains(response, 'class="post-nav"')

    def test_about_page_uses_the_static_content_composition(self):
        response = self.get_page("/about/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="content-page"')
        self.assertContains(response, 'class="content-page__body"')
        self.assertContains(response, "An independent technical notebook")
        self.assertContains(response, 'class="content-page__rail"')

    def test_error_states_share_tokens_and_remain_noindex(self):
        context = {
            "site_name": "Bringing Down The Gauss",
            "site_author": "Cesar Garza",
        }
        not_found = render_to_string("404.html", context)
        server_error = render_to_string("500.html", context)

        self.assertIn('name="robots" content="noindex,nofollow"', not_found)
        self.assertIn('class="error-band"', not_found)
        self.assertIn("There is nothing at this address.", not_found)
        self.assertIn('class="error-band"', server_error)
        self.assertIn("The server could not complete that request.", server_error)

    def test_css_declares_tokens_focus_and_reduced_motion_contracts(self):
        css_path = Path(settings.BASE_DIR) / "static" / "css" / "site.css"
        css = css_path.read_text(encoding="utf-8")

        self.assertIn("--color-bg:", css)
        self.assertIn("--color-surface-sunk:", css)
        self.assertIn("--accent-wash:", css)
        self.assertIn("--series-wash:", css)
        self.assertIn("--font-head:", css)
        self.assertIn("--measure-reading:", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("@media (prefers-color-scheme: light)", css)
        self.assertIn(".post-content table", css)
        self.assertIn(".post-content .katex-display", css)
        self.assertNotIn("--shadow-panel", css)
        self.assertNotIn("--color-surface-elevated", css)
        self.assertNotIn("background-image:", css)
        self.assertNotIn(".post-card:hover", css)

    def test_console_fonts_are_self_hosted(self):
        font_dir = Path(settings.BASE_DIR) / "static" / "fonts"
        expected_fonts = {
            "archivo-500-latin.woff2",
            "archivo-600-latin.woff2",
            "archivo-700-latin.woff2",
            "ibm-plex-mono-400-latin.woff2",
            "ibm-plex-mono-500-latin.woff2",
            "ibm-plex-mono-600-latin.woff2",
            "ibm-plex-sans-400-latin.woff2",
            "ibm-plex-sans-500-latin.woff2",
            "ibm-plex-sans-600-latin.woff2",
            "ibm-plex-sans-700-latin.woff2",
        }

        self.assertTrue(expected_fonts.issubset({path.name for path in font_dir.glob("*.woff2")}))
