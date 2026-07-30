from django.core.management.base import BaseCommand, CommandError

from blog.ghost_import import GhostImportError, import_ghost_export


class Command(BaseCommand):
    help = "Import a pruned Ghost migration export and sanitized media-only image archive."

    def add_arguments(self, parser):
        parser.add_argument("export_json")
        parser.add_argument("files_archive")
        parser.add_argument("--hostname", required=True)
        parser.add_argument("--port", type=int, default=443)
        parser.add_argument(
            "--site-name",
            help="Override the Ghost publication title for this Wagtail Site.",
        )
        parser.add_argument(
            "--site-description",
            help="Override the Ghost publication description for this Wagtail Site.",
        )
        parser.add_argument(
            "--site-author",
            help="Override the sole imported Ghost author used as the site fallback.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the export, archive, mappings, and sanitizer without writing.",
        )

    def handle(self, *args, **options):
        try:
            summary = import_ghost_export(
                options["export_json"],
                options["files_archive"],
                hostname=options["hostname"],
                port=options["port"],
                site_name=options["site_name"],
                site_description=options["site_description"],
                site_author=options["site_author"],
                dry_run=options["dry_run"],
            )
        except GhostImportError as exc:
            raise CommandError(str(exc)) from exc

        mode = "validated" if options["dry_run"] else "imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"Ghost export {mode}: "
                f"{summary.published_posts} published posts, "
                f"{summary.draft_posts} draft posts, "
                f"{summary.pages} pages, "
                f"{summary.authors} authors, "
                f"{summary.tags} tags, "
                f"{summary.archive_images} archive images, "
                f"{summary.inline_images} extracted inline images "
                f"({summary.images} total); "
                f"{summary.redirects} permanent redirects; "
                f"{summary.created_pages} pages created, "
                f"{summary.updated_pages} pages updated, "
                f"{summary.unchanged_pages} pages unchanged."
            )
        )
