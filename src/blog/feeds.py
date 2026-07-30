from dataclasses import dataclass

from django.contrib.syndication.views import Feed
from django.utils.feedgenerator import Atom1Feed
from wagtail.models import Site

from blog.context_processors import site_identity_values
from blog.models import BlogIndexPage, BlogPage
from blog.site_urls import page_full_url_for_site


@dataclass(frozen=True, slots=True)
class BlogFeedItem:
    page: BlogPage
    site: Site | None


class BlogFeed(Feed):
    def title(self, site):
        return site_identity_values(site)["site_name"]

    def description(self, site):
        return site_identity_values(site)["site_description"]

    def get_object(self, request):
        return Site.find_for_request(request)

    def link(self, site):
        if not site:
            return "/"
        root_page = site.root_page.specific
        if isinstance(root_page, BlogIndexPage):
            index = root_page
        else:
            index = (
                BlogIndexPage.objects.descendant_of(site.root_page)
                .live()
                .public()
                .order_by("path")
                .first()
            )
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
        return site_identity_values(site)["site_description"]
