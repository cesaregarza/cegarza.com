import html
import re
from html.parser import HTMLParser

from django.template.loader import render_to_string

WORD_REGEX = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")
MATH_PATTERNS = [
    re.compile(r"\[latex\](.+?)\[/latex\]", re.DOTALL),
    re.compile(r"\$\$(.+?)\$\$", re.DOTALL),
    re.compile(r"\\\[(.+?)\\\]", re.DOTALL),
    re.compile(r"\\\((.+?)\\\)", re.DOTALL),
    re.compile(r"\$(.+?)\$", re.DOTALL),
]


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


def collect_glossary_terms(blocks):
    terms = {}
    auto_link = False

    def visit(items):
        nonlocal auto_link
        for block in items:
            block_type = getattr(block, "block_type", "")
            value = getattr(block, "value", None)
            if block_type == "glossary":
                auto_link = auto_link or bool(_struct_value_get(value, "auto_link", False))
                entries = _struct_value_get(value, "terms", []) or []
                for entry in entries:
                    term = (_struct_value_get(entry, "term", "") or "").strip()
                    definition = (_struct_value_get(entry, "definition", "") or "").strip()
                    if not term or not definition:
                        continue
                    key = term.lower()
                    terms[key] = {"term": term, "definition": definition}
                    aliases = (_struct_value_get(entry, "aliases", "") or "").split(",")
                    for alias in (a.strip() for a in aliases if a.strip()):
                        alias_key = alias.lower()
                        if alias_key not in terms:
                            terms[alias_key] = {"term": term, "definition": definition}
            elif block_type == "collapsible":
                content = _struct_value_get(value, "content", []) or []
                visit(content)

    visit(blocks)
    return terms, auto_link


class HeadingSlugger:
    def __init__(self):
        self.used_ids = set()

    def ensure(self, text, existing_id=None):
        if existing_id:
            existing_id = existing_id.strip()
            if existing_id and existing_id not in self.used_ids:
                self.used_ids.add(existing_id)
                return existing_id
            base = existing_id or "section"
        else:
            base = re.sub(r"[^a-z0-9\s-]", "", (text or "").lower()).strip()
            base = re.sub(r"\s+", "-", base)
            if not base:
                base = "section"
            base = f"h-{base}"

        candidate = base
        suffix = 2
        while candidate in self.used_ids:
            candidate = f"{base}-{suffix}"
            suffix += 1
        self.used_ids.add(candidate)
        return candidate


class PostProcessor(HTMLParser):
    def __init__(self, glossary_terms, auto_link):
        super().__init__(convert_charrefs=True)
        self.glossary_terms = glossary_terms or {}
        self.auto_link = bool(auto_link) and bool(self.glossary_terms)
        self.slugger = HeadingSlugger()
        self.toc_items = []
        self.output = []
        self.total_main_words = 0
        self.total_deep_words = 0
        self.collapsible_word_counts = []
        self._heading = None
        self._skip_depth = 0
        self._skip_stack = []
        self._details_stack = []
        self._summary_depth = 0
        self._div_table_wrapper_stack = []
        self._generated_table_wrapper_stack = []
        self._manual_pattern = re.compile(r"\[\[([^\]]+)\]\]")
        self._auto_pattern = self._build_auto_pattern()
        self._skip_tags = {
            "script",
            "style",
            "pre",
            "code",
            "a",
            "button",
            "nav",
        }
        self._skip_classes = {
            "glossary-data",
            "glossary-tooltip",
            "post-toc",
            "post-sidebar",
        }

    def _build_auto_pattern(self):
        if not self.auto_link:
            return None
        terms = [entry["term"] for entry in self.glossary_terms.values() if entry.get("term")]
        if not terms:
            return None
        unique = list(dict.fromkeys(terms))
        unique.sort(key=len, reverse=True)
        escaped = [re.escape(term) for term in unique]
        return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)

    def _write(self, text):
        if self._heading is not None:
            self._heading["buffer"].append(text)
        else:
            self.output.append(text)

    def _format_attrs(self, attrs):
        parts = []
        for key, value in attrs:
            if value is None:
                parts.append(key)
            else:
                parts.append(f'{key}="{html.escape(value, quote=True)}"')
        if not parts:
            return ""
        return " " + " ".join(parts)

    def _ensure_attr(self, attrs, key, value):
        for existing_key, _ in attrs:
            if existing_key == key:
                return attrs
        attrs.append((key, value))
        return attrs

    def _is_skip_tag(self, tag, attrs):
        if tag in self._skip_tags:
            return True
        class_attr = ""
        for key, value in attrs:
            if key == "class" and value:
                class_attr = value
                break
        if class_attr:
            classes = {c.strip() for c in class_attr.split()}
            if classes & self._skip_classes:
                return True
        return False

    def _count_words(self, text):
        if not text:
            return 0
        working = text
        math_words = 0
        for pattern in MATH_PATTERNS:
            while True:
                match = pattern.search(working)
                if not match:
                    break
                segment = match.group(1) or ""
                compact = re.sub(r"\s+", "", segment)
                if compact:
                    math_words += max(1, int((len(compact) + 7) / 8))
                working = working[: match.start()] + " " + working[match.end() :]
        word_count = len(WORD_REGEX.findall(working))
        return word_count + math_words

    def _linkify_text(self, text):
        if not text:
            return ""
        segments = []
        last = 0
        for match in self._manual_pattern.finditer(text):
            start, end = match.span()
            if start > last:
                segments.append(("text", text[last:start]))
            raw = match.group(1).strip()
            if raw:
                parts = raw.split("|", 1)
                term_raw = parts[0].strip()
                label_raw = parts[1].strip() if len(parts) > 1 else ""
                key = term_raw.lower()
                entry = self.glossary_terms.get(key)
                if entry:
                    label = label_raw or entry["term"]
                    segments.append(("glossary", (label, key, entry["definition"])))
                else:
                    segments.append(("text", match.group(0)))
            else:
                segments.append(("text", match.group(0)))
            last = end
        if last < len(text):
            segments.append(("text", text[last:]))

        output = []
        for kind, payload in segments:
            if kind == "glossary":
                label, key, definition = payload
                output.append(self._glossary_button(label, key, definition))
                continue
            chunk = payload
            if self._auto_pattern:
                output.append(self._auto_linkify_chunk(chunk))
            else:
                output.append(html.escape(chunk))
        return "".join(output)

    def _auto_linkify_chunk(self, text):
        if not text or not self._auto_pattern:
            return html.escape(text or "")
        output = []
        last = 0
        for match in self._auto_pattern.finditer(text):
            start, end = match.span()
            if start > last:
                output.append(html.escape(text[last:start]))
            term_match = match.group(1)
            key = term_match.lower()
            entry = self.glossary_terms.get(key)
            if entry:
                output.append(self._glossary_button(term_match, key, entry["definition"]))
            else:
                output.append(html.escape(term_match))
            last = end
        if last < len(text):
            output.append(html.escape(text[last:]))
        return "".join(output)

    def _glossary_button(self, label, key, definition):
        safe_label = html.escape(label)
        safe_key = html.escape(key, quote=True)
        safe_def = html.escape(definition, quote=True)
        return (
            f'<button type="button" class="glossary-term" data-term-key="{safe_key}" '
            f'title="{safe_def}">{safe_label}</button>'
        )

    def handle_starttag(self, tag, attrs):
        skip_tag = self._is_skip_tag(tag, attrs)
        self._skip_stack.append(skip_tag)
        if skip_tag:
            self._skip_depth += 1
        attrs = list(attrs)
        if tag == "div":
            class_attr = next((value or "" for key, value in attrs if key == "class"), "")
            is_table_wrapper = "table-wrapper" in class_attr.split()
            self._div_table_wrapper_stack.append(is_table_wrapper)
            if is_table_wrapper:
                self._ensure_attr(attrs, "role", "region")
                self._ensure_attr(attrs, "aria-label", "Scrollable data table")
                self._ensure_attr(attrs, "tabindex", "0")
        if tag == "table":
            needs_wrapper = not any(self._div_table_wrapper_stack)
            self._generated_table_wrapper_stack.append(needs_wrapper)
            if needs_wrapper:
                self._write(
                    '<div class="table-wrapper" role="region" '
                    'aria-label="Scrollable data table" tabindex="0">'
                )
        if tag == "img":
            self._ensure_attr(attrs, "loading", "lazy")
            self._ensure_attr(attrs, "decoding", "async")
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._heading is None:
            self._heading = {"tag": tag, "attrs": list(attrs), "buffer": [], "text": []}
            return
        if tag == "details":
            is_collapsible = False
            open_attr = False
            class_attr = ""
            for key, value in attrs:
                if key == "class" and value:
                    class_attr = value
                if key == "open":
                    open_attr = True
            if class_attr and "collapsible-block" in class_attr.split():
                is_collapsible = True
            if is_collapsible:
                self._details_stack.append({"open": open_attr, "words": 0})
        if tag == "summary" and self._details_stack:
            self._summary_depth += 1
        self._write(f"<{tag}{self._format_attrs(attrs)}>")

    def handle_endtag(self, tag):
        if self._heading is not None and tag == self._heading["tag"]:
            heading = self._heading
            text = "".join(heading["text"]).strip()
            attrs = heading["attrs"]
            existing_id = None
            filtered_attrs = []
            for key, value in attrs:
                if key == "id":
                    existing_id = value
                else:
                    filtered_attrs.append((key, value))
            heading_id = self.slugger.ensure(text, existing_id)
            filtered_attrs.append(("id", heading_id))
            start_tag = f"<{tag}{self._format_attrs(filtered_attrs)}>"
            inner = "".join(heading["buffer"])
            self.output.append(f"{start_tag}{inner}</{tag}>")
            level = tag
            if level in {"h1", "h2", "h3"} and text:
                self.toc_items.append({"id": heading_id, "text": text, "level": level})
            self._heading = None
            if self._skip_stack:
                if self._skip_stack.pop():
                    self._skip_depth = max(0, self._skip_depth - 1)
            return
        self._write(f"</{tag}>")
        if tag == "table" and self._generated_table_wrapper_stack:
            if self._generated_table_wrapper_stack.pop():
                self._write("</div>")
        if tag == "div" and self._div_table_wrapper_stack:
            self._div_table_wrapper_stack.pop()
        if tag == "summary" and self._summary_depth > 0:
            self._summary_depth -= 1
        if tag == "details" and self._details_stack:
            details = self._details_stack.pop()
            self.collapsible_word_counts.append(details["words"])
        if self._skip_stack:
            if self._skip_stack.pop():
                self._skip_depth = max(0, self._skip_depth - 1)

    def handle_startendtag(self, tag, attrs):
        skip_tag = self._is_skip_tag(tag, attrs)
        if skip_tag:
            self._skip_depth += 1
        attrs = list(attrs)
        if tag == "img":
            self._ensure_attr(attrs, "loading", "lazy")
            self._ensure_attr(attrs, "decoding", "async")
        self._write(f"<{tag}{self._format_attrs(attrs)} />")
        if skip_tag:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data):
        if data is None:
            return
        word_count = self._count_words(data) if self._skip_depth == 0 else 0
        if self._summary_depth == 0 and word_count and self._details_stack:
            for details in self._details_stack:
                details["words"] += word_count
        if word_count:
            self.total_deep_words += word_count
            if not any(not details["open"] for details in self._details_stack) or self._summary_depth > 0:
                self.total_main_words += word_count
        if self._heading is not None:
            self._heading["buffer"].append(html.escape(data))
            self._heading["text"].append(data)
            return
        if self._skip_depth > 0:
            self._write(html.escape(data))
            return
        self._write(self._linkify_text(data))

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")

    def handle_comment(self, data):
        self._write(f"<!--{data}-->")


def format_minutes(words, words_per_minute=220):
    minutes = max(1, round(words / words_per_minute))
    return f"{minutes} min"


def inject_collapsible_readtimes(html_text, word_counts):
    if not word_counts:
        return html_text
    counts = list(word_counts)

    def repl(match):
        if not counts:
            return match.group(0)
        words = counts.pop(0)
        return f"{match.group(1)}{format_minutes(words)}{match.group(3)}"

    pattern = re.compile(
        r"(<span[^>]*data-collapsible-readtime[^>]*>)(.*?)(</span>)",
        re.DOTALL,
    )
    return pattern.sub(repl, html_text)


def build_toc_hierarchy(toc_items):
    items = []
    current_h1 = None
    current_h2 = None
    for entry in toc_items:
        level = entry["level"]
        item = {
            "id": entry["id"],
            "text": entry["text"],
            "level": level,
            "parent_id": "",
            "grandparent_id": "",
        }
        if level == "h1":
            current_h1 = entry
            current_h2 = None
        elif level == "h2":
            item["parent_id"] = current_h1["id"] if current_h1 else ""
            current_h2 = entry
        elif level == "h3":
            item["parent_id"] = current_h2["id"] if current_h2 else ""
            item["grandparent_id"] = current_h1["id"] if current_h1 else ""
        items.append(item)
    return items


# KaTeX auto-render delimiters (mirrors static/js/katex-init.js). Used to decide
# whether a page needs the KaTeX bundle so it is not loaded site-wide.
_MATH_DELIMITERS = ("\\(", "$$", "\\[", "[latex]")


def text_has_math(text):
    """True when a string contains a KaTeX math delimiter."""
    if not text:
        return False
    return any(delimiter in text for delimiter in _MATH_DELIMITERS)


# Backwards-compatible alias for callers that pass rendered HTML.
html_has_math = text_has_math


def body_has_math(body):
    """True when a StreamField body's *source* contains KaTeX math delimiters.

    Detection runs against the raw block source (StreamField ``raw_data``) rather
    than rendered HTML, because Markdown consumes ``\\(``/``\\)`` escapes before
    they reach the DOM: an author who writes inline ``\\(x\\)`` in a markdown block
    must still get KaTeX loaded. Used by the cache-hit render path, where the
    ``math_present`` flag is not a persisted column and must be recomputed
    without re-rendering.
    """
    if not body:
        return False
    raw_data = getattr(body, "raw_data", None)
    if raw_data is None:
        raw_data = body
    for entry in raw_data:
        value = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(value, dict):
            value = " ".join(str(part) for part in value.values())
        if text_has_math(str(value)):
            return True
    return False


def render_blog_body(body):
    if not body:
        return {
            "body_html": "",
            "toc_items": [],
            "toc_crumb": "",
            "readtime_main": format_minutes(0),
            "readtime_deep": format_minutes(0),
            "math_present": False,
        }
    glossary_terms, auto_link = collect_glossary_terms(body)
    blocks_html = []
    for block in body:
        blocks_html.append(render_to_string("blog/blocks/render_block.html", {"block": block}))
    raw_html = "\n".join(blocks_html)
    math_present = body_has_math(body)

    processor = PostProcessor(glossary_terms, auto_link)
    processor.feed(raw_html)
    processor.close()
    html_out = "".join(processor.output)
    html_out = inject_collapsible_readtimes(html_out, processor.collapsible_word_counts)
    toc_items = build_toc_hierarchy(processor.toc_items)
    return {
        "body_html": html_out,
        "toc_items": toc_items,
        "toc_crumb": toc_items[0]["text"] if toc_items else "",
        "readtime_main": format_minutes(processor.total_main_words),
        "readtime_deep": format_minutes(processor.total_deep_words),
        "math_present": math_present,
    }
