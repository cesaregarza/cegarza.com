from django.test import TestCase, override_settings
from wagtail.models import PageViewRestriction, Site

from blog.models import BlogIndexPage, BlogPage, BlogTag


@override_settings(
    ALLOWED_HOSTS=["essays.test"],
    SECURE_SSL_REDIRECT=False,
    BLOG_TAGS_ENABLED=False,
)
class EssaysArchiveTest(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.tree_root = self.site.root_page
        self.index = BlogIndexPage(
            title="Writing",
            slug="blog",
            default_author_name="Cesar Garza",
        )
        self.tree_root.add_child(instance=self.index)
        self.index.save_revision().publish()
        self.site.root_page = self.index
        self.site.hostname = "essays.test"
        self.site.port = 443
        self.site.save()

        self.tag = BlogTag.objects.get(slug="essays")
        self.essay = self.add_post("published-essay")
        self.note = self.add_post("technical-note", tagged=False)

    def add_post(self, slug, *, tagged=True, publish=True, index=None):
        post = BlogPage(
            title=slug.replace("-", " ").capitalize(),
            slug=slug,
            body=[],
            live=False,
        )
        (index or self.index).add_child(instance=post)
        if tagged:
            post.tags.add(self.tag)
            post.save()
        if publish:
            post.save_revision().publish()
        return post

    def get(self, path):
        return self.client.get(path, secure=True, HTTP_HOST="essays.test")

    def test_archive_only_lists_this_sites_tagged_live_public_posts(self):
        self.add_post("draft-essay", publish=False)
        restricted = self.add_post("private-essay")
        PageViewRestriction.objects.create(
            page=restricted,
            restriction_type=PageViewRestriction.LOGIN,
        )
        other_index = BlogIndexPage(title="Other blog", slug="other-blog")
        self.tree_root.add_child(instance=other_index)
        other_index.save_revision().publish()
        Site.objects.create(hostname="other.test", root_page=other_index)
        self.add_post("other-sites-essay", index=other_index)

        response = self.get("/essays/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([post.pk for post in response.context["posts"]], [self.essay.pk])
        self.assertContains(response, "Published essay")
        for title in ("Technical note", "Draft essay", "Private essay", "Other sites essay"):
            self.assertNotContains(response, title)

    def test_navigation_and_metadata_identify_the_essays_section(self):
        for path in ("/", "/writing/", "/published-essay/"):
            self.assertContains(self.get(path), 'href="/essays/"')

        response = self.get("/essays/")

        self.assertContains(
            response,
            '<a class="site-nav__link" href="/essays/" aria-current="page">essays</a>',
            html=True,
        )
        self.assertContains(response, "<title>Essays — Cesar Garza</title>", html=True)
        self.assertContains(
            response,
            '<link rel="canonical" href="https://essays.test/essays/">',
            html=True,
        )
        self.assertContains(
            response,
            '<meta property="og:url" content="https://essays.test/essays/">',
            html=True,
        )
        self.assertContains(response, "Personal essays, reflections, and longer-form writing.")

    def test_empty_archive_is_ready_for_future_essays(self):
        self.essay.tags.clear()
        self.essay.save_revision().publish()

        response = self.get("/essays/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["paginator"].count, 0)
        self.assertContains(response, "The first essay will appear here.")
        self.assertNotContains(response, "Published essay")
        self.assertNotContains(response, "Technical note")
        self.assertContains(self.get("/writing/"), "Published essay")

    def test_pagination_stays_in_the_essays_archive(self):
        additional_posts = [self.add_post(f"essay-{number}") for number in range(9)]

        first = self.get("/essays/")
        second = self.get("/essays/?page=2")

        self.assertEqual(len(first.context["posts"]), 9)
        self.assertEqual(len(second.context["posts"]), 1)
        self.assertEqual(first.context["paginator"].count, 10)
        self.assertEqual(
            {post.pk for response in (first, second) for post in response.context["posts"]},
            {self.essay.pk, *(post.pk for post in additional_posts)},
        )
        self.assertContains(
            first,
            '<link rel="next" href="https://essays.test/essays/?page=2">',
            html=True,
        )
        self.assertContains(
            second,
            '<link rel="canonical" href="https://essays.test/essays/?page=2">',
            html=True,
        )
        self.assertContains(
            second,
            '<link rel="prev" href="https://essays.test/essays/">',
            html=True,
        )

    def test_nested_blog_index_uses_its_own_essays_path(self):
        self.site.root_page = self.tree_root
        self.site.save()

        response = self.get("/blog/essays/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Published essay")
        self.assertContains(
            response,
            '<a class="site-nav__link" href="/blog/essays/" aria-current="page">essays</a>',
            html=True,
        )
        self.assertContains(
            response,
            '<link rel="canonical" href="https://essays.test/blog/essays/">',
            html=True,
        )

    def test_essays_keep_their_post_urls_and_appear_in_all_writing_and_feeds(self):
        self.assertContains(
            self.get("/published-essay/"),
            '<a href="/essays/">&larr; Back to essays</a>',
            html=True,
        )
        self.assertContains(
            self.get("/technical-note/"),
            '<a href="/writing/">&larr; Back to posts</a>',
            html=True,
        )
        for path in ("/writing/", "/feed/", "/feed/atom/"):
            response = self.get(path)
            self.assertContains(response, "Published essay")
            self.assertContains(response, "Technical note")
