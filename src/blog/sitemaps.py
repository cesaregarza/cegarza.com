from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from wagtail.contrib.sitemaps.sitemap_generator import Sitemap as WagtailSitemap
from wagtail.contrib.sitemaps.views import sitemap

from .series import public_series_for_index, request_site_and_index


class BlogSeriesSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def __init__(self, request):
        self.request = request
        self.site, self.blog_index = request_site_and_index(request)
        self.groups = public_series_for_index(self.blog_index, site=self.site)

    def items(self):
        if not self.blog_index:
            return []
        return ["index", *self.groups]

    def location(self, item):
        if item == "index":
            return reverse("blog-series-index")
        return item.url

    def lastmod(self, item):
        parts = [
            part.page.last_published_at
            for group in self.groups
            for part in group.parts
            if item == "index" or group == item
        ]
        return max((value for value in parts if value is not None), default=None)


def public_sitemap(request):
    return sitemap(
        request,
        sitemaps={
            "wagtail": WagtailSitemap(request),
            "series": BlogSeriesSitemap(request),
        },
    )
