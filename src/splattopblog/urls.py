"""
URL configuration for splattopblog project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.contrib.sitemaps.views import sitemap
from wagtail.documents import urls as wagtaildocs_urls

from blog import views as blog_views
from blog.feeds import BlogAtomFeed, BlogFeed
from blog.robots import robots_txt

handler404 = "blog.views.custom_404"
handler500 = "blog.views.custom_500"

urlpatterns = [
    path("robots.txt", robots_txt, name="robots-txt"),
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
    path("sitemap.xml", sitemap, name="sitemap"),
]

if settings.DEBUG or settings.SERVE_MEDIA:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Wagtail pages - must be last, after any debug/static routes.
urlpatterns += [
    path("", include(wagtail_urls)),
]
