import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.db.transaction import TransactionManagementError
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.test import TestCase as DjangoTestCase
from wagtail.models import PageViewRestriction

from blog.context_processors import site_identity
from blog.feeds import BlogFeed
from blog.markdown_extensions.random_choice import RandomChoicePreprocessor
from blog.middleware import FrontendSecurityHeadersMiddleware
from blog.models import AppletEmbedBlock, BlogPage, precompute_blog_body_render_cache
from blog.robots import robots_txt
from blog.templatetags.blog_sanitize import sanitize_html
from blog.views import _enforce_view_restrictions, _render_block, custom_500


class TestRobotsTxt(TestCase):
    def test_robots_uses_site_root_and_disallows_sensitive_paths(self):
        request = RequestFactory().get("/robots.txt")
        site = SimpleNamespace(root_url="https://blog.example.com")
        with patch("blog.robots.Site.find_for_request", return_value=site):
            response = robots_txt(request)
        body = response.content.decode("utf-8")
        self.assertIn("Disallow: /admin/", body)
        self.assertIn("Disallow: /health/", body)
        self.assertIn("Disallow: /*.md$", body)
        self.assertIn("Sitemap: https://blog.example.com/sitemap.xml", body)


class TestDeploymentSiteIdentity(TestCase):
    @patch("blog.context_processors.Site.find_for_request", return_value=None)
    @patch("blog.context_processors.settings")
    def test_context_uses_deployment_identity(self, settings_mock, _site_mock):
        settings_mock.SITE_NAME = "Example Notes"
        settings_mock.SITE_DESCRIPTION = "Example description"
        settings_mock.SITE_AUTHOR = "Example Author"
        settings_mock.WAGTAILADMIN_BASE_URL = "https://example.test/admin/"

        context = site_identity(RequestFactory().get("/"))

        self.assertEqual(context["site_name"], "Example Notes")
        self.assertEqual(context["site_description"], "Example description")
        self.assertEqual(context["site_author"], "Example Author")
        self.assertEqual(
            context["wagtail_admin_base_url"],
            "https://example.test/admin/",
        )

    @override_settings(
        SITE_NAME="Fallback Notes",
        SITE_DESCRIPTION="Fallback description",
        SITE_AUTHOR="Fallback Author",
    )
    @patch(
        "blog.context_processors.Site.find_for_request",
        side_effect=TransactionManagementError("transaction is broken"),
    )
    def test_500_template_uses_defaults_when_site_database_lookup_fails(
        self,
        _site_mock,
    ):
        response = custom_500(RequestFactory().get("/"))
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 500)
        self.assertIn("500 - Server Error | Fallback Notes", content)
        self.assertIn('content="Fallback Author"', content)

    @patch("blog.context_processors.settings")
    def test_feed_uses_deployment_identity(self, settings_mock):
        settings_mock.SITE_NAME = "Example Notes"
        settings_mock.SITE_DESCRIPTION = "Example description"
        settings_mock.SITE_AUTHOR = "Example Author"

        feed = BlogFeed()

        self.assertEqual(feed.title(None), "Example Notes")
        self.assertEqual(feed.description(None), "Example description")


class TestRandomChoiceDeterminism(TestCase):
    def test_inline_choice_is_stable(self):
        pre = RandomChoicePreprocessor(Mock())
        line = "x [random:red|green|blue] y"
        self.assertEqual(pre.run([line]), pre.run([line]))

    def test_block_choice_is_stable(self):
        pre = RandomChoicePreprocessor(Mock())
        lines = ["[random]", "- alpha", "- beta", "- gamma", "[/random]"]
        self.assertEqual(pre.run(lines), pre.run(lines))


class TestRawHtmlSanitization(TestCase):
    def test_template_filter_strips_script_and_event_handlers(self):
        html = '<script>alert(1)</script><p onclick="alert(1)">Safe</p>'
        output = str(sanitize_html(html))
        self.assertNotIn("<script", output.lower())
        self.assertNotIn("onclick", output.lower())
        self.assertIn(">Safe<", output)

    @patch("blog.html_sanitizer.settings.ALLOWED_EMBED_HOSTS", ["embed.example"])
    def test_iframe_source_rejects_backslashes_and_userinfo(self):
        poisoned_sources = [
            r"https://embed.example\@evil.example/applet",
            r"https://embed.example\evil/applet",
            "https://attacker@embed.example/applet",
        ]
        for source in poisoned_sources:
            with self.subTest(source=source):
                output = str(sanitize_html(f'<iframe src="{source}" title="unsafe"></iframe>'))
                self.assertNotIn("<iframe", output)

    @patch("blog.html_sanitizer.settings.ALLOWED_EMBED_HOSTS", ["embed.example"])
    def test_iframe_source_is_canonicalized_before_rendering(self):
        output = str(
            sanitize_html('<iframe src="HTTPS://EMBED.EXAMPLE:443/applet?a=1&amp;b=2"></iframe>')
        )
        self.assertIn(
            'src="https://embed.example/applet?a=1&amp;b=2"',
            output,
        )
        self.assertIn('sandbox="allow-forms allow-popups allow-scripts"', output)

    def test_markdown_export_strips_raw_html_tags(self):
        block = SimpleNamespace(block_type="raw_html", value="<p>Hello <strong>world</strong></p>")
        self.assertEqual(_render_block(block), "Hello world")

    def test_markdown_export_includes_applet_embed_metadata(self):
        block = SimpleNamespace(
            block_type="applet_embed",
            value={
                "title": "Winchart",
                "src": "/static/applets/loser-winner.html",
                "lazy_load": True,
                "use_full_height": False,
                "max_height": 560,
                "style_overrides": "--applet-frame-height: 560px;",
            },
        )
        output = _render_block(block)
        self.assertIn("Applet", output)
        self.assertIn("title=Winchart", output)
        self.assertIn("src=/static/applets/loser-winner.html", output)
        self.assertIn("lazy_load=true", output)
        self.assertIn("full_height=false", output)
        self.assertIn("max_height=560", output)


class TestMarkdownRestrictionEnforcement(TestCase):
    def test_login_restriction_returns_redirect(self):
        request = RequestFactory().get("/secret.md")
        page = Mock()
        restriction = Mock()
        restriction.accept_request.return_value = False
        restriction.restriction_type = PageViewRestriction.LOGIN
        page.get_view_restrictions.return_value = [restriction]
        response = _enforce_view_restrictions(request, page)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 302)

    def test_password_restriction_returns_password_response(self):
        request = RequestFactory().get("/secret.md")
        page = Mock()
        page.id = 123
        restriction = Mock()
        restriction.id = 55
        restriction.accept_request.return_value = False
        restriction.restriction_type = PageViewRestriction.PASSWORD
        page.get_view_restrictions.return_value = [restriction]
        page.serve_password_required_response.return_value = HttpResponse("password")
        with patch("blog.views.PasswordViewRestrictionForm"):
            response = _enforce_view_restrictions(request, page)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)


class TestFrontendSecurityHeadersMiddleware(TestCase):
    def test_frontend_headers_set_on_non_admin_routes(self):
        middleware = FrontendSecurityHeadersMiddleware(lambda request: HttpResponse("ok"))
        request = RequestFactory().get("/blog/post/")
        response = middleware(request)
        self.assertIn("Content-Security-Policy-Report-Only", response)
        self.assertIn("Permissions-Policy", response)
        self.assertNotIn(
            "upgrade-insecure-requests",
            response["Content-Security-Policy-Report-Only"],
        )

    def test_frontend_headers_skip_admin_routes(self):
        middleware = FrontendSecurityHeadersMiddleware(lambda request: HttpResponse("ok"))
        request = RequestFactory().get("/admin/")
        response = middleware(request)
        self.assertNotIn("Content-Security-Policy-Report-Only", response)
        self.assertNotIn("Content-Security-Policy", response)

    def test_csp_enforce_switch_uses_enforcing_header(self):
        with patch.dict(os.environ, {"CSP_ENFORCE": "true"}):
            middleware = FrontendSecurityHeadersMiddleware(lambda request: HttpResponse("ok"))
            request = RequestFactory().get("/blog/post/")
            response = middleware(request)
        self.assertIn("Content-Security-Policy", response)
        self.assertIn("upgrade-insecure-requests", response["Content-Security-Policy"])


class TestBlogPageModelFields(TestCase):
    def test_blogpage_has_featured_image_field(self):
        field_names = {field.name for field in BlogPage._meta.get_fields()}
        self.assertIn("featured_image", field_names)
        self.assertIn("social_image", field_names)
        self.assertIn("ghost_id", field_names)
        self.assertIn("ghost_uuid", field_names)
        self.assertIn("authors", field_names)
        self.assertIn("tags", field_names)


class TestBlogPageRenderCaching(DjangoTestCase):
    def test_cached_render_context_skips_recompute(self):
        page = BlogPage(title="Cache Hit", slug="cache-hit", body=[])
        cache_key = page._compute_body_render_cache_key()
        page.body_render_cache_key = cache_key
        page.body_rendered_html = "<p>cached</p>"
        page.body_rendered_toc_items = [{"id": "h-intro", "text": "Intro", "level": "h1"}]
        page.body_rendered_toc_crumb = "Intro"
        page.body_rendered_readtime_main = "2 min"
        page.body_rendered_readtime_deep = "3 min"

        with patch("blog.models.render_blog_body") as render_mock:
            rendered = page.get_render_context()

        render_mock.assert_not_called()
        self.assertEqual(rendered["body_html"], "<p>cached</p>")
        self.assertEqual(rendered["readtime_main"], "2 min")
        self.assertEqual(rendered["readtime_deep"], "3 min")

    def test_cache_miss_recomputes_render_context(self):
        page = BlogPage(title="Cache Miss", slug="cache-miss", body=[])
        payload = {
            "body_html": "<p>fresh</p>",
            "toc_items": [],
            "toc_crumb": "",
            "readtime_main": "1 min",
            "readtime_deep": "1 min",
        }
        with patch("blog.models.render_blog_body", return_value=payload) as render_mock:
            rendered = page.get_render_context()

        render_mock.assert_called_once()
        self.assertEqual(rendered, payload)

    def test_publish_signal_precomputes_cache(self):
        page = BlogPage(title="Publish", slug="publish", body=[])
        page.pk = 42
        page.live = True
        payload = {
            "body_html": "<p>published</p>",
            "toc_items": [{"id": "h-a", "text": "A", "level": "h1"}],
            "toc_crumb": "A",
            "readtime_main": "4 min",
            "readtime_deep": "6 min",
        }

        with (
            patch("blog.models.render_blog_body", return_value=payload) as render_mock,
            patch("blog.models.BlogPage.objects.filter") as filter_mock,
        ):
            precompute_blog_body_render_cache(sender=BlogPage, instance=page)

        render_mock.assert_called_once()
        filter_mock.assert_called_once_with(pk=42)
        filter_mock.return_value.update.assert_called_once()


class TestAppletEmbedBlock(TestCase):
    def test_applet_embed_requires_static_applets_prefix(self):
        block = AppletEmbedBlock()
        with self.assertRaises(ValidationError):
            block.clean(
                {
                    "title": "Bad",
                    "src": "https://example.com/applet.html",
                    "lazy_load": True,
                    "use_full_height": False,
                    "max_height": 600,
                    "style_overrides": "",
                }
            )

    def test_applet_embed_accepts_static_applets_path(self):
        block = AppletEmbedBlock()
        cleaned = block.clean(
            {
                "title": "Good",
                "src": "/static/applets/loser-winner.html",
                "lazy_load": False,
                "use_full_height": False,
                "max_height": 420,
                "style_overrides": "height: 420px;",
            }
        )
        self.assertEqual(cleaned["src"], "/static/applets/loser-winner.html")
        self.assertEqual(cleaned["max_height"], 420)

    def test_applet_embed_max_height_is_optional(self):
        block = AppletEmbedBlock()
        self.assertIsNone(block.child_blocks["max_height"].meta.default)

    def test_applet_embed_missing_max_height_stays_unset(self):
        block = AppletEmbedBlock()
        cleaned = block.clean(
            {
                "title": "Default Height",
                "src": "/static/applets/loser-winner.html",
                "lazy_load": True,
                "use_full_height": False,
                "max_height": None,
                "style_overrides": "",
            }
        )
        self.assertIsNone(cleaned["max_height"])

    def test_applet_embed_full_height_allows_uncapped_resize(self):
        block = AppletEmbedBlock()
        cleaned = block.clean(
            {
                "title": "Full Height",
                "src": "/static/applets/loser-winner.html",
                "lazy_load": True,
                "use_full_height": True,
                "max_height": None,
                "style_overrides": "",
            }
        )
        self.assertIsNone(cleaned.get("max_height"))
        self.assertTrue(cleaned.get("use_full_height"))
