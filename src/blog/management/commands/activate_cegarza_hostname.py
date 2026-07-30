from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from wagtail.contrib.redirects.models import Redirect
from wagtail.models import Site

from blog.models import BlogIndexPage

SOURCE_HOSTNAME = "preview.cegarza.com"
SOURCE_PORT = 443
TARGET_HOSTNAME = "cegarza.com"
TARGET_PORT = 443


class Command(BaseCommand):
    help = (
        "Add the cegarza.com:443 Wagtail Site alias for the existing preview.cegarza.com:443 blog."
    )

    def handle(self, *args, **options):
        try:
            created = self._activate()
        except IntegrityError as exc:
            raise CommandError(
                "The Wagtail Site table changed during activation; inspect it before retrying."
            ) from exc

        if created:
            message = (
                f"Created {TARGET_HOSTNAME}:{TARGET_PORT} as an alias of "
                f"{SOURCE_HOSTNAME}:{SOURCE_PORT}."
            )
        else:
            message = (
                f"{TARGET_HOSTNAME}:{TARGET_PORT} already aliases "
                f"{SOURCE_HOSTNAME}:{SOURCE_PORT}; no changes made."
            )
        self.stdout.write(self.style.SUCCESS(message))

    @transaction.atomic
    def _activate(self):
        source_sites = list(
            Site.objects.select_for_update()
            .select_related("root_page")
            .filter(hostname=SOURCE_HOSTNAME)
        )
        if len(source_sites) != 1:
            raise CommandError(
                f"Expected exactly one {SOURCE_HOSTNAME} Wagtail Site; found {len(source_sites)}."
            )

        source = source_sites[0]
        if source.port != SOURCE_PORT:
            raise CommandError(
                f"The {SOURCE_HOSTNAME} Wagtail Site must use port {SOURCE_PORT}; "
                f"found port {source.port}."
            )
        if not isinstance(source.root_page.specific, BlogIndexPage):
            raise CommandError(f"{SOURCE_HOSTNAME}:{SOURCE_PORT} is not rooted at a BlogIndexPage.")

        target_sites = list(
            Site.objects.select_for_update()
            .select_related("root_page")
            .filter(hostname=TARGET_HOSTNAME)
        )
        if target_sites:
            if len(target_sites) != 1:
                raise CommandError(
                    f"Expected at most one {TARGET_HOSTNAME} Wagtail Site; "
                    f"found {len(target_sites)}."
                )

            target = target_sites[0]
            if target.port != TARGET_PORT:
                raise CommandError(
                    f"{TARGET_HOSTNAME} already exists on port {target.port}; "
                    f"refusing to create the port {TARGET_PORT} alias."
                )
            if target.root_page_id != source.root_page_id:
                raise CommandError(
                    f"{TARGET_HOSTNAME}:{TARGET_PORT} points at a different root page."
                )
            created = False
        else:
            target = Site.objects.create(
                hostname=TARGET_HOSTNAME,
                port=TARGET_PORT,
                site_name=source.site_name,
                root_page=source.root_page,
                is_default_site=False,
            )
            created = True

        self._sync_redirects(source, target)
        return created

    @staticmethod
    def _sync_redirects(source, target):
        target_redirects = {
            redirect.old_path: redirect
            for redirect in Redirect.objects.select_for_update().filter(site=target)
        }
        source_redirects = list(Redirect.objects.select_for_update().filter(site=source))
        source_paths = {redirect.old_path for redirect in source_redirects}
        unexpected_target_paths = set(target_redirects) - source_paths
        if unexpected_target_paths:
            raise CommandError(
                f"{TARGET_HOSTNAME}:{TARGET_PORT} has redirects that are not present "
                f"on {SOURCE_HOSTNAME}:{SOURCE_PORT}."
            )

        for source_redirect in source_redirects:
            if not source_redirect.is_permanent:
                raise CommandError(
                    f"{SOURCE_HOSTNAME}:{SOURCE_PORT} has a non-permanent redirect "
                    f"for {source_redirect.old_path}."
                )
            target_redirect = target_redirects.get(source_redirect.old_path)
            desired = {
                "is_permanent": True,
                "redirect_page_id": source_redirect.redirect_page_id,
                "redirect_link": source_redirect.redirect_link,
                "redirect_page_route_path": source_redirect.redirect_page_route_path,
            }
            if target_redirect:
                if any(
                    getattr(target_redirect, field_name) != value
                    for field_name, value in desired.items()
                ):
                    raise CommandError(
                        f"{TARGET_HOSTNAME}:{TARGET_PORT} has a conflicting redirect "
                        f"for {source_redirect.old_path}."
                    )
                continue

            Redirect.objects.create(
                site=target,
                old_path=source_redirect.old_path,
                **desired,
            )
