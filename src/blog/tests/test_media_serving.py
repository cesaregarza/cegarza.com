import tempfile
from pathlib import Path

from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import Resolver404, resolve

from cegarza_site.urls import _local_media_urlpatterns, serve_local_media


class LocalMediaServingTest(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.media_root = Path(self.temporary_directory.name) / "media"
        self.media_root.mkdir()
        self.original_images_root = self.media_root / "original_images"
        self.original_images_root.mkdir()
        self.media_file = self.original_images_root / "example.png"
        self.media_file.write_bytes(b"verified-media")

    def tearDown(self):
        self.temporary_directory.cleanup()

    @override_settings(
        DEBUG=False,
        SERVE_MEDIA=True,
        USE_SPACES=False,
        MEDIA_URL="/media/",
    )
    def test_explicit_flag_serves_local_media_with_debug_disabled(self):
        request = self.request_factory.get("/media/original_images/example.png")

        with override_settings(MEDIA_ROOT=self.media_root):
            patterns = _local_media_urlpatterns()
            match = resolve("/media/original_images/example.png", urlconf=tuple(patterns))
            response = match.func(request, **match.kwargs)

        self.assertEqual(len(patterns), 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/png")
        self.assertEqual(b"".join(response.streaming_content), b"verified-media")

    @override_settings(
        DEBUG=False,
        SERVE_MEDIA=False,
        USE_SPACES=False,
        MEDIA_URL="/media/",
    )
    def test_local_media_is_not_served_when_disabled(self):
        request = self.request_factory.get("/media/original_images/example.png")

        with override_settings(MEDIA_ROOT=self.media_root):
            self.assertEqual(_local_media_urlpatterns(), [])
            with self.assertRaises(Http404):
                serve_local_media(request, "original_images/example.png")

    @override_settings(
        DEBUG=False,
        SERVE_MEDIA=True,
        USE_SPACES=False,
        MEDIA_URL="/media/",
    )
    def test_path_traversal_is_rejected(self):
        outside_file = self.media_root.parent / "outside.txt"
        outside_file.write_text("must-not-be-served", encoding="utf-8")
        request = self.request_factory.get(
            "/media/original_images/../../outside.txt"
        )

        with override_settings(MEDIA_ROOT=self.media_root):
            with self.assertRaises(Http404):
                serve_local_media(
                    request,
                    "original_images/../../outside.txt",
                )

    @override_settings(
        DEBUG=False,
        SERVE_MEDIA=True,
        USE_SPACES=False,
        MEDIA_URL="/media/",
    )
    def test_directory_indexes_remain_disabled(self):
        private_directory = self.original_images_root / "private"
        private_directory.mkdir()
        (private_directory / "index.txt").write_text("hidden", encoding="utf-8")
        request = self.request_factory.get("/media/original_images/private/")

        with override_settings(MEDIA_ROOT=self.media_root):
            with self.assertRaises(Http404):
                serve_local_media(request, "original_images/private/")

    @override_settings(
        DEBUG=False,
        SERVE_MEDIA=True,
        USE_SPACES=False,
        MEDIA_URL="/media/",
    )
    def test_documents_are_not_exposed_through_the_media_route(self):
        documents_root = self.media_root / "documents"
        documents_root.mkdir()
        (documents_root / "payload.html").write_text(
            "<script>window.exposed = true</script>",
            encoding="utf-8",
        )
        request = self.request_factory.get("/media/documents/payload.html")

        with override_settings(MEDIA_ROOT=self.media_root):
            patterns = _local_media_urlpatterns()
            with self.assertRaises(Http404):
                serve_local_media(request, "documents/payload.html")
            with self.assertRaises(Resolver404):
                resolve("/media/documents/payload.html", urlconf=tuple(patterns))

    @override_settings(
        DEBUG=False,
        SERVE_MEDIA=True,
        USE_SPACES=False,
        MEDIA_URL="/media/",
    )
    def test_symlink_escape_is_rejected(self):
        outside_file = self.media_root.parent / "outside.txt"
        outside_file.write_text("must-not-be-served", encoding="utf-8")
        symlink = self.original_images_root / "escape.txt"
        symlink.symlink_to(outside_file)
        request = self.request_factory.get("/media/original_images/escape.txt")

        with override_settings(MEDIA_ROOT=self.media_root):
            with self.assertRaises(Http404):
                serve_local_media(request, "original_images/escape.txt")

    @override_settings(DEBUG=False, SERVE_MEDIA=True, USE_SPACES=True, MEDIA_URL="/media/")
    def test_spaces_storage_never_installs_a_local_media_route(self):
        self.assertEqual(_local_media_urlpatterns(), [])

    @override_settings(
        DEBUG=False,
        SERVE_MEDIA=True,
        USE_SPACES=False,
        MEDIA_URL="https://cdn.example.com/media/",
    )
    def test_absolute_media_url_never_installs_a_local_media_route(self):
        self.assertEqual(_local_media_urlpatterns(), [])
