from datetime import date

from django.test import TestCase, override_settings
from wagtail.models import Site

from blog.models import BlogIndexPage, BlogPage, SignpostLink


@override_settings(ALLOWED_HOSTS=["signpost.test"], SECURE_SSL_REDIRECT=False)
class SignpostLandingTest(TestCase):
    """The root index serves a signpost at ``/`` and the listing at ``/writing/``."""

    def setUp(self):
        default_site = Site.objects.get(is_default_site=True)
        tree_root = default_site.root_page
        self.index = BlogIndexPage(
            title="Bringing Down The Gauss",
            slug="blog",
            intro="Open notebook description",
            default_author_name="Cesar Garza",
            signpost_kicker="software engineer · ml systems",
            signpost_heading="Cesar Garza",
            signpost_intro="I build ML systems and write about them.",
        )
        tree_root.add_child(instance=self.index)
        self.index.save_revision().publish()

        SignpostLink.objects.create(
            page=self.index,
            label="Résumé",
            url="/resume/",
            description="one page →",
        )

        self.post = BlogPage(
            title="Visible essay",
            slug="visible-essay",
            date=date(2026, 7, 30),
            body=[],
        )
        self.index.add_child(instance=self.post)
        self.post.save_revision().publish()

        self.draft = BlogPage(
            title="Draft essay",
            slug="draft-essay",
            date=date(2026, 7, 31),
            body=[],
            live=False,
        )
        self.index.add_child(instance=self.draft)  # unpublished draft

        default_site.root_page = self.index
        default_site.hostname = "signpost.test"
        default_site.port = 443
        default_site.site_name = "cegarza.com"
        default_site.save()

    def get(self, path):
        return self.client.get(path, secure=True, HTTP_HOST="signpost.test")

    def test_root_renders_signpost_not_listing(self):
        response = self.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="directory-hero"')
        self.assertContains(response, 'class="directory-grid"')
        self.assertContains(response, "Cesar Garza")
        self.assertContains(response, "Résumé")
        self.assertContains(response, "recent writing")
        self.assertContains(response, "Visible essay")
        # The editorial listing chrome must not appear on the signpost.
        self.assertNotContains(response, 'class="index-stats"')

    def test_signpost_does_not_leak_drafts(self):
        self.assertNotContains(self.get("/"), "Draft essay")

    def test_writing_route_renders_listing(self):
        response = self.get("/writing/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="index-hero"')
        self.assertContains(response, 'class="index-stats"')
        self.assertContains(response, "Visible essay")
        self.assertNotContains(response, "Draft essay")

    def test_post_urls_stay_flat(self):
        response = self.get("/visible-essay/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible essay")

    def test_post_back_link_points_to_writing(self):
        response = self.get("/visible-essay/")
        self.assertContains(
            response,
            '<a href="/writing/">&larr; Back to posts</a>',
            html=True,
        )

    def test_primary_nav_links_to_writing(self):
        self.assertContains(self.get("/"), 'href="/writing/"')
