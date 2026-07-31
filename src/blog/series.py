from dataclasses import dataclass

from django.urls import reverse
from wagtail.models import Site

from .models import BlogIndexPage, BlogPage, BlogSeries, BlogSeriesMembership
from .site_urls import page_path_for_site


@dataclass(frozen=True, slots=True)
class PublicSeriesPart:
    membership: BlogSeriesMembership
    page: BlogPage
    number: int
    read_minutes: int
    url: str
    is_latest: bool

    @property
    def readtime(self):
        return self.page.body_rendered_readtime_main or f"{self.read_minutes} min"

    @property
    def is_primary(self):
        return self.membership.is_primary


@dataclass(frozen=True, slots=True)
class PublicSeries:
    series: BlogSeries
    parts: tuple[PublicSeriesPart, ...]
    total_minutes: int

    @property
    def part_count(self):
        return len(self.parts)

    @property
    def hidden_part_count(self):
        return max(0, len(self.parts) - 3)

    @property
    def url(self):
        return reverse("blog-series-detail", kwargs={"slug": self.series.slug})

    @property
    def feed_url(self):
        return reverse("blog-series-feed", kwargs={"slug": self.series.slug})


@dataclass(frozen=True, slots=True)
class PublicSeriesSelection:
    group: PublicSeries
    part: PublicSeriesPart


def blog_index_for_site(site):
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


def public_posts_for_index(blog_index):
    if not blog_index:
        return BlogPage.objects.none()
    return BlogPage.objects.child_of(blog_index).live().public()


def _read_minutes(page):
    raw = page.body_rendered_readtime_main or ""
    token = raw.partition(" ")[0]
    try:
        return max(1, int(token))
    except (TypeError, ValueError):
        return 1


def public_series_for_index(blog_index, *, site=None, slug=None):
    public_posts = public_posts_for_index(blog_index)
    memberships = (
        BlogSeriesMembership.objects.filter(page_id__in=public_posts.values("pk"))
        .select_related("page", "series")
        .order_by("series__title", "series_id", "sort_order", "pk")
    )
    if slug is not None:
        memberships = memberships.filter(series__slug=slug)

    grouped_memberships = {}
    for membership in memberships:
        grouped_memberships.setdefault(membership.series_id, []).append(membership)

    groups = []
    for series_memberships in grouped_memberships.values():
        series = series_memberships[0].series
        final_number = len(series_memberships)
        parts = tuple(
            PublicSeriesPart(
                membership=membership,
                page=membership.page,
                number=number,
                read_minutes=_read_minutes(membership.page),
                url=page_path_for_site(membership.page, site)
                if site
                else membership.page.url,
                is_latest=number == final_number,
            )
            for number, membership in enumerate(series_memberships, start=1)
        )
        groups.append(
            PublicSeries(
                series=series,
                parts=parts,
                total_minutes=sum(part.read_minutes for part in parts),
            )
        )
    return groups


def public_series_context_for_page(page, blog_index, *, site=None):
    selections = []
    for group in public_series_for_index(blog_index, site=site):
        for part in group.parts:
            if part.page.pk == page.pk:
                selections.append(PublicSeriesSelection(group=group, part=part))
                break

    selections.sort(
        key=lambda selection: (
            not selection.part.is_primary,
            selection.group.series.title.casefold(),
            selection.group.series.pk,
        )
    )
    if not selections:
        return {
            "post_series": None,
            "series_part": None,
            "series_previous": None,
            "series_next": None,
            "also_series": (),
        }

    primary = selections[0]
    previous_part = (
        primary.group.parts[primary.part.number - 2]
        if primary.part.number > 1
        else None
    )
    next_part = (
        primary.group.parts[primary.part.number]
        if primary.part.number < primary.group.part_count
        else None
    )
    return {
        "post_series": primary.group,
        "series_part": primary.part,
        "series_previous": previous_part,
        "series_next": next_part,
        "also_series": tuple(selections[1:]),
    }


def site_has_public_series(site):
    blog_index = blog_index_for_site(site)
    public_posts = public_posts_for_index(blog_index)
    return BlogSeriesMembership.objects.filter(
        page_id__in=public_posts.values("pk")
    ).exists()


def request_site_and_index(request):
    site = Site.find_for_request(request)
    return site, blog_index_for_site(site)
