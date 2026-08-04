import os
from urllib.parse import urlparse

from django import http
from django.conf import settings
from django.urls import Resolver404
from django.utils.deprecation import MiddlewareMixin
from wagtail.contrib.redirects import models as redirect_models
from wagtail.contrib.redirects.middleware import get_redirect
from wagtail.models import Site

from blog.site_urls import page_full_url_for_site

APPLET_INLINE_SCRIPT_HASHES = (
    "sha256-ahjuAJ6kuYRzHlz7zYWvwxvFDKjnKHquGIEGzpuavXU=",
    "sha256-2svO+pGuPmmPvv5RF/vvH4POgwfrKwYcFe8MN6mGEiU=",
    "sha256-l6bkXz93BMcC3viToBnVBss7AXM1ZfPnkJ/cAHDYvV4=",
)


def _redirect_target_for_site(redirect, request, site):
    if redirect.redirect_page:
        page = redirect.redirect_page.specific_deferred
        base_url = page_full_url_for_site(page, site) if site else None
        if not base_url:
            base_url = page.get_url(request)
        if not base_url:
            return None
        if not redirect.redirect_page_route_path:
            return base_url
        try:
            page.resolve_subpage(redirect.redirect_page_route_path)
        except (AttributeError, Resolver404):
            return base_url
        return base_url.rstrip("/") + redirect.redirect_page_route_path
    if redirect.redirect_link:
        return redirect.redirect_link
    return None


class SiteAwareRedirectMiddleware(MiddlewareMixin):
    """Wagtail redirect handling with page targets bound to the request Site."""

    def process_response(self, request, response):
        if response.status_code != 404:
            return response

        path = redirect_models.Redirect.normalise_path(request.get_full_path())
        redirect = get_redirect(request, path)
        if redirect is None:
            path_without_query = urlparse(path).path
            if path == path_without_query:
                return response
            redirect = get_redirect(request, path_without_query)
            if redirect is None:
                return response

        site = Site.find_for_request(request)
        target = _redirect_target_for_site(redirect, request, site)
        if target is None:
            return response
        response_class = (
            http.HttpResponsePermanentRedirect
            if redirect.is_permanent
            else http.HttpResponseRedirect
        )
        return response_class(target)


class FrontendSecurityHeadersMiddleware:
    """Attach additional frontend security headers without impacting Wagtail admin."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.enforce_csp = os.environ.get("CSP_ENFORCE", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def __call__(self, request):
        response = self.get_response(request)
        if self._is_admin_path(request.path):
            return response

        csp_header = "Content-Security-Policy" if self.enforce_csp else "Content-Security-Policy-Report-Only"
        script_sources = ["'self'", "https://cdn.jsdelivr.net"]
        if self._is_applet_path(request.path):
            script_sources.extend(f"'{script_hash}'" for script_hash in APPLET_INLINE_SCRIPT_HASHES)
        csp_directives = [
            "default-src 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "frame-ancestors 'self'",
            "img-src 'self' data: https:",
            "font-src 'self' data: https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
            f"script-src {' '.join(script_sources)}",
            "connect-src 'self'",
            "form-action 'self'",
        ]
        if settings.ALLOWED_EMBED_HOSTS:
            frame_hosts = " ".join(f"https://{host}" for host in settings.ALLOWED_EMBED_HOSTS)
            csp_directives.append(f"frame-src 'self' {frame_hosts}")
        else:
            csp_directives.append("frame-src 'self'")
        if self.enforce_csp:
            csp_directives.append("upgrade-insecure-requests")
        csp_policy = "; ".join(csp_directives)
        response.setdefault(csp_header, csp_policy)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @staticmethod
    def _is_admin_path(path):
        return path.startswith("/admin/") or path.startswith("/django-admin/")

    @staticmethod
    def _is_applet_path(path):
        return path.startswith("/static/applets/")
