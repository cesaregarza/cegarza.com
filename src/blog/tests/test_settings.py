from unittest import TestCase

from django.conf import settings

from splattopblog.settings import parse_database_url


class DatabaseUrlParsingTest(TestCase):
    def test_sslrootcert_is_passed_to_postgresql_options(self):
        config = parse_database_url(
            "postgresql://cegarza:secret@db.example:25060/cegarzablog"
            "?sslmode=verify-full&sslrootcert=%2Fetc%2Fcegarza-db%2Fca.crt"
        )

        self.assertEqual(
            config["OPTIONS"],
            {
                "sslmode": "verify-full",
                "sslrootcert": "/etc/cegarza-db/ca.crt",
            },
        )
        self.assertNotIn("sslrootcert", config)

    def test_unrecognised_tls_query_options_are_not_passed_through(self):
        config = parse_database_url(
            "postgresql://cegarza:secret@db.example/cegarzablog"
            "?sslmode=require&sslcert=%2Ftmp%2Fclient.crt"
        )

        self.assertEqual(config["OPTIONS"], {"sslmode": "require"})


class MediaStorageSafetyTest(TestCase):
    def test_s3_media_never_overwrites_existing_object_keys(self):
        self.assertIs(settings.AWS_S3_FILE_OVERWRITE, False)
