"""URL configuration for the cegarza.com site."""

import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.core.exceptions import SuspiciousFileOperation
from django.http import Http404
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve as serve_static_file
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

from blog import views as blog_views
from blog.feeds import BlogAtomFeed, BlogFeed, BlogSeriesAtomFeed, BlogSeriesFeed
from blog.robots import robots_txt
from blog.sitemaps import public_sitemap

handler404 = "blog.views.custom_404"
handler500 = "blog.views.custom_500"

_LOCAL_MEDIA_NAMESPACES = ("original_images", "images")


def serve_local_media(request, path):
    """Serve retained local media only when the runtime explicitly enables it."""
    if not (settings.DEBUG or settings.SERVE_MEDIA):
        raise Http404

    try:
        requested_path = PurePosixPath(path)
        if (
            requested_path.is_absolute()
            or len(requested_path.parts) < 2
            or requested_path.parts[0] not in _LOCAL_MEDIA_NAMESPACES
            or ".." in requested_path.parts
        ):
            raise Http404

        media_root = Path(settings.MEDIA_ROOT).resolve()
        namespace_root = (media_root / requested_path.parts[0]).resolve()
        namespace_root.relative_to(media_root)

        target = namespace_root.joinpath(*requested_path.parts[1:]).resolve()
        target.relative_to(namespace_root)
        canonical_path = target.relative_to(media_root).as_posix()

        return serve_static_file(
            request,
            canonical_path,
            document_root=media_root,
            show_indexes=False,
        )
    except (OSError, RuntimeError, SuspiciousFileOperation, ValueError) as exc:
        raise Http404 from exc


def _local_media_urlpatterns():
    """Build media routes without relying on Django's DEBUG-only helper."""
    if settings.DEBUG:
        return static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    if not settings.SERVE_MEDIA or settings.USE_SPACES:
        return []

    media_url = urlsplit(settings.MEDIA_URL)
    media_prefix = media_url.path.lstrip("/")
    if media_url.netloc or not media_url.path.startswith("/") or not media_prefix:
        return []

    namespace_pattern = "|".join(re.escape(namespace) for namespace in _LOCAL_MEDIA_NAMESPACES)
    return [
        re_path(
            rf"^{re.escape(media_prefix)}"
            rf"(?P<path>(?:{namespace_pattern})/.*)$",
            serve_local_media,
            name="local-media",
        )
    ]


urlpatterns = [
    path("robots.txt", robots_txt, name="robots-txt"),
    path("site.webmanifest", blog_views.web_manifest, name="web_manifest"),
    path("django-admin/", admin.site.urls),
    path("admin/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("health/", include("health_check.urls")),
    re_path(r"^(?P<page_path>.+)\.md$", blog_views.blog_page_markdown),
    path("feed/", BlogFeed(), name="blog-feed"),
    path(
        "rss/",
        RedirectView.as_view(pattern_name="blog-feed", permanent=True),
        name="legacy-rss-feed",
    ),
    path("feed/atom/", BlogAtomFeed(), name="blog-atom-feed"),
    path("series/", blog_views.series_index, name="blog-series-index"),
    path(
        "series/<slug:slug>/feed/",
        BlogSeriesFeed(),
        name="blog-series-feed",
    ),
    path(
        "series/<slug:slug>/feed/atom/",
        BlogSeriesAtomFeed(),
        name="blog-series-atom-feed",
    ),
    path(
        "series/<slug:slug>/",
        blog_views.series_detail,
        name="blog-series-detail",
    ),
    path("sitemap.xml", public_sitemap, name="sitemap"),
]

urlpatterns += _local_media_urlpatterns()
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Wagtail pages - must be last, after any debug/static routes.
urlpatterns += [
    path("", include(wagtail_urls)),
]
