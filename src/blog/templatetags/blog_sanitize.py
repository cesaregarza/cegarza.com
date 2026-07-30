from django import template
from django.utils.safestring import mark_safe
from wagtail.models import Site

from blog.html_sanitizer import sanitize_structural_html
from blog.site_urls import page_full_url_for_site

register = template.Library()


@register.filter(name="sanitize_html")
def sanitize_html(value):
    if not value:
        return ""
    return mark_safe(sanitize_structural_html(value))


@register.simple_tag(takes_context=True)
def current_page_full_url(context, page):
    """Build a page URL against the Site selected by the current request."""

    request = context.get("request")
    if request is None or page is None:
        return ""
    site = Site.find_for_request(request)
    if site is None:
        return ""
    return page_full_url_for_site(page, site)
