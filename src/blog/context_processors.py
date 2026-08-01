from django.conf import settings
from django.db import DatabaseError
from wagtail.models import Site

from blog.models import BlogIndexPage, ContentPage
from blog.series import site_has_public_series
from blog.site_urls import page_path_for_site


def site_identity_values(site):
    site_name = (site.site_name or "").strip() if site else ""
    site_description = ""
    site_author = ""
    if site:
        root_page = site.root_page.specific
        if isinstance(root_page, BlogIndexPage):
            site_description = (root_page.intro or "").strip()
            site_author = (root_page.default_author_name or "").strip()

    return {
        "site_name": site_name or settings.SITE_NAME,
        "site_description": site_description or settings.SITE_DESCRIPTION,
        "site_author": site_author or settings.SITE_AUTHOR,
    }


def site_navigation_values(site):
    navigation = {
        "site_home_url": "/",
        "site_writing_url": "/writing/",
        "site_about_url": "",
        "site_series_url": "",
    }
    if not site or not getattr(site, "root_page_id", None):
        return navigation

    root_page = site.root_page.specific
    if isinstance(root_page, BlogIndexPage):
        blog_index = root_page
    else:
        blog_index = (
            BlogIndexPage.objects.descendant_of(site.root_page)
            .live()
            .public()
            .order_by("path")
            .first()
        )

    if not blog_index:
        return navigation

    navigation["site_home_url"] = page_path_for_site(blog_index, site) or "/"
    if blog_index.is_root_for_site(site):
        navigation["site_writing_url"] = (
            navigation["site_home_url"].rstrip("/") + "/writing/"
        )
    else:
        navigation["site_writing_url"] = navigation["site_home_url"]
    about_page = (
        ContentPage.objects.child_of(blog_index)
        .live()
        .public()
        .filter(slug="about")
        .first()
    )
    if about_page:
        navigation["site_about_url"] = page_path_for_site(about_page, site) or ""
    if site_has_public_series(site):
        navigation["site_series_url"] = "/series/"
    return navigation


def site_identity(request):
    """Expose branding for the Wagtail Site that owns this request."""

    try:
        site = Site.find_for_request(request)
        identity = site_identity_values(site)
        navigation = site_navigation_values(site)
    except DatabaseError:
        identity = site_identity_values(None)
        navigation = site_navigation_values(None)
    return {
        **identity,
        **navigation,
        "wagtail_admin_base_url": settings.WAGTAILADMIN_BASE_URL,
    }
