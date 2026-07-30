import html
import re
from urllib.parse import urlsplit, urlunsplit

from bleach import clean
from django.conf import settings

ALLOWED_TAGS = {
    "a",
    "abbr",
    "acronym",
    "b",
    "blockquote",
    "br",
    "button",
    "caption",
    "circle",
    "code",
    "col",
    "colgroup",
    "dd",
    "del",
    "desc",
    "details",
    "div",
    "dl",
    "dt",
    "ellipse",
    "em",
    "figcaption",
    "figure",
    "g",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "iframe",
    "img",
    "image",
    "ins",
    "li",
    "line",
    "nav",
    "ol",
    "p",
    "path",
    "polygon",
    "polyline",
    "pre",
    "rect",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "svg",
    "switch",
    "table",
    "tbody",
    "td",
    "text",
    "tfoot",
    "th",
    "thead",
    "title",
    "tr",
    "tspan",
    "tt",
    "u",
    "ul",
}

GLOBAL_ATTRIBUTES = {
    "class",
    "dir",
    "id",
    "lang",
    "role",
    "style",
    "title",
}

TAG_ATTRIBUTES = {
    "a": {"href", "rel"},
    "button": {"disabled", "name", "type", "value"},
    "details": {"open"},
    "iframe": {
        "allowfullscreen",
        "height",
        "loading",
        "referrerpolicy",
        "sandbox",
        "src",
        "width",
    },
    "img": {"alt", "decoding", "height", "loading", "src", "width"},
    "ol": {"reversed", "start", "type"},
    "svg": {
        "fill",
        "height",
        "preserveAspectRatio",
        "stroke",
        "version",
        "viewBox",
        "width",
        "xmlns",
    },
    "td": {"colspan", "headers", "rowspan"},
    "th": {"abbr", "colspan", "headers", "rowspan", "scope"},
}

SVG_ATTRIBUTES = {
    "cx",
    "cy",
    "d",
    "dx",
    "dy",
    "fill",
    "fill-opacity",
    "fill-rule",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "height",
    "href",
    "opacity",
    "points",
    "preserveAspectRatio",
    "r",
    "rx",
    "ry",
    "stroke",
    "stroke-dasharray",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-miterlimit",
    "stroke-opacity",
    "stroke-width",
    "text-anchor",
    "transform",
    "viewBox",
    "width",
    "x",
    "x1",
    "x2",
    "y",
    "y1",
    "y2",
}

SVG_TAGS = {
    "circle",
    "desc",
    "ellipse",
    "g",
    "line",
    "path",
    "polygon",
    "polyline",
    "rect",
    "svg",
    "image",
    "switch",
    "text",
    "title",
    "tspan",
}

ALLOWED_STYLES = {
    "align-items",
    "background",
    "background-color",
    "border",
    "border-bottom",
    "border-collapse",
    "border-color",
    "border-left",
    "border-radius",
    "border-right",
    "border-style",
    "border-top",
    "border-width",
    "color",
    "display",
    "fill",
    "filter",
    "flex",
    "flex-direction",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "gap",
    "height",
    "justify-content",
    "line-height",
    "margin",
    "margin-bottom",
    "margin-left",
    "margin-right",
    "margin-top",
    "max-height",
    "max-width",
    "min-height",
    "min-width",
    "opacity",
    "overflow",
    "padding",
    "padding-bottom",
    "padding-left",
    "padding-right",
    "padding-top",
    "stroke",
    "stroke-width",
    "text-align",
    "text-decoration",
    "vertical-align",
    "white-space",
    "width",
}

URL_ATTRIBUTES = {"href", "src", "xlink:href"}
DANGEROUS_CSS_PATTERN = re.compile(
    r"(?:@import|expression\s*\(|javascript\s*:|vbscript\s*:|"
    r"-moz-binding|behavior\s*:|url\s*\()",
    re.IGNORECASE,
)
ACTIVE_ELEMENT_PATTERN = re.compile(
    r"<(?P<tag>script|style)\b[^>]*>.*?(?:</(?P=tag)\s*>|$)",
    re.IGNORECASE | re.DOTALL,
)
FOREIGN_OBJECT_PATTERN = re.compile(
    r"<foreignObject\b[^>]*(?:/>|>.*?</foreignObject\s*>)",
    re.IGNORECASE | re.DOTALL,
)


def _remove_active_elements(value):
    without_active_elements = ACTIVE_ELEMENT_PATTERN.sub("", value)
    return FOREIGN_OBJECT_PATTERN.sub("", without_active_elements)


def _normalized_scheme(value):
    candidate = html.unescape(value or "").strip()
    collapsed = re.sub(r"[\x00-\x20\x7f]+", "", candidate)
    return urlsplit(collapsed).scheme.lower(), collapsed


def _safe_url(tag, name, value):
    scheme, collapsed = _normalized_scheme(value)
    if not collapsed:
        return False

    if tag == "image" and name == "href":
        return _is_canonical_imported_media_url(collapsed)

    if collapsed.startswith("#"):
        return name in {"href", "xlink:href"}

    if collapsed.startswith("//"):
        return False

    if scheme == "data":
        return False

    if tag == "iframe" and name == "src":
        return _canonical_iframe_url(collapsed) is not None

    if scheme:
        if name == "href":
            return scheme in {"http", "https", "mailto"}
        return scheme in {"http", "https"}

    return collapsed.startswith("/") or not collapsed.startswith(("\\", ".\\"))


def _is_canonical_imported_media_url(value):
    """Allow only opaque importer-owned media URLs inside SVG image nodes."""

    if "\\" in value:
        return False
    try:
        candidate = urlsplit(value)
        media_base = urlsplit(settings.MEDIA_URL)
        candidate_port = candidate.port
        media_port = media_base.port
    except ValueError:
        return False

    if candidate.username is not None or candidate.password is not None:
        return False
    if candidate.query or candidate.fragment:
        return False

    if media_base.scheme or media_base.netloc:
        if (
            candidate.scheme.lower() != media_base.scheme.lower()
            or (candidate.hostname or "").lower() != (media_base.hostname or "").lower()
            or candidate_port != media_port
        ):
            return False
    elif candidate.scheme or candidate.netloc:
        return False

    media_path = media_base.path.rstrip("/")
    expected_path = (
        rf"{re.escape(media_path)}/original_images/"
        r"ghost-[0-9a-f]{64}\.(?:gif|jpg|png|webp)"
    )
    return re.fullmatch(expected_path, candidate.path) is not None


def _canonical_iframe_url(value):
    """Return one browser-safe representation of an allowed iframe URL."""

    candidate = html.unescape(value or "").strip()
    if not candidate or "\\" in candidate:
        return None

    collapsed = re.sub(r"[\x00-\x20\x7f]+", "", candidate)
    try:
        parsed = urlsplit(collapsed)
        port = parsed.port
    except ValueError:
        return None

    hostname = (parsed.hostname or "").lower()
    allowed_hosts = {host.lower() for host in settings.ALLOWED_EMBED_HOSTS}
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None

    path = parsed.path or "/"
    return urlunsplit(("https", hostname, path, parsed.query, parsed.fragment))


def _allow_attribute(tag, name, value):
    lowered_name = name.lower()
    if lowered_name.startswith("on") or lowered_name == "srcset":
        return False
    if lowered_name.startswith("aria-") or lowered_name.startswith("data-"):
        return True

    allowed = (
        name in GLOBAL_ATTRIBUTES
        or name in TAG_ATTRIBUTES.get(tag, set())
        or (tag in SVG_TAGS and name in SVG_ATTRIBUTES)
    )
    if not allowed:
        return False

    if lowered_name == "style":
        return not DANGEROUS_CSS_PATTERN.search(html.unescape(value or ""))
    if tag in SVG_TAGS and DANGEROUS_CSS_PATTERN.search(html.unescape(value or "")):
        return False
    if lowered_name in URL_ATTRIBUTES:
        return _safe_url(tag, lowered_name, value)
    return True


def sanitize_structural_html(value):
    """Keep explicitly allowed document/SVG structure while removing executable HTML."""

    if not value:
        return ""
    prepared = _remove_active_elements(str(value))
    sanitized = clean(
        prepared,
        tags=ALLOWED_TAGS,
        attributes=_allow_attribute,
        styles=ALLOWED_STYLES,
        protocols=["http", "https", "mailto"],
        strip=True,
        strip_comments=True,
    )
    return _harden_iframes(sanitized)


IFRAME_PATTERN = re.compile(
    r"<iframe\b(?P<attributes>[^>]*)>(?P<body>.*?)</iframe\s*>",
    re.IGNORECASE | re.DOTALL,
)
ATTRIBUTE_PATTERN = re.compile(
    r"\s+(?P<name>[a-zA-Z][a-zA-Z0-9:-]*)"
    r"(?:=\"(?P<value>[^\"]*)\")?"
)


def _harden_iframes(value):
    def replace(match):
        attributes = {
            attribute.group("name").lower(): attribute.group("value")
            for attribute in ATTRIBUTE_PATTERN.finditer(match.group("attributes"))
        }
        source = attributes.get("src")
        canonical_source = _canonical_iframe_url(source)
        if canonical_source is None:
            return ""

        safe_attributes = [f'src="{html.escape(canonical_source, quote=True)}"']
        for name in ("title", "width", "height", "style"):
            attribute_value = attributes.get(name)
            if attribute_value:
                safe_attributes.append(f'{name}="{html.escape(attribute_value, quote=True)}"')
        if "allowfullscreen" in attributes:
            safe_attributes.append("allowfullscreen")
        safe_attributes.extend(
            [
                'loading="lazy"',
                'referrerpolicy="no-referrer"',
                'sandbox="allow-forms allow-popups allow-scripts"',
            ]
        )
        return f"<iframe {' '.join(safe_attributes)}></iframe>"

    return IFRAME_PATTERN.sub(replace, value)
