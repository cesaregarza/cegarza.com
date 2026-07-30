from datetime import date

from django.test import TestCase, override_settings
from wagtail.contrib.redirects.models import Redirect
from wagtail.models import PageViewRestriction, Site

from blog.models import BlogIndexPage, BlogPage


@override_settings(
    ALLOWED_HOSTS=[
        "preview.cegarza.test",
        "cegarza.test",
        "nested.cegarza.test",
    ],
    SECURE_SSL_REDIRECT=False,
)
class RuntimeMultisiteTest(TestCase):
    def setUp(self):
        default_site = Site.objects.get(is_default_site=True)
        self.tree_root = default_site.root_page
        self.index = BlogIndexPage(
            title="Shared blog",
            slug="blog",
            intro="Shared-root description",
            default_author_name="Shared-root author",
        )
        self.tree_root.add_child(instance=self.index)
        self.index.save_revision().publish()

        self.post = BlogPage(
            title="Visible post",
            slug="visible-post",
            date=date(2026, 7, 30),
            body=[],
        )
        self.index.add_child(instance=self.post)
        self.post.save_revision().publish()

        self.preview_site = Site.objects.create(
            hostname="preview.cegarza.test",
            port=443,
            site_name="Preview identity",
            root_page=self.index,
        )
        self.apex_site = Site.objects.create(
            hostname="cegarza.test",
            port=443,
            site_name="Apex identity",
            root_page=self.index,
        )
        self.nested_site = Site.objects.create(
            hostname="nested.cegarza.test",
            port=443,
            site_name="Nested identity",
            root_page=self.tree_root,
        )

    def get_for_host(self, path, host):
        return self.client.get(path, secure=True, HTTP_HOST=host)

    def test_branding_and_feeds_use_request_site_identity(self):
        preview_page = self.get_for_host("/visible-post/", "preview.cegarza.test")
        apex_page = self.get_for_host("/visible-post/", "cegarza.test")
        self.assertContains(preview_page, "Preview identity")
        self.assertNotContains(preview_page, "Apex identity")
        self.assertContains(apex_page, "Apex identity")
        self.assertNotContains(apex_page, "Preview identity")

        preview_feed = self.get_for_host("/feed/", "preview.cegarza.test")
        apex_feed = self.get_for_host("/feed/", "cegarza.test")
        self.assertContains(preview_feed, "Preview identity")
        self.assertNotContains(preview_feed, "Apex identity")
        self.assertContains(apex_feed, "Apex identity")
        self.assertNotContains(apex_feed, "Preview identity")
        self.assertContains(preview_feed, "Shared-root description")
        self.assertContains(apex_feed, "Shared-root description")
        self.assertContains(preview_page, "Shared-root author")
        self.assertContains(apex_page, "Shared-root author")
        self.assertContains(
            preview_feed,
            "<link>https://preview.cegarza.test/</link>",
        )
        self.assertContains(
            apex_feed,
            "<link>https://cegarza.test/</link>",
        )

        nested_feed = self.get_for_host("/feed/", "nested.cegarza.test")
        self.assertContains(
            nested_feed,
            "<link>https://nested.cegarza.test/blog/</link>",
        )

    def test_shared_root_redirects_keep_the_requested_host(self):
        Redirect.objects.create(
            old_path="/legacy-post",
            site=None,
            is_permanent=True,
            redirect_page=self.post,
        )

        preview_response = self.get_for_host(
            "/legacy-post/?ignored=1",
            "preview.cegarza.test",
        )
        apex_response = self.get_for_host(
            "/legacy-post/?ignored=1",
            "cegarza.test",
        )

        self.assertEqual(preview_response.status_code, 301)
        self.assertEqual(
            preview_response["Location"],
            "https://preview.cegarza.test/visible-post/",
        )
        self.assertEqual(apex_response.status_code, 301)
        self.assertEqual(
            apex_response["Location"],
            "https://cegarza.test/visible-post/",
        )

    def test_back_link_uses_parent_index_path_for_nested_site(self):
        response = self.get_for_host(
            "/blog/visible-post/",
            "nested.cegarza.test",
        )

        self.assertContains(
            response,
            '<a href="/blog/">&larr; Back to posts</a>',
            html=True,
        )

    def test_pagination_rel_links_use_request_site_host(self):
        for number in range(18):
            post = BlogPage(
                title=f"Pagination post {number}",
                slug=f"pagination-post-{number}",
                date=date(2026, 7, number + 1),
                body=[],
            )
            self.index.add_child(instance=post)
            post.save_revision().publish()

        preview_first = self.get_for_host("/", "preview.cegarza.test")
        preview_second = self.get_for_host("/?page=2", "preview.cegarza.test")
        preview_third = self.get_for_host("/?page=3", "preview.cegarza.test")
        apex_first = self.get_for_host("/", "cegarza.test")
        apex_second = self.get_for_host("/?page=2", "cegarza.test")
        apex_third = self.get_for_host("/?page=3", "cegarza.test")

        self.assertContains(
            preview_first,
            '<link rel="next" href="https://preview.cegarza.test/?page=2">',
            html=True,
        )
        self.assertContains(
            preview_second,
            '<link rel="prev" href="https://preview.cegarza.test/">',
            html=True,
        )
        self.assertContains(
            preview_second,
            '<link rel="next" href="https://preview.cegarza.test/?page=3">',
            html=True,
        )
        self.assertContains(
            preview_third,
            '<link rel="prev" href="https://preview.cegarza.test/?page=2">',
            html=True,
        )
        self.assertContains(
            apex_first,
            '<link rel="next" href="https://cegarza.test/?page=2">',
            html=True,
        )
        self.assertContains(
            apex_second,
            '<link rel="prev" href="https://cegarza.test/">',
            html=True,
        )
        self.assertContains(
            apex_second,
            '<link rel="next" href="https://cegarza.test/?page=3">',
            html=True,
        )
        self.assertContains(
            apex_third,
            '<link rel="prev" href="https://cegarza.test/?page=2">',
            html=True,
        )
        self.assertNotContains(preview_first, "https://cegarza.test/?page=2")
        self.assertNotContains(apex_first, "https://preview.cegarza.test/?page=2")

    def test_restricted_posts_are_absent_from_public_surfaces(self):
        restricted = BlogPage(
            title="Restricted post",
            slug="restricted-post",
            date=date(2026, 7, 29),
            body=[],
        )
        self.index.add_child(instance=restricted)
        restricted.save_revision().publish()
        PageViewRestriction.objects.create(
            page=restricted,
            restriction_type=PageViewRestriction.LOGIN,
        )

        index_response = self.get_for_host("/", "preview.cegarza.test")
        feed_response = self.get_for_host("/feed/", "preview.cegarza.test")
        sitemap_response = self.get_for_host(
            "/sitemap.xml",
            "preview.cegarza.test",
        )
        markdown_response = self.get_for_host(
            "/restricted-post.md",
            "preview.cegarza.test",
        )

        self.assertNotContains(index_response, "Restricted post")
        self.assertNotContains(feed_response, "Restricted post")
        self.assertNotContains(sitemap_response, "/restricted-post/")
        self.assertEqual(markdown_response.status_code, 404)
        self.assertContains(index_response, "Visible post")
        self.assertContains(feed_response, "Visible post")
        self.assertContains(sitemap_response, "/visible-post/")
