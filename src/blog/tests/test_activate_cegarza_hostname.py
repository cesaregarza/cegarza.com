from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from wagtail.contrib.redirects.models import Redirect
from wagtail.models import Site

from blog.models import BlogIndexPage, BlogPage


class ActivateCegarzaHostnameTest(TestCase):
    def setUp(self):
        self.default_site = Site.objects.get(is_default_site=True)
        self.default_root_id = self.default_site.root_page_id

    def _create_index(self, slug="cegarza-blog"):
        index = BlogIndexPage(title="Cegarza Blog", slug=slug)
        self.default_site.root_page.add_child(instance=index)
        return index

    def _create_source(self, root, *, port=443):
        return Site.objects.create(
            hostname="preview.cegarza.com",
            port=port,
            site_name="Cegarza",
            root_page=root,
            is_default_site=False,
        )

    def _create_post(self, root, slug="canonical-post"):
        post = BlogPage(title="Canonical post", slug=slug)
        root.add_child(instance=post)
        return post

    def _run_command(self):
        stdout = StringIO()
        call_command("activate_cegarza_hostname", stdout=stdout)
        return stdout.getvalue()

    def assert_default_site_unchanged(self):
        self.default_site.refresh_from_db()
        self.assertTrue(self.default_site.is_default_site)
        self.assertEqual(self.default_site.root_page_id, self.default_root_id)

    def test_creates_apex_alias_and_keeps_preview_and_default_site(self):
        index = self._create_index()
        source = self._create_source(index)

        output = self._run_command()

        source.refresh_from_db()
        target = Site.objects.get(hostname="cegarza.com", port=443)
        self.assertEqual(source.root_page_id, index.pk)
        self.assertEqual(target.root_page_id, index.pk)
        self.assertEqual(target.site_name, source.site_name)
        self.assertFalse(target.is_default_site)
        self.assertIn("Created cegarza.com:443", output)
        self.assert_default_site_unchanged()

    def test_existing_correct_alias_is_idempotent_and_untouched(self):
        index = self._create_index()
        self._create_source(index)
        target = Site.objects.create(
            hostname="cegarza.com",
            port=443,
            site_name="Existing alias name",
            root_page=index,
            is_default_site=False,
        )

        output = self._run_command()

        target.refresh_from_db()
        self.assertEqual(
            Site.objects.filter(hostname="cegarza.com", port=443).count(),
            1,
        )
        self.assertEqual(target.site_name, "Existing alias name")
        self.assertIn("no changes made", output)
        self.assert_default_site_unchanged()

    def test_copies_source_redirects_to_apex_idempotently(self):
        index = self._create_index()
        source = self._create_source(index)
        post = self._create_post(index)
        Redirect.objects.create(
            site=source,
            old_path="/legacy-post",
            is_permanent=True,
            redirect_page=post,
        )

        self._run_command()
        self._run_command()

        target = Site.objects.get(hostname="cegarza.com", port=443)
        target_redirect = Redirect.objects.get(
            site=target,
            old_path="/legacy-post",
        )
        self.assertTrue(target_redirect.is_permanent)
        self.assertEqual(target_redirect.redirect_page_id, post.pk)
        self.assertEqual(
            Redirect.objects.filter(site=target, old_path="/legacy-post").count(),
            1,
        )

    def test_conflicting_apex_redirect_rolls_back_activation(self):
        index = self._create_index()
        source = self._create_source(index)
        canonical = self._create_post(index)
        other = self._create_post(index, slug="other-post")
        Redirect.objects.create(
            site=source,
            old_path="/legacy-post",
            is_permanent=True,
            redirect_page=canonical,
        )
        target = Site.objects.create(
            hostname="cegarza.com",
            port=443,
            site_name="Existing alias",
            root_page=index,
            is_default_site=False,
        )
        Redirect.objects.create(
            site=target,
            old_path="/legacy-post",
            is_permanent=True,
            redirect_page=other,
        )

        with self.assertRaisesMessage(CommandError, "has a conflicting redirect"):
            self._run_command()

        target_redirect = Redirect.objects.get(
            site=target,
            old_path="/legacy-post",
        )
        self.assertEqual(target_redirect.redirect_page_id, other.pk)

    def test_rejects_target_only_redirect_without_changes(self):
        index = self._create_index()
        self._create_source(index)
        target = Site.objects.create(
            hostname="cegarza.com",
            port=443,
            site_name="Existing alias",
            root_page=index,
            is_default_site=False,
        )
        existing = Redirect.objects.create(
            site=target,
            old_path="/unexpected",
            is_permanent=True,
            redirect_link="https://example.test/",
        )
        site_count = Site.objects.count()
        redirect_count = Redirect.objects.count()

        with self.assertRaisesMessage(
            CommandError,
            "has redirects that are not present",
        ):
            self._run_command()

        existing.refresh_from_db()
        self.assertEqual(existing.redirect_link, "https://example.test/")
        self.assertEqual(Site.objects.count(), site_count)
        self.assertEqual(Redirect.objects.count(), redirect_count)

    def test_rejects_non_permanent_preview_redirect_without_creating_apex(self):
        index = self._create_index()
        source = self._create_source(index)
        Redirect.objects.create(
            site=source,
            old_path="/temporary",
            is_permanent=False,
            redirect_link="https://example.test/",
        )

        with self.assertRaisesMessage(CommandError, "has a non-permanent redirect"):
            self._run_command()

        self.assertFalse(Site.objects.filter(hostname="cegarza.com").exists())
        self.assertEqual(Redirect.objects.filter(site=source).count(), 1)

    def test_rejects_missing_source_without_writes(self):
        with self.assertRaisesMessage(
            CommandError,
            "Expected exactly one preview.cegarza.com Wagtail Site; found 0.",
        ):
            self._run_command()

        self.assertFalse(Site.objects.filter(hostname="cegarza.com").exists())
        self.assert_default_site_unchanged()

    def test_rejects_multiple_source_sites_without_writes(self):
        index = self._create_index()
        self._create_source(index)
        self._create_source(index, port=8443)

        with self.assertRaisesMessage(
            CommandError,
            "Expected exactly one preview.cegarza.com Wagtail Site; found 2.",
        ):
            self._run_command()

        self.assertFalse(Site.objects.filter(hostname="cegarza.com").exists())
        self.assert_default_site_unchanged()

    def test_rejects_source_on_wrong_port_without_writes(self):
        index = self._create_index()
        self._create_source(index, port=8443)

        with self.assertRaisesMessage(CommandError, "must use port 443"):
            self._run_command()

        self.assertFalse(Site.objects.filter(hostname="cegarza.com").exists())
        self.assert_default_site_unchanged()

    def test_rejects_source_with_wrong_root_without_writes(self):
        self._create_source(self.default_site.root_page)

        with self.assertRaisesMessage(CommandError, "not rooted at a BlogIndexPage"):
            self._run_command()

        self.assertFalse(Site.objects.filter(hostname="cegarza.com").exists())
        self.assert_default_site_unchanged()

    def test_rejects_target_on_another_port_without_changes(self):
        index = self._create_index()
        self._create_source(index)
        target = Site.objects.create(
            hostname="cegarza.com",
            port=8443,
            site_name="Collision",
            root_page=index,
            is_default_site=False,
        )

        with self.assertRaisesMessage(CommandError, "already exists on port 8443"):
            self._run_command()

        target.refresh_from_db()
        self.assertEqual(target.port, 8443)
        self.assertFalse(Site.objects.filter(hostname="cegarza.com", port=443).exists())
        self.assert_default_site_unchanged()

    def test_rejects_target_with_wrong_root_without_changes(self):
        source_index = self._create_index()
        other_index = self._create_index(slug="other-blog")
        self._create_source(source_index)
        target = Site.objects.create(
            hostname="cegarza.com",
            port=443,
            site_name="Collision",
            root_page=other_index,
            is_default_site=False,
        )

        with self.assertRaisesMessage(CommandError, "different root page"):
            self._run_command()

        target.refresh_from_db()
        self.assertEqual(target.root_page_id, other_index.pk)
        self.assert_default_site_unchanged()
