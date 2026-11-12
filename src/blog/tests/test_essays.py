from django.test import TestCase, override_settings
from wagtail.models import PageViewRestriction, Site

from blog.models import BlogIndexPage, BlogPage, BlogSeries, BlogSeriesMembership, BlogTag


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

    def section(self, response, opening, closing):
        """The rendered markup from `opening` up to the next `closing`."""
        rendered = response.content.decode("utf-8")
        start = rendered.index(opening)
        return rendered[start : rendered.index(closing, start)]

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

    def test_essay_posts_read_as_one_column_without_the_technical_chrome(self):
        essay = self.get("/published-essay/")
        note = self.get("/technical-note/")

        self.assertContains(essay, '<body class="page--article page--essay">')
        self.assertContains(essay, '<p class="eyebrow">essay</p>', html=True)
        self.assertContains(essay, '<span class="post-meta__proper">Cesar Garza</span>', html=True)
        self.assertContains(essay, "</span> read</span>")
        self.assertContains(essay, 'class="post-actions post-actions--end"')
        self.assertContains(essay, "data-share-action")
        # The essays link is marked as the current section, not the current page.
        self.assertContains(
            essay,
            '<a class="site-nav__link" href="/essays/" aria-current="true">essays</a>',
            html=True,
        )
        for technical_chrome in (
            'id="postOutline"',
            'id="readingStatus"',
            'id="postTocDrawerToggle"',
            "data-cite-action",
            "Back to",
        ):
            self.assertNotContains(essay, technical_chrome)

        self.assertContains(note, '<body class="page--article">')
        self.assertContains(note, 'id="postOutline"')
        self.assertContains(note, 'id="readingStatus"')
        self.assertContains(note, "data-cite-action")
        self.assertNotContains(note, 'class="eyebrow"')
        self.assertNotContains(note, "post-actions--end")
        self.assertContains(
            note,
            '<a class="site-nav__link" href="/essays/">essays</a>',
            html=True,
        )

    def test_essay_neighbours_stay_within_the_essays(self):
        self.add_post("second-essay")

        first = self.get("/published-essay/")
        second = self.get("/second-essay/")
        note = self.get("/technical-note/")

        self.assertEqual(first.context["next_post"].slug, "second-essay")
        self.assertNotIn("previous_post", first.context)
        self.assertContains(first, "next essay →")
        self.assertNotContains(first, "Technical note")

        self.assertEqual(second.context["previous_post"].slug, "published-essay")
        self.assertNotIn("next_post", second.context)
        self.assertContains(second, "← previous essay")
        self.assertContains(second, "essays index →")
        self.assertContains(second, "All essays")
        self.assertNotContains(second, "Technical note")

        # A technical post still walks every post in publication order.
        self.assertEqual(note.context["previous_post"].slug, "published-essay")
        self.assertEqual(note.context["next_post"].slug, "second-essay")
        self.assertNotContains(note, "previous essay")
        self.assertNotContains(note, "next essay")

    def test_an_essay_in_a_series_still_moves_between_essays(self):
        series = BlogSeries.objects.create(
            title="Mixed series",
            slug="mixed-series",
            status=BlogSeries.Status.ONGOING,
        )
        series_essay = self.add_post("series-essay")
        self.add_post("later-essay")
        BlogSeriesMembership.objects.create(
            series=series,
            page=self.note,
            sort_order=10,
            is_primary=True,
        )
        BlogSeriesMembership.objects.create(
            series=series,
            page=series_essay,
            sort_order=20,
            is_primary=True,
        )

        essay = self.get("/series-essay/")
        note = self.get("/technical-note/")
        adjacent = self.section(essay, '<nav class="post-nav"', "</nav>")
        end_card = self.section(essay, '<section class="post-series-end"', "</section>")

        for series_navigation in ("Technical note", "← part", "series index", "/series/mixed-series/"):
            self.assertNotIn(series_navigation, adjacent)
        self.assertIn("← previous essay", adjacent)
        self.assertIn("Published essay", adjacent)
        self.assertIn("next essay →", adjacent)
        self.assertIn("Later essay", adjacent)
        self.assertEqual(essay.context["previous_post"].slug, "published-essay")
        self.assertEqual(essay.context["next_post"].slug, "later-essay")

        # The series keeps its own navigation in the band and the end card.
        self.assertContains(essay, "part 02 of 02")
        self.assertIn("Mixed series</span>, for now", end_card)
        self.assertIn('<a href="/series/mixed-series/">all parts →</a>', end_card)

        # The technical part of the same series is still navigated as a series part.
        self.assertNotIn("previous_post", note.context)
        self.assertNotIn("next_post", note.context)
        self.assertContains(note, "series index →")
        self.assertNotContains(note, "next essay")

    def test_essays_keep_their_post_urls_and_appear_in_all_writing_and_feeds(self):
        self.assertEqual(self.get("/published-essay/").status_code, 200)
        self.assertContains(
            self.get("/technical-note/"),
            '<a href="/writing/">&larr; Back to posts</a>',
            html=True,
        )
        for path in ("/writing/", "/feed/", "/feed/atom/"):
            response = self.get(path)
            self.assertContains(response, "Published essay")
            self.assertContains(response, "Technical note")
