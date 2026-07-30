from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.html import strip_tags
from wagtail.forms import PasswordViewRestrictionForm
from wagtail.models import PageViewRestriction, Site

from .models import BlogPage


def custom_404(request, exception):
    return render(request, "404.html", status=404)


def custom_500(request):
    return render(request, "500.html", status=500)


def _escape_tag_value(value):
    if value is None:
        return ""
    text = str(value)
    return text.replace("\\", "\\\\").replace(";", "\\;").replace("]", "\\]")


def _struct_value_get(value, key, default=None):
    getter = getattr(value, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
    if hasattr(value, key):
        return getattr(value, key)
    try:
        return value[key]
    except Exception:
        return default


def _html_to_text(html):
    if not html:
        return ""
    text = strip_tags(html)
    return text.strip()


def _enforce_view_restrictions(request, page, *, fail_closed=False):
    restrictions = page.get_view_restrictions()
    for restriction in restrictions:
        if restriction.accept_request(request):
            continue
        if fail_closed:
            raise Http404
        if restriction.restriction_type == PageViewRestriction.PASSWORD:
            form = PasswordViewRestrictionForm(
                instance=restriction,
                initial={"return_url": request.get_full_path()},
            )
            action_url = reverse("wagtailcore_authenticate_with_password", args=[restriction.id, page.id])
            response = page.serve_password_required_response(request, form, action_url)
            add_never_cache_headers(response)
            return response
        if restriction.restriction_type in {PageViewRestriction.LOGIN, PageViewRestriction.GROUPS}:
            login_url = getattr(settings, "WAGTAIL_FRONTEND_LOGIN_URL", reverse("wagtailcore_login"))
            response = redirect_to_login(request.get_full_path(), login_url)
            add_never_cache_headers(response)
            return response
    return None


def _render_block(block):
    block_type = block.block_type
    value = block.value

    if block_type == "markdown":
        return str(value).strip()

    if block_type == "paragraph":
        html = getattr(value, "source", None)
        if html is None:
            html = str(value)
        return _html_to_text(html)

    if block_type == "heading":
        return f"## {_escape_tag_value(value)}"

    if block_type == "image":
        image_obj = _struct_value_get(value, "image", value)
        title = _escape_tag_value(getattr(image_obj, "title", "") or "")
        caption = _escape_tag_value(_struct_value_get(value, "caption", "") or "")
        return f"[Image; Title={title}; Caption={caption}]"

    if block_type == "code":
        language = _struct_value_get(value, "language", "") or ""
        code = _struct_value_get(value, "code", "") or ""
        return f"```{language}\n{code}\n```"

    if block_type == "raw_html":
        return _html_to_text(str(value))

    if block_type == "quote":
        text = str(value).strip()
        if not text:
            return ""
        return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())

    if block_type == "glossary":
        terms = _struct_value_get(value, "terms", []) or []
        auto_link = _struct_value_get(value, "auto_link", False)
        show_list = _struct_value_get(value, "show_list", False)
        header = (
            "[Glossary; auto_link="
            f"{'true' if auto_link else 'false'}; show_list={'true' if show_list else 'false'}]"
        )
        lines = [header]
        for entry in terms:
            term = _escape_tag_value(_struct_value_get(entry, "term", ""))
            definition = _escape_tag_value(_struct_value_get(entry, "definition", ""))
            aliases = _escape_tag_value(_struct_value_get(entry, "aliases", ""))
            if not term and not definition:
                continue
            if aliases:
                lines.append(f"- {term} ({aliases}): {definition}")
            else:
                lines.append(f"- {term}: {definition}")
        lines.append("[/Glossary]")
        return "\n".join(lines)

    if block_type == "takeaway":
        title = _escape_tag_value(_struct_value_get(value, "title", "") or "Key takeaway")
        color = _escape_tag_value(_struct_value_get(value, "color", "") or "blue")
        body = _escape_tag_value(_struct_value_get(value, "body", ""))
        return f"[Takeaway; title={title}; color={color}] {body}"

    if block_type == "applet_embed":
        title = _escape_tag_value(_struct_value_get(value, "title", ""))
        src = _escape_tag_value(_struct_value_get(value, "src", ""))
        lazy = "true" if _struct_value_get(value, "lazy_load", True) else "false"
        full_height = "true" if _struct_value_get(value, "use_full_height", False) else "false"
        raw_max_height = _struct_value_get(value, "max_height", "")
        max_height = _escape_tag_value(
            "" if raw_max_height in ("", None) else str(raw_max_height)
        )
        style = _escape_tag_value(_struct_value_get(value, "style_overrides", ""))
        return (
            "[Applet; "
            f"title={title}; src={src}; lazy_load={lazy}; full_height={full_height}; "
            f"max_height={max_height}; style={style}]"
        )

    if block_type == "collapsible":
        title = _escape_tag_value(_struct_value_get(value, "title", ""))
        category = _struct_value_get(value, "category", "") or "default"
        default_closed = "true" if not _struct_value_get(value, "open_by_default", False) else "false"
        inner = _render_blocks(_struct_value_get(value, "content", []))
        header = (
            f"[collapsible; title={title}; category={category}; "
            f"default_closed={default_closed}]"
        )
        footer = "[/collapsible]"
        if inner:
            return f"{header}\n{inner}\n{footer}"
        return f"{header}\n{footer}"

    return ""


def _render_blocks(blocks):
    parts = []
    for block in blocks:
        rendered = _render_block(block)
        if rendered:
            parts.append(rendered)
    return "\n\n".join(parts)


def blog_page_markdown(request, page_path):
    site = Site.find_for_request(request)
    if not site:
        raise Http404

    path_components = [component for component in page_path.split("/") if component]
    route_result = site.root_page.route(request, path_components)

    page = getattr(route_result, "page", None)
    if page is None and isinstance(route_result, tuple):
        page = route_result[0]

    if page is None:
        raise Http404

    specific = page.specific
    if not isinstance(specific, BlogPage):
        raise Http404

    restriction_response = _enforce_view_restrictions(
        request,
        specific,
        fail_closed=True,
    )
    if restriction_response is not None:
        return restriction_response

    body = _render_blocks(specific.body)
    title = specific.title or ""
    date = specific.date.isoformat() if specific.date else ""

    lines = []
    if title:
        lines.append(f"# {title}")
    if date:
        lines.append(f"*{date}*")
    if body:
        if lines:
            lines.append("")
        lines.append(body)

    content = "\n".join(lines).strip() + "\n"

    return HttpResponse(content, content_type="text/markdown; charset=utf-8")
