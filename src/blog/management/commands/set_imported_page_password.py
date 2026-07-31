import sys

from django.core.management.base import BaseCommand, CommandError

from blog.wagtail_port import WagtailPortError, set_imported_page_password

MAX_PASSWORD_INPUT = 255


class Command(BaseCommand):
    help = "Set one imported page restriction password from a non-interactive stdin pipe."

    def add_arguments(self, parser):
        parser.add_argument("--source-namespace", required=True)
        parser.add_argument("--source-page-id", required=True, type=int)

    def handle(self, *args, **options):
        if sys.stdin.isatty():
            raise CommandError("Password input must arrive through a non-interactive stdin pipe.")
        password = sys.stdin.read(MAX_PASSWORD_INPUT + 1)
        if len(password) > MAX_PASSWORD_INPUT:
            raise CommandError("Password input exceeds the supported limit.")
        try:
            set_imported_page_password(
                options["source_namespace"],
                options["source_page_id"],
                password,
            )
        except WagtailPortError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write("Updated one imported page restriction.")
