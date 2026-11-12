import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from wagtail.images.models import Image
from wagtail.images.tests.utils import get_test_image_file
from wagtail.models import Site

from blog.models import BlogIndexPage, BlogPage, ContentPage

SURFACE_TOKENS = (
    "--color-bg",
    "--color-surface",
    "--color-surface-2",
    "--color-surface-sunk",
    "--color-surface-rail",
)
TEXT_TOKENS = (
    "--color-text-primary",
    "--color-text-secondary",
    "--color-text-muted",
    "--essay-text",
    "--accent",
    "--accent-bright",
    "--series",
    "--series-bright",
    "--cat-explainer",
    "--cat-technical",
    "--cat-extra",
    "--cat-subquest",
)
# Fills that carry a label, each paired with a `-on` token for that label.
LABEL_FILL_TOKENS = (
    "--accent",
    "--series",
    "--cat-explainer",
    "--cat-technical",
    "--cat-extra",
    "--cat-subquest",
)
WCAG_AA_BODY_TEXT = 4.5


def palette_tokens(css, selector):
    """Custom properties declared in the first rule whose selector is `selector`."""
    start = css.index(f"{selector} {{")
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", css[start : css.index("}", start)]))


def relative_luminance(hex_colour):
    channels = (int(hex_colour[index : index + 2], 16) / 255 for index in (1, 3, 5))
    linear = [
        value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first, second):
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


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
        # The fixture lead post has no featured image, so it renders as a clean
        # text-only lead (CES-675) rather than an empty media placeholder.
        self.assertContains(response, "lead-post lead-post--text-only")
        self.assertNotContains(response, "lead-post__media--empty")
        self.assertNotContains(response, "lead graphic")
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
        self.assertContains(response, '<body class="page--article page--has-contents">')
        self.assertContains(response, 'class="post-actions"')

    def test_header_menu_is_the_same_four_links_on_every_page(self):
        for path in ("/", "/writing/", "/representative-note/", "/about/"):
            html = self.get_page(path).content.decode("utf-8")
            header = html[html.index('<header class="site-header">') : html.index("</header>")]

            self.assertIn('href="/writing/"', header, path)
            self.assertIn('href="/essays/"', header, path)
            self.assertIn('href="/about/"', header, path)
            self.assertNotIn("applets", header, path)
            self.assertNotIn("rss", header, path)

        about = self.get_page("/about/")
        self.assertContains(
            about,
            '<a class="site-nav__link" href="/about/" aria-current="page">about</a>',
            html=True,
        )

    def test_read_time_shows_the_deep_figure_only_when_it_differs(self):
        plain = self.get_page("/representative-note/")
        self.assertContains(plain, 'class="post-readtime__main"')
        self.assertNotContains(plain, "post-readtime__deep")

        BlogPage.objects.filter(pk=self.post.pk).update(
            body_rendered_readtime_main="4 min",
            body_rendered_readtime_deep="9 min",
        )
        self.assertContains(
            self.get_page("/representative-note/"),
            '<span class="post-readtime__deep">+9 min deep</span>',
            html=True,
        )

    def test_about_page_uses_the_static_content_composition(self):
        response = self.get_page("/about/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="content-page"')
        self.assertContains(response, 'class="content-page__body"')
        self.assertContains(response, "An independent technical notebook")
        self.assertContains(response, '<p class="eyebrow">about</p>', html=True)
        # The page is one column: the old side rail only repeated the site menu.
        self.assertNotContains(response, "content-page__rail")

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

        # 404 CTA points at the writing listing (CES-679 item 3)...
        self.assertIn("browse writing →", not_found)
        self.assertIn("/writing/", not_found)
        # ...but 500 keeps the shared default so the block override did not leak.
        self.assertIn("back to posts →", server_error)
        self.assertNotIn("browse writing →", server_error)

        # Both render inside the shared site shell and offer more than one way out.
        for rendered in (not_found, server_error):
            self.assertIn('<body class="page--error">', rendered)
            self.assertIn('class="site-header"', rendered)
            self.assertIn('class="site-footer"', rendered)
            self.assertIn('<h1 id="error-heading">', rendered)
        self.assertIn('<a href="/essays/">essays →</a>', not_found)
        self.assertIn('<a href="/">home →</a>', not_found)

    def test_katex_is_gated_to_math_posts_only(self):
        math_post = BlogPage(
            title="A note with equations",
            slug="math-note",
            date=date(2026, 7, 31),
            body=[("markdown", "A display block $$E = mc^2$$ inline.")],
        )
        self.index.add_child(instance=math_post)
        math_post.save_revision().publish()

        math_html = self.get_page("/math-note/").content.decode("utf-8")
        self.assertIn("katex.min.css", math_html)
        self.assertIn("katex.min.js", math_html)

        # The non-math post must not pull KaTeX.
        plain_html = self.get_page("/representative-note/").content.decode("utf-8")
        self.assertNotIn("katex.min.css", plain_html)

        # And KaTeX must not load site-wide (home + writing listing).
        self.assertNotIn("katex", self.get_page("/").content.decode("utf-8"))
        self.assertNotIn("katex", self.get_page("/writing/").content.decode("utf-8"))

    def test_math_blog_checkbox_force_loads_katex(self):
        # No math delimiters anywhere in the body — only the editor checkbox.
        forced = BlogPage(
            title="Forced math note",
            slug="forced-math-note",
            date=date(2026, 8, 1),
            body=[("markdown", "No delimiters here, but the applet needs KaTeX.")],
            force_math=True,
        )
        self.index.add_child(instance=forced)
        forced.save_revision().publish()

        html = self.get_page("/forced-math-note/").content.decode("utf-8")
        self.assertIn("katex.min.css", html)
        self.assertIn("katex.min.js", html)

    def test_head_wires_apple_touch_icon_and_manifest(self):
        html = self.get_page("/").content.decode("utf-8")
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn('sizes="180x180"', html)
        self.assertIn('rel="manifest"', html)

    def test_web_manifest_route_serves_json(self):
        response = self.client.get(
            "/site.webmanifest", secure=True, HTTP_HOST="design.test"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        body = response.content.decode("utf-8")
        self.assertIn('"192x192"', body)
        self.assertIn('"512x512"', body)
        self.assertIn("#0b1020", body)
        self.assertIn('"purpose": "maskable"', body)

    def test_body_image_renders_srcset_and_preserves_alt(self):
        image = Image.objects.create(
            title="Body figure title",
            file=get_test_image_file(filename="body-figure.png"),
        )
        post = BlogPage(
            title="Post with a body image",
            slug="body-image-post",
            date=date(2026, 7, 26),
            body=[("image", {"image": image, "caption": ""})],
        )
        self.index.add_child(instance=post)
        post.save_revision().publish()

        html = self.get_page("/body-image-post/").content.decode("utf-8")
        self.assertIn('class="post-image"', html)
        self.assertIn("srcset=", html)
        self.assertIn("sizes=", html)
        # Alt falls back to the image title when there is no caption.
        self.assertIn('alt="Body figure title"', html)

    def test_lead_post_with_image_is_not_text_only(self):
        image = Image.objects.create(
            title="Lead hero",
            file=get_test_image_file(filename="lead-hero.png"),
        )
        lead = BlogPage(
            title="Illustrated lead",
            slug="illustrated-lead",
            date=date(2026, 8, 1),
            featured_image=image,
            body=[("heading", "Heading")],
        )
        self.index.add_child(instance=lead)
        lead.save_revision().publish()

        html = self.get_page("/writing/").content.decode("utf-8")
        self.assertIn("lead-post__media", html)
        self.assertNotIn("lead-post--text-only", html)

    def test_css_declares_tokens_focus_and_reduced_motion_contracts(self):
        css_path = Path(settings.BASE_DIR) / "static" / "css" / "site.css"
        css = css_path.read_text(encoding="utf-8")

        self.assertIn("--color-bg:", css)
        self.assertIn("--color-surface-sunk:", css)
        self.assertIn("--accent-wash:", css)
        self.assertIn("--series-wash:", css)
        self.assertIn("--font-head:", css)
        self.assertIn("--measure-reading:", css)
        self.assertIn("--font-serif:", css)
        self.assertIn("--essay-column:", css)
        self.assertIn(".page--essay .post-content", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("@media (prefers-color-scheme: light)", css)
        self.assertIn(".post-content table", css)
        self.assertIn(".post-content .katex-display", css)
        self.assertNotIn("--shadow-panel", css)
        self.assertNotIn("--color-surface-elevated", css)
        self.assertNotIn("background-image:", css)
        self.assertNotIn(".post-card:hover", css)

    def test_palettes_keep_text_readable_on_every_surface(self):
        css_path = Path(settings.BASE_DIR) / "static" / "css" / "site.css"
        css = css_path.read_text(encoding="utf-8")
        dark = palette_tokens(css, ":root")
        light = palette_tokens(css, ':root[data-theme="light"]')

        # The OS-preference block and the explicit theme are two copies of one palette.
        self.assertEqual(light, palette_tokens(css, ':root:not([data-theme="dark"])'))

        pairs = [(text, surface) for text in TEXT_TOKENS for surface in SURFACE_TOKENS]
        pairs += [(f"{fill}-on", fill) for fill in LABEL_FILL_TOKENS]
        for name, tokens in (("dark", dark), ("light", dark | light)):
            for text, surface in pairs:
                with self.subTest(palette=name, text=text, surface=surface):
                    self.assertGreaterEqual(
                        contrast_ratio(tokens[text], tokens[surface]),
                        WCAG_AA_BODY_TEXT,
                    )

    def test_applet_shell_supports_intrinsic_and_constrained_heights(self):
        static_dir = Path(settings.BASE_DIR) / "static"
        applet_css = (static_dir / "css" / "applet-base.css").read_text(encoding="utf-8")
        site_css = (static_dir / "css" / "site.css").read_text(encoding="utf-8")
        blog_js = (static_dir / "js" / "blog-post.js").read_text(encoding="utf-8")

        self.assertIn("html, body { min-height: 100%; margin: 0; }", applet_css)
        self.assertIn("align-items: flex-start;", applet_css)
        self.assertIn("margin-block: auto;", applet_css)
        self.assertNotIn("html, body { height: 100%;", applet_css)
        self.assertIn("html.is-embedded.is-height-constrained body", applet_css)
        self.assertIn("overflow-y: auto;", applet_css)
        self.assertIn("scrollbar-gutter: auto;", applet_css)
        self.assertNotIn("scrollbar-gutter: stable;", applet_css)
        self.assertIn("height: var(--applet-frame-height, 240px);", site_css)
        self.assertIn("min-height: 120px;", site_css)
        self.assertNotIn("min-height: var(--applet-frame-height", site_css)
        self.assertIn("measureEmbeddedContentHeight", blog_js)
        self.assertIn('classList.toggle("is-height-constrained"', blog_js)
        self.assertIn('frame.style.minHeight = "120px";', blog_js)
        self.assertNotIn("html.scrollHeight", blog_js)

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
            "ibm-plex-serif-400-latin.woff2",
            "ibm-plex-serif-400-italic-latin.woff2",
            "ibm-plex-serif-600-latin.woff2",
        }

        self.assertTrue(expected_fonts.issubset({path.name for path in font_dir.glob("*.woff2")}))
