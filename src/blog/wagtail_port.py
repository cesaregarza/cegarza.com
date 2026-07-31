from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import secrets
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.dateparse import parse_datetime
from PIL import Image as PillowImage
from PIL import ImageSequence, UnidentifiedImageError
from wagtail.images import get_image_model
from wagtail.models import Page, PageViewRestriction, Site

from blog.ghost_import import _open_bounded_tar_archive
from blog.models import (
    APPLET_CATALOG,
    BlogIndexPage,
    BlogPage,
    WagtailImageImport,
    WagtailPageImport,
)

SCHEMA_VERSION = 1
MAX_BUNDLE_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_PAGES = 100
MAX_IMAGES = 200
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 96 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_TOTAL_IMAGE_PIXELS = 160_000_000
MAX_IMAGE_FRAMES = 500
COPY_CHUNK_BYTES = 1024 * 1024
NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
SLUG_PATTERN = re.compile(r"^[-a-zA-Z0-9_]+$")
REFERENCE_TAG_PATTERN = re.compile(r"<(?:embed|a)\b[^>]*>", re.IGNORECASE)
ID_ATTRIBUTE_PATTERN = re.compile(r"\bid=(?P<quote>[\"'])(?P<id>\d+)(?P=quote)")
APPLET_PATHS = {f"/static/{entry['path']}" for entry in APPLET_CATALOG}
SNAPSHOT_KEYS = {
    "abstract",
    "body",
    "date",
    "featured_image_id",
    "is_featured",
    "search_description",
    "seo_title",
    "show_in_menus",
    "slug",
    "social_image_id",
    "title",
}
PAGE_KEYS = {
    "draft",
    "first_published_at",
    "last_published_at",
    "live",
    "restriction",
    "source_page_id",
}
IMAGE_KEYS = {
    "filename",
    "height",
    "member",
    "sha256",
    "size",
    "source_image_id",
    "source_name",
    "source_urls",
    "title",
    "width",
}
MANIFEST_KEYS = {
    "exported_at",
    "images",
    "pages",
    "schema_version",
    "source_index_page_id",
    "source_namespace",
}
SENSITIVE_KEY_PARTS = ("password", "secret", "token", "credential")


class WagtailPortError(ValueError):
    pass


@dataclass(frozen=True)
class ImagePayload:
    source_image_id: int
    filename: str
    member: str
    source_name: str
    source_urls: tuple[str, ...]
    title: str
    source_sha256: str
    data: bytes
    width: int
    height: int
    pixel_count: int


@dataclass
class PortSummary:
    pages: int = 0
    images: int = 0
    created_pages: int = 0
    updated_pages: int = 0
    unchanged_pages: int = 0
    created_images: int = 0
    unchanged_images: int = 0
    restricted_pages: int = 0
    draft_pages: int = 0
    dry_run: bool = False

    def as_dict(self):
        return {
            "pages": self.pages,
            "images": self.images,
            "created_pages": self.created_pages,
            "updated_pages": self.updated_pages,
            "unchanged_pages": self.unchanged_pages,
            "created_images": self.created_images,
            "unchanged_images": self.unchanged_images,
            "restricted_pages": self.restricted_pages,
            "draft_pages": self.draft_pages,
            "dry_run": self.dry_run,
        }


def _canonical_json(payload) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def snapshot_sha256(snapshot) -> str:
    return hashlib.sha256(_canonical_json(snapshot)).hexdigest()


def _validate_exact_keys(payload, allowed_keys, label):
    if not isinstance(payload, dict):
        raise WagtailPortError(f"{label} must be a JSON object.")
    unexpected = sorted(set(payload) - allowed_keys)
    if unexpected:
        raise WagtailPortError(f"{label} has unsupported fields: {', '.join(unexpected)}.")


def _reject_sensitive_keys(payload, path="manifest"):
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                raise WagtailPortError(f"{path} contains a forbidden sensitive field.")
            _reject_sensitive_keys(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _reject_sensitive_keys(value, f"{path}[{index}]")


def _read_member(archive, member, *, limit, label):
    if member.size < 0 or member.size > limit:
        raise WagtailPortError(f"{label} exceeds the {limit}-byte limit.")
    extracted = archive.extractfile(member)
    if extracted is None:
        raise WagtailPortError(f"Cannot read {label}.")
    data = extracted.read(limit + 1)
    if len(data) != member.size:
        raise WagtailPortError(f"{label} size changed while reading.")
    if len(data) > limit:
        raise WagtailPortError(f"{label} exceeds the {limit}-byte limit.")
    return data


def _file_sha256(path, *, expected_size):
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as bundle_file:
            while True:
                chunk = bundle_file.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_size:
                    raise WagtailPortError(
                        "Wagtail port bundle changed while hashing."
                    )
                digest.update(chunk)
    except OSError as exc:
        raise WagtailPortError("Cannot read the Wagtail port bundle.") from exc
    if total != expected_size:
        raise WagtailPortError("Wagtail port bundle changed while hashing.")
    return digest.hexdigest()


def _validate_member_name(name):
    if len(name.encode("utf-8")) > 1024:
        raise WagtailPortError("Bundle member path is too long.")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or not path.parts
        or "." in path.parts
        or ".." in path.parts
        or path.as_posix() != name
    ):
        raise WagtailPortError("Bundle contains an unsafe member path.")


def _validate_image_bytes(name, data, expected_width, expected_height):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise WagtailPortError(f"Image {name} has an invalid size.")
    try:
        with PillowImage.open(io.BytesIO(data)) as image:
            frame_count = int(getattr(image, "n_frames", 1))
            if frame_count < 1 or frame_count > MAX_IMAGE_FRAMES:
                raise WagtailPortError(
                    f"Image {name} exceeds the {MAX_IMAGE_FRAMES}-frame limit."
                )
            pixel_count = 0
            first_size = None
            for frame in ImageSequence.Iterator(image):
                width, height = frame.size
                if width < 1 or height < 1:
                    raise WagtailPortError(f"Image {name} has invalid dimensions.")
                pixel_count += width * height
                if pixel_count > MAX_IMAGE_PIXELS:
                    raise WagtailPortError(
                        f"Image {name} exceeds the {MAX_IMAGE_PIXELS}-pixel limit."
                    )
                if first_size is None:
                    first_size = (width, height)
                frame.load()
    except WagtailPortError:
        raise
    except (
        EOFError,
        OSError,
        PillowImage.DecompressionBombError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        raise WagtailPortError(f"Image {name} is not a valid supported image.") from exc
    if first_size != (expected_width, expected_height):
        raise WagtailPortError(f"Image {name} dimensions do not match the manifest.")
    return pixel_count


def _parse_positive_int(value, label):
    if isinstance(value, bool):
        raise WagtailPortError(f"{label} must be a positive integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise WagtailPortError(f"{label} must be a positive integer.") from exc
    if parsed < 1 or parsed != value:
        raise WagtailPortError(f"{label} must be a positive integer.")
    return parsed


def _validate_timestamp(value, label, *, required):
    if value is None and not required:
        return None
    if not isinstance(value, str) or parse_datetime(value) is None:
        raise WagtailPortError(f"{label} must be an ISO-8601 timestamp.")
    return value


def _validate_snapshot(snapshot, label):
    _validate_exact_keys(snapshot, SNAPSHOT_KEYS, label)
    if not isinstance(snapshot.get("title"), str) or not snapshot["title"].strip():
        raise WagtailPortError(f"{label}.title is required.")
    if len(snapshot["title"]) > 255:
        raise WagtailPortError(f"{label}.title is too long.")
    slug = snapshot.get("slug")
    if (
        not isinstance(slug, str)
        or not slug
        or len(slug) > 255
        or not SLUG_PATTERN.fullmatch(slug)
    ):
        raise WagtailPortError(f"{label}.slug is invalid.")
    for field_name in ("seo_title", "search_description", "abstract"):
        if not isinstance(snapshot.get(field_name), str):
            raise WagtailPortError(f"{label}.{field_name} must be text.")
    if len(snapshot["seo_title"]) > 255 or len(snapshot["search_description"]) > 255:
        raise WagtailPortError(f"{label} contains oversized SEO text.")
    if not isinstance(snapshot.get("show_in_menus"), bool):
        raise WagtailPortError(f"{label}.show_in_menus must be boolean.")
    if not isinstance(snapshot.get("is_featured"), bool):
        raise WagtailPortError(f"{label}.is_featured must be boolean.")
    if snapshot.get("date") is not None:
        try:
            date.fromisoformat(snapshot["date"])
        except (TypeError, ValueError) as exc:
            raise WagtailPortError(f"{label}.date must be an ISO date.") from exc
    if not isinstance(snapshot.get("body"), list):
        raise WagtailPortError(f"{label}.body must be a StreamField list.")
    for field_name in ("featured_image_id", "social_image_id"):
        value = snapshot.get(field_name)
        if value is not None:
            _parse_positive_int(value, f"{label}.{field_name}")

    body_field = BlogPage._meta.get_field("body")
    try:
        body_field.stream_block.to_python(copy.deepcopy(snapshot["body"]))
    except Exception as exc:
        raise WagtailPortError(f"{label}.body failed StreamField validation.") from exc
    allowed_block_types = set(body_field.stream_block.child_blocks)
    for block_type, _value in _iter_stream_blocks(snapshot["body"]):
        if block_type not in allowed_block_types:
            raise WagtailPortError(
                f"{label}.body contains unsupported block type {block_type!r}."
            )


def _iter_stream_blocks(blocks):
    for block in blocks:
        if not isinstance(block, dict):
            raise WagtailPortError("StreamField blocks must be objects.")
        block_type = block.get("type")
        value = block.get("value")
        yield block_type, value
        if block_type == "collapsible":
            if not isinstance(value, dict) or not isinstance(value.get("content"), list):
                raise WagtailPortError("Collapsible content must be a StreamField list.")
            yield from _iter_stream_blocks(value["content"])


def _tag_reference_ids(text):
    image_ids = set()
    page_ids = set()
    for match in REFERENCE_TAG_PATTERN.finditer(text):
        tag = match.group(0)
        id_match = ID_ATTRIBUTE_PATTERN.search(tag)
        if not id_match:
            continue
        reference_id = int(id_match.group("id"))
        lowered = tag.lower()
        if "embedtype=\"image\"" in lowered or "embedtype='image'" in lowered:
            image_ids.add(reference_id)
        elif "linktype=\"page\"" in lowered or "linktype='page'" in lowered:
            page_ids.add(reference_id)
    return image_ids, page_ids


def _snapshot_references(snapshot):
    image_ids = {
        value
        for value in (
            snapshot.get("featured_image_id"),
            snapshot.get("social_image_id"),
        )
        if value is not None
    }
    page_ids = set()
    applet_paths = set()
    text_values = []
    for block_type, value in _iter_stream_blocks(snapshot["body"]):
        if block_type == "image":
            if not isinstance(value, dict):
                raise WagtailPortError("Image blocks must use structured values.")
            image_ids.add(_parse_positive_int(value.get("image"), "image block ID"))
        elif block_type == "applet_embed":
            if not isinstance(value, dict) or not isinstance(value.get("src"), str):
                raise WagtailPortError("Applet blocks require a source path.")
            applet_paths.add(value["src"])
        elif isinstance(value, str):
            text_values.append(value)
    for value in text_values:
        tag_image_ids, tag_page_ids = _tag_reference_ids(value)
        image_ids.update(tag_image_ids)
        page_ids.update(tag_page_ids)
    return image_ids, page_ids, applet_paths


def _validate_page_entry(entry, image_ids, page_ids, source_index_page_id):
    _validate_exact_keys(entry, PAGE_KEYS, "page")
    source_page_id = _parse_positive_int(entry.get("source_page_id"), "source_page_id")
    live = entry.get("live")
    if not isinstance(live, dict) or set(live) != {"sha256", "snapshot"}:
        raise WagtailPortError("page.live must contain only sha256 and snapshot.")
    _validate_snapshot(live["snapshot"], f"page {source_page_id} live")
    if live["sha256"] != snapshot_sha256(live["snapshot"]):
        raise WagtailPortError(f"Page {source_page_id} live hash does not match.")

    draft = entry.get("draft")
    if draft is not None:
        if not isinstance(draft, dict) or set(draft) != {"sha256", "snapshot"}:
            raise WagtailPortError("page.draft must contain only sha256 and snapshot.")
        _validate_snapshot(draft["snapshot"], f"page {source_page_id} draft")
        if draft["sha256"] != snapshot_sha256(draft["snapshot"]):
            raise WagtailPortError(f"Page {source_page_id} draft hash does not match.")
        if draft["sha256"] == live["sha256"]:
            raise WagtailPortError(f"Page {source_page_id} draft duplicates its live state.")

    restriction = entry.get("restriction")
    if not isinstance(restriction, dict) or set(restriction) != {"type"}:
        raise WagtailPortError("page.restriction must contain only type.")
    if restriction["type"] not in {"none", "password"}:
        raise WagtailPortError("Only none and password page restrictions are supported.")

    if not isinstance(entry.get("first_published_at"), str):
        raise WagtailPortError("Live pages require first_published_at.")
    _validate_timestamp(
        entry["first_published_at"],
        "first_published_at",
        required=True,
    )
    _validate_timestamp(
        entry.get("last_published_at"),
        "last_published_at",
        required=True,
    )

    for state_name in ("live", "draft"):
        state = entry.get(state_name)
        if state is None:
            continue
        referenced_images, referenced_pages, applet_paths = _snapshot_references(
            state["snapshot"]
        )
        missing_images = sorted(referenced_images - image_ids)
        if missing_images:
            raise WagtailPortError(
                f"Page {source_page_id} references missing source images: {missing_images}."
            )
        allowed_pages = page_ids | {source_index_page_id}
        missing_pages = sorted(referenced_pages - allowed_pages)
        if missing_pages:
            raise WagtailPortError(
                f"Page {source_page_id} references unmapped source pages: {missing_pages}."
            )
        unknown_applets = sorted(applet_paths - APPLET_PATHS)
        if unknown_applets:
            raise WagtailPortError(
                f"Page {source_page_id} references unknown applets: {unknown_applets}."
            )
        for applet_path in applet_paths:
            if finders.find(applet_path.removeprefix("/static/")) is None:
                raise WagtailPortError(
                    f"Page {source_page_id} applet asset is not installed: {applet_path}."
                )
    return source_page_id


def load_wagtail_bundle(
    bundle_path,
    *,
    expected_namespace=None,
    expected_sha256=None,
):
    path = Path(bundle_path)
    try:
        bundle_size = path.stat().st_size
    except OSError as exc:
        raise WagtailPortError("Cannot read the Wagtail port bundle.") from exc
    if bundle_size < 1 or bundle_size > MAX_BUNDLE_BYTES:
        raise WagtailPortError("Wagtail port bundle has an invalid compressed size.")
    if (
        not isinstance(expected_sha256, str)
        or SHA256_PATTERN.fullmatch(expected_sha256) is None
    ):
        raise WagtailPortError("A valid pinned bundle SHA-256 is required.")
    if _file_sha256(path, expected_size=bundle_size) != expected_sha256:
        raise WagtailPortError("Wagtail port bundle SHA-256 does not match the pin.")

    try:
        archive_context = _open_bounded_tar_archive(path)
        with archive_context as archive:
            members = archive.getmembers()
            by_name = {}
            for member in members:
                _validate_member_name(member.name)
                if not member.isfile():
                    raise WagtailPortError("Bundle members must be regular files.")
                if member.name in by_name:
                    raise WagtailPortError("Bundle contains duplicate member names.")
                by_name[member.name] = member
            manifest_member = by_name.get("manifest.json")
            if manifest_member is None:
                raise WagtailPortError("Bundle is missing manifest.json.")
            manifest_bytes = _read_member(
                archive,
                manifest_member,
                limit=MAX_MANIFEST_BYTES,
                label="manifest.json",
            )
            try:
                manifest = json.loads(manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WagtailPortError("Bundle manifest is not valid UTF-8 JSON.") from exc

            _validate_exact_keys(manifest, MANIFEST_KEYS, "manifest")
            _reject_sensitive_keys(manifest)
            if manifest.get("schema_version") != SCHEMA_VERSION:
                raise WagtailPortError("Unsupported Wagtail port schema version.")
            namespace = manifest.get("source_namespace")
            if not isinstance(namespace, str) or not NAMESPACE_PATTERN.fullmatch(namespace):
                raise WagtailPortError("source_namespace is invalid.")
            if expected_namespace is not None and namespace != expected_namespace:
                raise WagtailPortError("Bundle source_namespace does not match the pinned value.")
            _validate_timestamp(manifest.get("exported_at"), "exported_at", required=True)
            source_index_page_id = _parse_positive_int(
                manifest.get("source_index_page_id"),
                "source_index_page_id",
            )

            image_entries = manifest.get("images")
            page_entries = manifest.get("pages")
            if not isinstance(image_entries, list) or len(image_entries) > MAX_IMAGES:
                raise WagtailPortError("Bundle image inventory is invalid or too large.")
            if (
                not isinstance(page_entries, list)
                or not page_entries
                or len(page_entries) > MAX_PAGES
            ):
                raise WagtailPortError("Bundle page inventory is invalid or too large.")

            image_payloads = {}
            total_image_bytes = 0
            total_image_pixels = 0
            expected_members = {"manifest.json"}
            for entry in image_entries:
                _validate_exact_keys(entry, IMAGE_KEYS, "image")
                source_image_id = _parse_positive_int(
                    entry.get("source_image_id"),
                    "source_image_id",
                )
                if source_image_id in image_payloads:
                    raise WagtailPortError("Bundle contains duplicate source image IDs.")
                sha256 = entry.get("sha256")
                if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
                    raise WagtailPortError("Image SHA-256 is invalid.")
                size = _parse_positive_int(entry.get("size"), "image size")
                width = _parse_positive_int(entry.get("width"), "image width")
                height = _parse_positive_int(entry.get("height"), "image height")
                member_name = entry.get("member")
                filename = entry.get("filename")
                if (
                    not isinstance(filename, str)
                    or PurePosixPath(filename).name != filename
                    or len(filename) > 255
                ):
                    raise WagtailPortError("Image filename is invalid.")
                expected_member = f"media/{source_image_id}/{sha256}/{filename}"
                if member_name != expected_member:
                    raise WagtailPortError("Image member path is not canonical.")
                member = by_name.get(member_name)
                if member is None:
                    raise WagtailPortError("Bundle is missing an image member.")
                data = _read_member(
                    archive,
                    member,
                    limit=MAX_IMAGE_BYTES,
                    label=f"image {source_image_id}",
                )
                if size != len(data) or hashlib.sha256(data).hexdigest() != sha256:
                    raise WagtailPortError(
                        f"Image {source_image_id} size or hash does not match."
                    )
                pixel_count = _validate_image_bytes(
                    filename,
                    data,
                    width,
                    height,
                )
                total_image_bytes += len(data)
                total_image_pixels += pixel_count
                if total_image_bytes > MAX_TOTAL_IMAGE_BYTES:
                    raise WagtailPortError("Bundle images exceed the aggregate byte limit.")
                if total_image_pixels > MAX_TOTAL_IMAGE_PIXELS:
                    raise WagtailPortError("Bundle images exceed the aggregate pixel limit.")
                source_urls = entry.get("source_urls")
                if (
                    not isinstance(source_urls, list)
                    or len(source_urls) > 8
                    or any(not isinstance(url, str) or len(url) > 2048 for url in source_urls)
                ):
                    raise WagtailPortError("Image source_urls are invalid.")
                for field_name in ("source_name", "title"):
                    if not isinstance(entry.get(field_name), str):
                        raise WagtailPortError(f"Image {field_name} must be text.")
                image_payloads[source_image_id] = ImagePayload(
                    source_image_id=source_image_id,
                    filename=filename,
                    member=member_name,
                    source_name=entry["source_name"],
                    source_urls=tuple(source_urls),
                    title=entry["title"][:255],
                    source_sha256=sha256,
                    data=data,
                    width=width,
                    height=height,
                    pixel_count=pixel_count,
                )
                expected_members.add(member_name)

            if set(by_name) != expected_members:
                raise WagtailPortError("Bundle contains unreferenced members.")

            source_page_ids = {
                _parse_positive_int(entry.get("source_page_id"), "source_page_id")
                for entry in page_entries
                if isinstance(entry, dict)
            }
            if len(source_page_ids) != len(page_entries):
                raise WagtailPortError("Bundle contains duplicate source page IDs.")
            slugs = set()
            for entry in page_entries:
                source_page_id = _validate_page_entry(
                    entry,
                    set(image_payloads),
                    source_page_ids,
                    source_index_page_id,
                )
                slug = entry["live"]["snapshot"]["slug"]
                if slug in slugs:
                    raise WagtailPortError("Bundle contains duplicate page slugs.")
                slugs.add(slug)
                if source_page_id == source_index_page_id:
                    raise WagtailPortError("Source index cannot also be a content page.")
    except WagtailPortError:
        raise
    except Exception as exc:
        raise WagtailPortError("Cannot read the Wagtail port bundle.") from exc

    return manifest, image_payloads


def _find_site_index(hostname, port):
    if not hostname or "/" in hostname:
        raise WagtailPortError("A valid destination hostname is required.")
    if not 1 <= int(port) <= 65535:
        raise WagtailPortError("Destination port must be between 1 and 65535.")
    try:
        site = Site.objects.get(hostname=hostname, port=port)
    except Site.DoesNotExist as exc:
        raise WagtailPortError("Destination Wagtail site does not exist.") from exc
    root = site.root_page.specific
    if isinstance(root, BlogIndexPage):
        return site, root
    indexes = list(BlogIndexPage.objects.descendant_of(root, inclusive=True))
    if len(indexes) != 1:
        raise WagtailPortError("Destination site must contain exactly one blog index.")
    return site, indexes[0]


def _body_prep_value(body):
    return copy.deepcopy(body.stream_block.get_prep_value(body))


def snapshot_from_page(page):
    return {
        "title": page.title,
        "slug": page.slug,
        "seo_title": page.seo_title or "",
        "search_description": page.search_description or "",
        "show_in_menus": bool(page.show_in_menus),
        "date": page.date.isoformat() if page.date else None,
        "is_featured": bool(page.is_featured),
        "abstract": page.abstract or "",
        "body": _body_prep_value(page.body),
        "featured_image_id": page.featured_image_id,
        "social_image_id": page.social_image_id,
    }


def _revision_snapshot(revision):
    if revision is None:
        return None
    return snapshot_from_page(revision.as_object().specific)


def _stored_file_sha256(file_field):
    digest = hashlib.sha256()
    total = 0
    with file_field.storage.open(file_field.name, "rb") as stored_file:
        while True:
            chunk = stored_file.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), total


def _preflight_images(namespace, image_payloads):
    for source_image_id, payload in sorted(image_payloads.items()):
        mapping = (
            WagtailImageImport.objects.select_related("image")
            .filter(
                source_namespace=namespace,
                source_image_id=source_image_id,
            )
            .first()
        )
        if mapping is None:
            _image, storage, expected_name = _stable_image_storage_target(
                namespace,
                payload,
            )
            if storage.exists(expected_name) and not _storage_matches(
                storage,
                expected_name,
                payload,
            ):
                raise WagtailPortError(
                    f"Stable image target has unexpected bytes: {expected_name}."
                )
            continue
        if mapping.source_sha256 != payload.source_sha256:
            raise WagtailPortError(
                f"Source image {source_image_id} changed after its first import."
            )
        if not mapping.image.file.storage.exists(mapping.image.file.name):
            raise WagtailPortError(f"Imported image {source_image_id} is missing.")
        actual_hash, actual_size = _stored_file_sha256(mapping.image.file)
        if actual_hash != mapping.stored_sha256 or actual_size != len(payload.data):
            raise WagtailPortError(f"Imported image {source_image_id} drifted.")


def _actual_page_hashes(page):
    page = BlogPage.objects.get(pk=page.pk)
    live_snapshot = _revision_snapshot(page.live_revision)
    if live_snapshot is None:
        return "", ""
    live_hash = snapshot_sha256(live_snapshot)
    latest = page.get_latest_revision()
    draft_hash = ""
    if latest and (page.live_revision_id is None or latest.pk != page.live_revision_id):
        draft_hash = snapshot_sha256(_revision_snapshot(latest))
    return live_hash, draft_hash


def _restriction_type(page):
    restrictions = list(PageViewRestriction.objects.filter(page=page))
    if not restrictions:
        return "none"
    if len(restrictions) != 1:
        raise WagtailPortError(f"Destination page {page.pk} has multiple restrictions.")
    if restrictions[0].restriction_type != PageViewRestriction.PASSWORD:
        raise WagtailPortError(f"Destination page {page.pk} has an unsupported restriction.")
    return "password"


def _publication_timestamps(entry):
    first_published_at = parse_datetime(entry["first_published_at"])
    last_published_at = parse_datetime(entry["last_published_at"])
    if first_published_at is None or last_published_at is None:
        raise WagtailPortError("Page publication timestamps are invalid.")
    return first_published_at, last_published_at


def _preflight_pages(namespace, page_entries, index):
    planned = {}
    for entry in page_entries:
        source_page_id = entry["source_page_id"]
        mapping = (
            WagtailPageImport.objects.select_related("page")
            .filter(
                source_namespace=namespace,
                source_page_id=source_page_id,
            )
            .first()
        )
        slug = entry["live"]["snapshot"]["slug"]
        sibling = index.get_children().filter(slug=slug).first()
        if mapping is None:
            if sibling is not None:
                raise WagtailPortError(
                    f"Destination slug {slug!r} belongs to an unrelated page."
                )
            planned[source_page_id] = ("create", None)
            continue
        page = mapping.page
        if page.get_parent().pk != index.pk:
            raise WagtailPortError(f"Mapped page {source_page_id} left the blog index.")
        if sibling is None or sibling.pk != page.pk:
            raise WagtailPortError(f"Mapped page {source_page_id} no longer owns its slug.")
        actual_live_hash, actual_draft_hash = _actual_page_hashes(page)
        if (
            actual_live_hash != mapping.target_live_sha256
            or actual_draft_hash != mapping.target_draft_sha256
        ):
            raise WagtailPortError(
                f"Mapped page {source_page_id} has destination editorial drift."
            )
        expected_first_published_at, expected_last_published_at = (
            _publication_timestamps(entry)
        )
        if (
            page.first_published_at != mapping.source_first_published_at
            or page.last_published_at != mapping.source_last_published_at
        ):
            raise WagtailPortError(
                f"Mapped page {source_page_id} publication timestamps drifted."
            )
        expected_restriction = entry["restriction"]["type"]
        if _restriction_type(page) != expected_restriction:
            raise WagtailPortError(
                f"Mapped page {source_page_id} restriction state drifted."
            )
        source_live_hash = entry["live"]["sha256"]
        source_draft_hash = entry["draft"]["sha256"] if entry["draft"] else ""
        if (
            mapping.source_live_sha256 == source_live_hash
            and mapping.source_draft_sha256 == source_draft_hash
            and mapping.source_first_published_at == expected_first_published_at
            and mapping.source_last_published_at == expected_last_published_at
        ):
            planned[source_page_id] = ("unchanged", mapping)
        else:
            planned[source_page_id] = ("update", mapping)
    return planned


def _stable_image_storage_target(namespace, payload):
    image_model = get_image_model()
    image = image_model(
        title=payload.title or payload.filename,
        width=payload.width,
        height=payload.height,
    )
    namespace_hash = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:16]
    suffix = PurePosixPath(payload.filename).suffix.lower()
    filename = (
        f"wagtail-port-{namespace_hash}-{payload.source_image_id}-"
        f"{payload.source_sha256[:20]}{suffix}"
    )
    file_field = image_model._meta.get_field("file")
    storage_name = file_field.generate_filename(image, filename)
    if len(storage_name) > file_field.max_length:
        raise WagtailPortError("Stable Wagtail image storage name is too long.")
    return image, file_field.storage, storage_name


def _storage_matches(storage, name, payload):
    digest = hashlib.sha256()
    total = 0
    try:
        with storage.open(name, "rb") as stored_file:
            while True:
                chunk = stored_file.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > len(payload.data):
                    return False
                digest.update(chunk)
    except Exception as exc:
        raise WagtailPortError(f"Could not verify media object {name}.") from exc
    return total == len(payload.data) and digest.hexdigest() == payload.source_sha256


def _import_images(namespace, image_payloads, created_files, summary):
    image_map = {}
    image_urls = {}
    for source_image_id, payload in sorted(image_payloads.items()):
        mapping = (
            WagtailImageImport.objects.select_related("image")
            .filter(
                source_namespace=namespace,
                source_image_id=source_image_id,
            )
            .first()
        )
        if mapping:
            image_map[source_image_id] = mapping.image.pk
            image_urls[source_image_id] = mapping.image.file.url
            summary.unchanged_images += 1
            continue

        image, storage, expected_name = _stable_image_storage_target(namespace, payload)
        target_existed = storage.exists(expected_name)
        if target_existed:
            if not _storage_matches(storage, expected_name, payload):
                raise WagtailPortError(
                    f"Stable image target has unexpected bytes: {expected_name}."
                )
            stored_name = expected_name
        else:
            stored_name = storage.save(expected_name, ContentFile(payload.data))
            created_files.append((storage, stored_name))
            if stored_name != expected_name:
                raise WagtailPortError("Media storage changed a collision-safe image name.")
        image.file.name = stored_name
        image.save()
        mapping = WagtailImageImport.objects.create(
            source_namespace=namespace,
            source_image_id=source_image_id,
            image=image,
            source_sha256=payload.source_sha256,
            stored_sha256=payload.source_sha256,
        )
        image_map[source_image_id] = mapping.image.pk
        image_urls[source_image_id] = mapping.image.file.url
        summary.created_images += 1
    return image_map, image_urls


def _rewrite_reference_tags(text, image_map, page_map):
    def replace_tag(match):
        tag = match.group(0)
        id_match = ID_ATTRIBUTE_PATTERN.search(tag)
        if not id_match:
            return tag
        source_id = int(id_match.group("id"))
        lowered = tag.lower()
        if "embedtype=\"image\"" in lowered or "embedtype='image'" in lowered:
            if source_id not in image_map:
                raise WagtailPortError(f"No image mapping for source ID {source_id}.")
            target_id = image_map[source_id]
        elif "linktype=\"page\"" in lowered or "linktype='page'" in lowered:
            if source_id not in page_map:
                raise WagtailPortError(f"No page mapping for source ID {source_id}.")
            target_id = page_map[source_id]
        else:
            return tag
        start, end = id_match.span("id")
        return f"{tag[:start]}{target_id}{tag[end:]}"

    return REFERENCE_TAG_PATTERN.sub(replace_tag, text)


def _rewrite_text_urls(text, source_url_map):
    rewritten = text
    for source_url, destination_url in sorted(
        source_url_map.items(),
        key=lambda pair: len(pair[0]),
        reverse=True,
    ):
        if source_url:
            rewritten = rewritten.replace(source_url, destination_url)
    return rewritten


def _rewrite_body(blocks, image_map, page_map, source_url_map):
    rewritten = copy.deepcopy(blocks)
    for block in rewritten:
        block_type = block.get("type")
        value = block.get("value")
        if block_type == "image":
            source_id = int(value["image"])
            if source_id not in image_map:
                raise WagtailPortError(f"No image mapping for source ID {source_id}.")
            value["image"] = image_map[source_id]
        elif block_type == "collapsible":
            value["content"] = _rewrite_body(
                value["content"],
                image_map,
                page_map,
                source_url_map,
            )
        elif isinstance(value, str):
            value = _rewrite_reference_tags(value, image_map, page_map)
            block["value"] = _rewrite_text_urls(value, source_url_map)
    return rewritten


def _rewrite_snapshot(snapshot, image_map, page_map, source_url_map):
    rewritten = copy.deepcopy(snapshot)
    for field_name in ("featured_image_id", "social_image_id"):
        source_id = rewritten[field_name]
        if source_id is not None:
            if source_id not in image_map:
                raise WagtailPortError(f"No image mapping for source ID {source_id}.")
            rewritten[field_name] = image_map[source_id]
    rewritten["body"] = _rewrite_body(
        rewritten["body"],
        image_map,
        page_map,
        source_url_map,
    )
    return rewritten


def _validation_reference_maps(
    namespace,
    manifest,
    image_payloads,
    planned,
    index,
):
    referenced_image_ids = set()
    for entry in manifest["pages"]:
        for state_name in ("live", "draft"):
            state = entry.get(state_name)
            if state is None:
                continue
            state_image_ids, _page_ids, _applet_paths = _snapshot_references(
                state["snapshot"]
            )
            referenced_image_ids.update(state_image_ids)

    image_model = get_image_model()
    placeholder_image = image_model.objects.order_by("pk").first()
    image_map = {}
    image_urls = {}
    for source_image_id, payload in sorted(image_payloads.items()):
        mapping = (
            WagtailImageImport.objects.select_related("image")
            .filter(
                source_namespace=namespace,
                source_image_id=source_image_id,
            )
            .first()
        )
        if mapping is not None:
            image_map[source_image_id] = mapping.image_id
            image_urls[source_image_id] = mapping.image.file.url
            continue
        if source_image_id in referenced_image_ids:
            if placeholder_image is None:
                raise WagtailPortError(
                    "Dry-run revision validation requires one existing destination "
                    "image when new page snapshots contain image references."
                )
            image_map[source_image_id] = placeholder_image.pk
        _image, storage, expected_name = _stable_image_storage_target(
            namespace,
            payload,
        )
        try:
            image_urls[source_image_id] = storage.url(expected_name)
        except Exception as exc:
            raise WagtailPortError(
                f"Could not resolve the destination URL for image {source_image_id}."
            ) from exc

    page_map = {manifest["source_index_page_id"]: index.pk}
    for source_page_id, (_action, mapping) in planned.items():
        page_map[source_page_id] = mapping.page_id if mapping is not None else index.pk

    source_url_map = {}
    for source_image_id, payload in image_payloads.items():
        destination_url = image_urls[source_image_id]
        for source_url in payload.source_urls:
            source_url_map[source_url] = destination_url
    return image_map, page_map, source_url_map


def _validate_rewritten_pages(
    namespace,
    manifest,
    image_payloads,
    planned,
    index,
):
    image_map, page_map, source_url_map = _validation_reference_maps(
        namespace,
        manifest,
        image_payloads,
        planned,
        index,
    )
    body_field = BlogPage._meta.get_field("body")
    imported_field_names = (
        "title",
        "slug",
        "seo_title",
        "search_description",
        "show_in_menus",
        "date",
        "is_featured",
        "abstract",
        "featured_image",
        "social_image",
    )
    for entry in manifest["pages"]:
        for state_name in ("live", "draft"):
            state = entry.get(state_name)
            if state is None:
                continue
            rewritten = _rewrite_snapshot(
                state["snapshot"],
                image_map,
                page_map,
                source_url_map,
            )
            page = BlogPage(title=rewritten["title"], slug=rewritten["slug"])
            _apply_snapshot(page, rewritten)
            try:
                cleaned_body = body_field.stream_block.clean(page.body)
                body_field.get_prep_value(cleaned_body)
                for field_name in imported_field_names:
                    field = BlogPage._meta.get_field(field_name)
                    field.clean(field.value_from_object(page), page)
            except ValidationError as exc:
                raise WagtailPortError(
                    f"Page {entry['source_page_id']} {state_name} failed "
                    "rewritten revision validation."
                ) from exc


def _apply_snapshot(page, snapshot):
    page.title = snapshot["title"]
    page.slug = snapshot["slug"]
    page.seo_title = snapshot["seo_title"]
    page.search_description = snapshot["search_description"]
    page.show_in_menus = snapshot["show_in_menus"]
    page.date = date.fromisoformat(snapshot["date"]) if snapshot["date"] else None
    page.is_featured = snapshot["is_featured"]
    page.abstract = snapshot["abstract"]
    page.body = snapshot["body"]
    page.featured_image_id = snapshot["featured_image_id"]
    page.social_image_id = snapshot["social_image_id"]
    page.body_render_cache_key = ""
    page.body_rendered_html = ""
    page.body_rendered_toc_items = []
    page.body_rendered_toc_crumb = ""
    page.body_rendered_readtime_main = ""
    page.body_rendered_readtime_deep = ""


def _set_restriction(page, restriction_type):
    restrictions = list(PageViewRestriction.objects.filter(page=page))
    if restriction_type == "none":
        if restrictions:
            raise WagtailPortError("Refusing to remove an existing page restriction.")
        return
    if restrictions:
        if len(restrictions) != 1 or restrictions[0].restriction_type != "password":
            raise WagtailPortError("Destination page restriction is not compatible.")
        return
    PageViewRestriction.objects.create(
        page=page,
        restriction_type=PageViewRestriction.PASSWORD,
        password=secrets.token_urlsafe(48),
    )


def _import_page(
    entry,
    page,
    mapping,
    action,
    image_map,
    page_map,
    source_url_map,
    namespace,
):
    live_snapshot = _rewrite_snapshot(
        entry["live"]["snapshot"],
        image_map,
        page_map,
        source_url_map,
    )
    draft_snapshot = (
        _rewrite_snapshot(
            entry["draft"]["snapshot"],
            image_map,
            page_map,
            source_url_map,
        )
        if entry["draft"]
        else None
    )
    _apply_snapshot(page, live_snapshot)
    live_revision = page.save_revision(clean=True)
    live_revision.publish()
    first_published_at, last_published_at = _publication_timestamps(entry)
    Page.objects.filter(pk=page.pk).update(
        first_published_at=first_published_at,
        last_published_at=last_published_at,
    )
    page.refresh_from_db()
    if draft_snapshot is not None:
        _apply_snapshot(page, draft_snapshot)
        page.save_revision(clean=True)
    _set_restriction(page, entry["restriction"]["type"])

    target_live_hash = snapshot_sha256(live_snapshot)
    target_draft_hash = snapshot_sha256(draft_snapshot) if draft_snapshot else ""
    values = {
        "page": page,
        "source_live_sha256": entry["live"]["sha256"],
        "source_draft_sha256": entry["draft"]["sha256"] if entry["draft"] else "",
        "source_first_published_at": first_published_at,
        "source_last_published_at": last_published_at,
        "target_live_sha256": target_live_hash,
        "target_draft_sha256": target_draft_hash,
    }
    if mapping is None:
        WagtailPageImport.objects.create(
            source_namespace=namespace,
            source_page_id=entry["source_page_id"],
            **values,
        )
    else:
        for field_name, value in values.items():
            setattr(mapping, field_name, value)
        mapping.save(
            update_fields=[
                "page",
                "source_live_sha256",
                "source_draft_sha256",
                "source_first_published_at",
                "source_last_published_at",
                "target_live_sha256",
                "target_draft_sha256",
                "imported_at",
            ]
        )
    return action


def _cleanup_created_files(created_files):
    failures = 0
    for storage, name in reversed(created_files):
        try:
            storage.delete(name)
        except Exception:
            failures += 1
    created_files.clear()
    return failures


def import_wagtail_bundle(
    bundle_path,
    *,
    hostname,
    port=443,
    expected_namespace=None,
    expected_bundle_sha256,
    dry_run=False,
):
    manifest, image_payloads = load_wagtail_bundle(
        bundle_path,
        expected_namespace=expected_namespace,
        expected_sha256=expected_bundle_sha256,
    )
    namespace = manifest["source_namespace"]
    page_entries = manifest["pages"]
    _site, index = _find_site_index(hostname, port)
    _preflight_images(namespace, image_payloads)
    planned = _preflight_pages(namespace, page_entries, index)
    _validate_rewritten_pages(
        namespace,
        manifest,
        image_payloads,
        planned,
        index,
    )
    summary = PortSummary(
        pages=len(page_entries),
        images=len(image_payloads),
        restricted_pages=sum(
            entry["restriction"]["type"] == "password" for entry in page_entries
        ),
        draft_pages=sum(entry["draft"] is not None for entry in page_entries),
        dry_run=dry_run,
    )
    for action, _mapping in planned.values():
        if action == "create":
            summary.created_pages += 1
        elif action == "update":
            summary.updated_pages += 1
        else:
            summary.unchanged_pages += 1
    summary.created_images = sum(
        not WagtailImageImport.objects.filter(
            source_namespace=namespace,
            source_image_id=source_image_id,
        ).exists()
        for source_image_id in image_payloads
    )
    summary.unchanged_images = len(image_payloads) - summary.created_images
    if dry_run:
        return summary

    created_files = []
    transaction_body_completed = False
    try:
        with transaction.atomic():
            try:
                Page.objects.select_for_update().get(pk=index.pk)
                _preflight_images(namespace, image_payloads)
                planned = _preflight_pages(namespace, page_entries, index)
                summary.created_pages = 0
                summary.updated_pages = 0
                summary.unchanged_pages = 0
                summary.created_images = 0
                summary.unchanged_images = 0
                image_map, image_urls = _import_images(
                    namespace,
                    image_payloads,
                    created_files,
                    summary,
                )

                pages = {}
                for entry in page_entries:
                    source_page_id = entry["source_page_id"]
                    action, mapping = planned[source_page_id]
                    if mapping is not None:
                        pages[source_page_id] = mapping.page
                        continue
                    snapshot = entry["live"]["snapshot"]
                    page = BlogPage(
                        title=snapshot["title"],
                        slug=snapshot["slug"],
                        live=False,
                    )
                    index.add_child(instance=page)
                    pages[source_page_id] = page

                page_map = {
                    manifest["source_index_page_id"]: index.pk,
                    **{
                        source_page_id: page.pk
                        for source_page_id, page in pages.items()
                    },
                }
                source_url_map = {}
                for source_image_id, payload in image_payloads.items():
                    destination_url = image_urls[source_image_id]
                    for source_url in payload.source_urls:
                        source_url_map[source_url] = destination_url

                for entry in page_entries:
                    source_page_id = entry["source_page_id"]
                    action, mapping = planned[source_page_id]
                    if action == "unchanged":
                        summary.unchanged_pages += 1
                        continue
                    result = _import_page(
                        entry,
                        pages[source_page_id],
                        mapping,
                        action,
                        image_map,
                        page_map,
                        source_url_map,
                        namespace,
                    )
                    if result == "create":
                        summary.created_pages += 1
                    else:
                        summary.updated_pages += 1
                transaction_body_completed = True
            except Exception as import_error:
                cleanup_failures = _cleanup_created_files(created_files)
                if cleanup_failures:
                    raise WagtailPortError(
                        f"Import failed and {cleanup_failures} media files "
                        "could not be removed."
                    ) from import_error
                raise
    except Exception as import_error:
        if transaction_body_completed:
            raise WagtailPortError(
                "Import commit outcome is unknown; deterministic media was "
                "preserved. Retry the identical bundle to reconcile state."
            ) from import_error
        if isinstance(import_error, WagtailPortError):
            raise
        raise WagtailPortError("Wagtail port import failed.") from import_error
    return summary


def set_imported_page_password(source_namespace, source_page_id, password):
    if not isinstance(password, str) or not password or len(password) > 255:
        raise WagtailPortError("Restriction password input is invalid.")
    if not NAMESPACE_PATTERN.fullmatch(source_namespace):
        raise WagtailPortError("source_namespace is invalid.")
    with transaction.atomic():
        try:
            mapping = WagtailPageImport.objects.select_for_update().select_related("page").get(
                source_namespace=source_namespace,
                source_page_id=source_page_id,
            )
        except WagtailPageImport.DoesNotExist as exc:
            raise WagtailPortError("Imported page mapping does not exist.") from exc
        restrictions = list(PageViewRestriction.objects.select_for_update().filter(page=mapping.page))
        if len(restrictions) != 1 or restrictions[0].restriction_type != "password":
            raise WagtailPortError("Imported page does not have one password restriction.")
        restrictions[0].password = password
        restrictions[0].save(update_fields=["password"])
