from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from wagtail.models import PageViewRestriction, Site
from wagtail.snippets.models import get_snippet_models

from blog.models import (
    BlogIndexPage,
    BlogPage,
    BlogSeries,
    BlogSeriesMembership,
)


@override_settings(
    ALLOWED_HOSTS=["series.test"],
    SECURE_SSL_REDIRECT=False,
)
class OrderedSeriesTest(TestCase):
    def setUp(self):
        default_site = Site.objects.get(is_default_site=True)
        self.index = BlogIndexPage(
            title="Field notes",
            slug="field-notes",
            intro="Ordered technical notes.",
            default_author_name="Series Author",
        )
        default_site.root_page.add_child(instance=self.index)
        self.index.save_revision().publish()

        self.part_one = self.add_post("Part one", "part-one", 1, publish=True)
        self.part_two = self.add_post("Part two", "part-two", 2, publish=True)
        self.draft = self.add_post("Draft part", "draft-part", 3, publish=False)
        self.restricted = self.add_post(
            "Restricted part",
            "restricted-part",
            4,
            publish=True,
        )
        PageViewRestriction.objects.create(
            page=self.restricted,
            restriction_type=PageViewRestriction.LOGIN,
        )

        self.primary_series = BlogSeries.objects.create(
            title="Primary sequence",
            slug="primary-sequence",
            description="The main ordered path.",
            status=BlogSeries.Status.ONGOING,
            next_up="Part three is in progress.",
        )
        BlogSeriesMembership.objects.create(
            series=self.primary_series,
            page=self.part_two,
            sort_order=20,
            is_primary=True,
        )
        BlogSeriesMembership.objects.create(
            series=self.primary_series,
            page=self.part_one,
            sort_order=10,
            is_primary=True,
        )
        BlogSeriesMembership.objects.create(
            series=self.primary_series,
            page=self.draft,
            sort_order=30,
        )
        BlogSeriesMembership.objects.create(
            series=self.primary_series,
            page=self.restricted,
            sort_order=40,
        )

        self.secondary_series = BlogSeries.objects.create(
            title="Secondary sequence",
            slug="secondary-sequence",
            description="A second valid reading path.",
            status=BlogSeries.Status.COMPLETE,
        )
        BlogSeriesMembership.objects.create(
            series=self.secondary_series,
            page=self.part_one,
            sort_order=10,
        )

        self.private_series = BlogSeries.objects.create(
            title="Private sequence",
            slug="private-sequence",
        )
        BlogSeriesMembership.objects.create(
            series=self.private_series,
            page=self.draft,
            sort_order=10,
        )

        self.site = Site.objects.create(
            hostname="series.test",
            port=443,
            site_name="Series test",
            root_page=self.index,
        )

    def add_post(self, title, slug, day, *, publish):
        post = BlogPage(
            title=title,
            slug=slug,
            date=date(2026, 7, day),
            abstract=f"Summary for {title}.",
            body=[("heading", f"Inside {title}")],
            live=publish,
        )
        self.index.add_child(instance=post)
        revision = post.save_revision()
        if publish:
            revision.publish()
        return post

    def get(self, path):
        return self.client.get(path, secure=True, HTTP_HOST="series.test")

    def test_memberships_are_ordered_and_enforce_one_primary_series(self):
        self.assertEqual(
            list(
                self.primary_series.memberships.values_list(
                    "page__title",
                    flat=True,
                )
            ),
            ["Part one", "Part two", "Draft part", "Restricted part"],
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BlogSeriesMembership.objects.create(
                    series=self.secondary_series,
                    page=self.part_two,
                    sort_order=20,
                    is_primary=True,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BlogSeriesMembership.objects.create(
                    series=self.primary_series,
                    page=self.part_one,
                    sort_order=50,
                )

        conflicting_primary = BlogSeriesMembership(
            series=self.secondary_series,
            page=self.part_two,
            sort_order=20,
            is_primary=True,
        )
        with self.assertRaisesMessage(
            ValidationError,
            "This post already has a primary series.",
        ):
            conflicting_primary.clean()

        original_url = reverse(
            "blog-series-detail",
            kwargs={"slug": self.primary_series.slug},
        )
        self.primary_series.title = "Renamed editorial title"
        self.primary_series.save(update_fields=["title", "updated_at"])
        self.assertEqual(
            reverse(
                "blog-series-detail",
                kwargs={"slug": self.primary_series.slug},
            ),
            original_url,
        )

    def test_series_is_editable_as_a_wagtail_snippet_with_ordered_parts(self):
        self.assertIn(BlogSeries, get_snippet_models())
        user = get_user_model().objects.create_superuser(
            username="series-admin",
            email="series@example.test",
            password="unused-password",
        )
        self.client.force_login(user)

        response = self.client.get(
            reverse("wagtailsnippets_blog_blogseries:add"),
            secure=True,
            HTTP_HOST="series.test",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parts")
        self.assertContains(response, "Stable public URL segment")
        self.assertContains(response, "Is primary")

    def test_hub_detail_and_index_use_only_live_public_parts(self):
        index_response = self.get("/")
        hub_response = self.get("/series/")
        detail_response = self.get("/series/primary-sequence/")

        for response in (index_response, hub_response, detail_response):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Primary sequence")
            self.assertContains(response, "Part one")
            self.assertContains(response, "Part two")
            self.assertNotContains(response, "Draft part")
            self.assertNotContains(response, "Restricted part")
            self.assertNotContains(response, "Private sequence")

        self.assertContains(index_response, "<dd>2</dd>", html=True)
        self.assertContains(hub_response, "2 series · 3 parts")
        self.assertContains(detail_response, "2 published")
        self.assertContains(
            detail_response,
            '<meta property="og:url" content="https://series.test/series/primary-sequence/">',
            html=True,
        )
        self.assertContains(
            detail_response,
            '<link rel="canonical" href="https://series.test/series/primary-sequence/">',
            html=True,
        )
        self.assertEqual(self.get("/series/private-sequence/").status_code, 404)
        self.assertEqual(self.get("/series/not-a-series/").status_code, 404)

        rendered = detail_response.content.decode("utf-8")
        self.assertLess(rendered.index("Part one"), rendered.index("Part two"))

    def test_article_uses_primary_series_and_public_in_series_navigation(self):
        first_response = self.get("/part-one/")
        second_response = self.get("/part-two/")

        self.assertContains(first_response, "part 01 of 02")
        self.assertContains(first_response, "Primary sequence")
        self.assertContains(first_response, "also in")
        self.assertContains(first_response, "Secondary sequence")
        self.assertContains(first_response, "part 02 →")
        self.assertContains(first_response, "continue →")
        self.assertNotContains(first_response, "Draft part")
        self.assertNotContains(first_response, "Restricted part")

        self.assertContains(second_response, "end of")
        self.assertContains(second_response, "Part three is in progress.")
        self.assertContains(second_response, "series index →")

    def test_series_feeds_and_sitemap_never_expose_private_parts(self):
        rss = self.get("/series/primary-sequence/feed/")
        atom = self.get("/series/primary-sequence/feed/atom/")
        sitemap = self.get("/sitemap.xml")

        for response in (rss, atom):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Part one")
            self.assertContains(response, "Part two")
            self.assertNotContains(response, "Draft part")
            self.assertNotContains(response, "Restricted part")
            rendered = response.content.decode("utf-8")
            self.assertLess(rendered.index("Part one"), rendered.index("Part two"))

        self.assertContains(sitemap, "https://series.test/series/")
        self.assertContains(
            sitemap,
            "https://series.test/series/primary-sequence/",
        )
        self.assertNotContains(sitemap, "private-sequence")
        self.assertNotContains(sitemap, "draft-part")
        self.assertNotContains(sitemap, "restricted-part")

    def test_nested_wagtail_root_keeps_series_routes_canonical(self):
        self.site.root_page = self.index.get_parent()
        self.site.save(update_fields=["root_page"])

        rss = self.get("/series/primary-sequence/feed/")

        self.assertContains(
            rss,
            "<link>https://series.test/series/primary-sequence/</link>",
        )
        self.assertContains(
            rss,
            "https://series.test/field-notes/part-one/",
        )

    def test_series_never_crosses_the_request_site_tree(self):
        other_index = BlogIndexPage(title="Other notes", slug="other-notes")
        self.index.get_parent().add_child(instance=other_index)
        other_index.save_revision().publish()
        other_post = BlogPage(
            title="Other site part",
            slug="other-site-part",
            live=True,
            body=[],
        )
        other_index.add_child(instance=other_post)
        other_post.save_revision().publish()
        BlogSeriesMembership.objects.create(
            series=self.primary_series,
            page=other_post,
            sort_order=5,
        )

        detail = self.get("/series/primary-sequence/")
        feed = self.get("/series/primary-sequence/feed/")

        self.assertNotContains(detail, "Other site part")
        self.assertNotContains(feed, "Other site part")

    def test_navigation_hides_series_when_no_public_memberships_remain(self):
        BlogSeriesMembership.objects.filter(
            page__in=[self.part_one, self.part_two]
        ).delete()

        response = self.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="/series/"')
        self.assertContains(response, "<dd>0</dd>", html=True)


class OrderedSeriesMigrationTest(TransactionTestCase):
    migrate_from = [("blog", "0020_blogauthor_blogtag_contentpage_and_more")]
    migrate_to = [("blog", "0021_blogseries_blogseriesmembership")]

    def test_schema_migration_preserves_existing_blog_posts(self):
        default_site = Site.objects.get(is_default_site=True)
        index = BlogIndexPage(title="Migration notes", slug="migration-notes")
        default_site.root_page.add_child(instance=index)
        index.save_revision().publish()
        post = BlogPage(
            title="Existing Ghost post",
            slug="existing-ghost-post",
            ghost_id="ghost-existing",
            body=[],
        )
        index.add_child(instance=post)
        post.save_revision().publish()
        post_pk = post.pk

        try:
            executor = MigrationExecutor(connection)
            executor.migrate(self.migrate_from)
            old_apps = executor.loader.project_state(self.migrate_from).apps
            OldBlogPage = old_apps.get_model("blog", "BlogPage")
            self.assertEqual(
                OldBlogPage.objects.get(pk=post_pk).ghost_id,
                "ghost-existing",
            )

            executor = MigrationExecutor(connection)
            executor.migrate(self.migrate_to)
            new_apps = executor.loader.project_state(self.migrate_to).apps
            NewBlogPage = new_apps.get_model("blog", "BlogPage")
            NewBlogSeries = new_apps.get_model("blog", "BlogSeries")
            self.assertEqual(
                NewBlogPage.objects.get(pk=post_pk).ghost_id,
                "ghost-existing",
            )
            self.assertEqual(NewBlogSeries.objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate(self.migrate_to)
