from urllib.parse import urljoin


def page_path_for_site(page, site):
    """Return a standard Wagtail page path relative to an explicit Site root."""

    root_url_path = site.root_page.url_path
    if not page.url_path.startswith(root_url_path):
        return None
    relative_path = page.url_path[len(root_url_path) :]
    return f"/{relative_path}"


def page_full_url_for_site(page, site):
    path = page_path_for_site(page, site)
    if path is None:
        return ""
    return urljoin(f"{site.root_url.rstrip('/')}/", path.lstrip("/"))
