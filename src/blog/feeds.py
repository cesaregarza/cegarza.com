from dataclasses import dataclass
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.syndication.views import Feed
from django.http import Http404
from django.urls import reverse
from django.utils.feedgenerator import Atom1Feed
from wagtail.models import Site

from blog.context_processors import site_identity_values
from blog.models import BlogIndexPage, BlogPage
from blog.series import (
    PublicSeries,
    PublicSeriesPart,
    blog_index_for_site,
    public_series_for_index,
)
from blog.site_urls import page_full_url_for_site


@dataclass(frozen=True, slots=True)
class BlogFeedItem:
    page: BlogPage
    site: Site | None


class BlogFeed(Feed):
    def title(self, site):
        return site_identity_values(site)["site_name"]

    def _index(self, site):
        if not site:
            return None
        root_page = site.root_page.specific
        if isinstance(root_page, BlogIndexPage):
            return root_page
        return (
            BlogIndexPage.objects.descendant_of(site.root_page)
            .live()
            .public()
            .order_by("path")
            .first()
        )

    def description(self, site):
        index = self._index(site)
        intro = (getattr(index, "intro", "") or "").strip()
        return intro or settings.SITE_ROLE_DESCRIPTION

    def get_object(self, request):
        return Site.find_for_request(request)

    def link(self, site):
        if not site:
            return "/"
        index = self._index(site)
        return page_full_url_for_site(index, site) if index else site.root_url

    def items(self, site):
        posts = BlogPage.objects.live().public()
        if site:
            posts = posts.descendant_of(site.root_page)
        return [
            BlogFeedItem(page=page, site=site)
            for page in posts.order_by("-first_published_at")[:20]
        ]

    def item_title(self, item):
        return item.page.title

    def item_description(self, item):
        return item.page.abstract or item.page.search_description or ""

    def item_link(self, item):
        if item.site:
            return page_full_url_for_site(item.page, item.site)
        return item.page.get_full_url()

    def item_pubdate(self, item):
        return item.page.first_published_at

    def item_author_name(self, item):
        author = item.page.primary_author
        return author.name if author else site_identity_values(item.site)["site_author"]


class BlogAtomFeed(BlogFeed):
    feed_type = Atom1Feed

    def subtitle(self, site):
        return self.description(site)


@dataclass(frozen=True, slots=True)
class BlogSeriesFeedContext:
    group: PublicSeries
    site: Site


@dataclass(frozen=True, slots=True)
class BlogSeriesFeedItem:
    part: PublicSeriesPart
    site: Site


class BlogSeriesFeed(Feed):
    def get_object(self, request, slug):
        site = Site.find_for_request(request)
        blog_index = blog_index_for_site(site)
        groups = public_series_for_index(blog_index, site=site, slug=slug)
        if not site or not groups:
            raise Http404
        return BlogSeriesFeedContext(group=groups[0], site=site)

    def title(self, context):
        return f"{context.group.series.title} · {site_identity_values(context.site)['site_name']}"

    def description(self, context):
        return context.group.series.description or site_identity_values(context.site)[
            "site_description"
        ]

    def link(self, context):
        return urljoin(
            f"{context.site.root_url.rstrip('/')}/",
            reverse(
                "blog-series-detail",
                kwargs={"slug": context.group.series.slug},
            ),
        )

    def items(self, context):
        return [
            BlogSeriesFeedItem(part=part, site=context.site)
            for part in context.group.parts
        ]

    def item_title(self, item):
        return item.part.page.title

    def item_description(self, item):
        return item.part.page.abstract or item.part.page.search_description or ""

    def item_link(self, item):
        return item.part.url

    def item_pubdate(self, item):
        return item.part.page.first_published_at

    def item_author_name(self, item):
        author = item.part.page.primary_author
        return (
            author.name
            if author
            else site_identity_values(item.site)["site_author"]
        )


class BlogSeriesAtomFeed(BlogSeriesFeed):
    feed_type = Atom1Feed

    def subtitle(self, context):
        return self.description(context)
