from django.conf import settings
from django.db import DatabaseError
from wagtail.models import Site

from blog.models import BlogIndexPage


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


def site_identity(request):
    """Expose branding for the Wagtail Site that owns this request."""

    try:
        identity = site_identity_values(Site.find_for_request(request))
    except DatabaseError:
        identity = site_identity_values(None)
    return {
        **identity,
        "wagtail_admin_base_url": settings.WAGTAILADMIN_BASE_URL,
    }
