from urllib.parse import urljoin

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

    site_name = site_name or settings.SITE_NAME
    site_author = site_author or settings.SITE_AUTHOR
    site_role = getattr(settings, "SITE_ROLE", "")
    site_role_description = getattr(settings, "SITE_ROLE_DESCRIPTION", "")
    # Absolute origin for structured-data URLs. Prefer the requesting Site's own
    # root_url so multi-site pages never leak a sibling host; fall back to the
    # configured SITE_URL only when no Site is available (error/None path).
    site_root_url = (getattr(site, "root_url", "") or "").strip() if site else ""
    site_url = (site_root_url or getattr(settings, "SITE_URL", "")).rstrip("/")

    return {
        "site_name": site_name,
        # Tagline. Still used for RSS alternate-link titles; NO LONGER the
        # meta-description fallback (that is site_role_description).
        "site_description": site_description or settings.SITE_DESCRIPTION,
        "site_author": site_author,
        # Name-first descriptors for per-page title/description overrides.
        "site_role": site_role,
        "site_home_title": f"{site_author} — {site_role}",
        "site_writing_title": f"Writing — {site_author}",
        "site_role_description": site_role_description,
        # Structured-data / absolute-URL identity.
        "site_url": site_url,
        "publisher_logo_url": getattr(settings, "SITE_PUBLISHER_LOGO", ""),
        "person_same_as": list(getattr(settings, "SITE_SAMEAS", []) or []),
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


def _absolute_url(site_url, path):
    """Join an absolute origin with a site-relative path."""
    if not site_url:
        return path
    return urljoin(f"{site_url}/", (path or "/").lstrip("/"))


def site_identity(request):
    """Expose branding for the Wagtail Site that owns this request."""

    try:
        site = Site.find_for_request(request)
        identity = site_identity_values(site)
        navigation = site_navigation_values(site)
    except DatabaseError:
        identity = site_identity_values(None)
        navigation = site_navigation_values(None)

    site_url = identity["site_url"]
    person_url = (
        getattr(settings, "SITE_PERSON_URL", "")
        or _absolute_url(site_url, navigation["site_about_url"] or "/about/")
        or site_url
    )
    breadcrumbs = {
        "person_url": person_url,
        "breadcrumb_home_url": _absolute_url(site_url, navigation["site_home_url"]),
        "breadcrumb_writing_url": _absolute_url(
            site_url, navigation["site_writing_url"]
        ),
    }
    return {
        **identity,
        **navigation,
        **breadcrumbs,
        "wagtail_admin_base_url": settings.WAGTAILADMIN_BASE_URL,
    }
