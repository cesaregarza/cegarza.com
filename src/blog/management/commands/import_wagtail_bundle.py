import json

from django.core.management.base import BaseCommand, CommandError

from blog.wagtail_port import WagtailPortError, import_wagtail_bundle


class Command(BaseCommand):
    help = "Validate or import a bounded, credential-free Wagtail content bundle."

    def add_arguments(self, parser):
        parser.add_argument("bundle")
        parser.add_argument("--hostname", required=True)
        parser.add_argument("--port", type=int, default=443)
        parser.add_argument("--source-namespace", required=True)
        parser.add_argument("--bundle-sha256", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            summary = import_wagtail_bundle(
                options["bundle"],
                hostname=options["hostname"],
                port=options["port"],
                expected_namespace=options["source_namespace"],
                expected_bundle_sha256=options["bundle_sha256"],
                dry_run=options["dry_run"],
            )
        except WagtailPortError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(summary.as_dict(), sort_keys=True))
