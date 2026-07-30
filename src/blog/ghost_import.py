import base64
import binascii
import gzip
import hashlib
import html
import io
import json
import re
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import UUID

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify
from django.utils.timezone import is_naive, make_aware
from PIL import Image as PillowImage
from PIL import ImageOps, ImageSequence, UnidentifiedImageError
from wagtail.contrib.redirects.models import Redirect
from wagtail.images import get_image_model
from wagtail.models import Page, Site

from blog.html_sanitizer import sanitize_structural_html
from blog.models import (
    BlogAuthor,
    BlogIndexPage,
    BlogPage,
    BlogTag,
    ContentPage,
    GhostImageImport,
)

MAX_EXPORT_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 5_000
MAX_ARCHIVE_MEMBER_NAME_BYTES = 1_024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_DECOMPRESSED_BYTES = MAX_TOTAL_IMAGE_BYTES + (16 * 1024 * 1024)
MAX_IMAGE_PIXELS = 25_000_000
MAX_TOTAL_IMAGE_PIXELS = 100_000_000
MAX_TOTAL_CANONICAL_IMAGE_BYTES = 100 * 1024 * 1024
MAX_IMAGE_FRAMES = 500
MAX_INLINE_IMAGE_ENCODED_BYTES = ((MAX_IMAGE_BYTES + 2) // 3) * 4
ARCHIVE_COPY_CHUNK_BYTES = 1024 * 1024
REJECTED_TAR_TYPEFLAGS = {
    tarfile.GNUTYPE_LONGNAME,
    tarfile.GNUTYPE_LONGLINK,
    tarfile.XHDTYPE,
    tarfile.XGLTYPE,
    tarfile.GNUTYPE_SPARSE,
}
GHOST_URL_PREFIX = "__GHOST_URL__"
EXPLICIT_INTERNAL_ALIASES = {
    "/splatgpt-part-02b/": "splatgpt-part-2b",
    "/the-deceptive-difficulty-of-splatoon-3-gear-optimization/": "splatgpt-part-1",
}
URL_ATTRIBUTE_PATTERN = re.compile(
    r"(?P<prefix>\b(?:href|src)\s*=\s*(?P<quote>[\"']))"
    r"(?P<url>.*?)"
    r"(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)
SRCSET_ATTRIBUTE_PATTERN = re.compile(
    r"\s+srcset\s*=\s*(?:\"[^\"]*\"|'[^']*')",
    re.IGNORECASE | re.DOTALL,
)
SVG_BLOCK_PATTERN = re.compile(
    r"<svg\b.*?</svg\s*>",
    re.IGNORECASE | re.DOTALL,
)
SVG_IMAGE_TAG_PATTERN = re.compile(
    r"<image\b(?P<attributes>(?:[^>\"']|\"[^\"]*\"|'[^']*')*)/?>",
    re.IGNORECASE | re.DOTALL,
)
SVG_IMAGE_HREF_PATTERN = re.compile(
    r"(?P<attribute>\b(?:xlink:href|href))"
    r"\s*=\s*(?P<quote>[\"'])"
    r"(?P<url>.*?)"
    r"(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)
STRICT_INLINE_PNG_PATTERN = re.compile(
    r"\Adata:image/png;base64,"
    r"(?P<payload>(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?)"
    r"\Z"
)
ALLOWED_EXPORT_KEYS = {
    "authors",
    "exported_at",
    "posts",
    "posts_authors",
    "posts_tags",
    "schema_version",
    "settings",
    "source",
    "tags",
}
ALLOWED_SETTINGS_KEYS = {
    "accent_color",
    "active_theme",
    "cover_image",
    "default_content_visibility",
    "description",
    "icon",
    "locale",
    "logo",
    "timezone",
    "title",
}
ALLOWED_POST_KEYS = {
    "canonical_url",
    "codeinjection_foot",
    "codeinjection_head",
    "created_at",
    "custom_excerpt",
    "custom_template",
    "feature_image",
    "featured",
    "html",
    "id",
    "locale",
    "plaintext",
    "published_at",
    "show_title_and_feature_image",
    "slug",
    "status",
    "title",
    "type",
    "updated_at",
    "uuid",
    "visibility",
}
ALLOWED_AUTHOR_KEYS = {
    "bio",
    "cover_image",
    "facebook",
    "id",
    "locale",
    "location",
    "meta_description",
    "meta_title",
    "name",
    "profile_image",
    "slug",
    "status",
    "twitter",
    "visibility",
    "website",
}
ALLOWED_TAG_KEYS = {
    "accent_color",
    "canonical_url",
    "description",
    "feature_image",
    "id",
    "meta_description",
    "meta_title",
    "name",
    "slug",
    "visibility",
}
ALLOWED_POST_AUTHOR_KEYS = {"author_id", "post_id", "sort_order"}
ALLOWED_POST_TAG_KEYS = {"post_id", "sort_order", "tag_id"}


class GhostImportError(ValueError):
    pass


@dataclass
class ImportSummary:
    posts: int = 0
    pages: int = 0
    published_posts: int = 0
    draft_posts: int = 0
    authors: int = 0
    tags: int = 0
    images: int = 0
    archive_images: int = 0
    inline_images: int = 0
    redirects: int = 0
    created_pages: int = 0
    updated_pages: int = 0
    unchanged_pages: int = 0


@dataclass(frozen=True)
class CanonicalImagePayload:
    data: bytes
    extension: str
    source_sha256: str
    width: int
    height: int
    pixel_count: int


@dataclass(frozen=True)
class ImageProcessingWork:
    distinct_images: int = 0
    canonical_bytes: int = 0
    decoded_pixels: int = 0


def _reject_unknown_keys(record, allowed_keys, label):
    if not isinstance(record, dict):
        raise GhostImportError(f"{label} must be an object.")
    unknown = set(record) - allowed_keys
    if unknown:
        unknown_list = ", ".join(sorted(unknown))
        raise GhostImportError(f"{label} has unsupported fields: {unknown_list}")


def _validate_identities(records, allowed_keys, label):
    ids = set()
    slugs = set()
    for record in records:
        _reject_unknown_keys(record, allowed_keys, label)
        identity = str(record.get("id") or "")
        slug = str(record.get("slug") or "")
        if not identity or identity in ids:
            raise GhostImportError(f"{label} IDs must be present and unique.")
        if not slug or slug in slugs:
            raise GhostImportError(f"{label} slugs must be present and unique.")
        if record.get("visibility") != "public":
            raise GhostImportError(f"{label} {identity} has unsupported non-public visibility.")
        ids.add(identity)
        slugs.add(slug)
    return ids


def _ghost_featured_value(record):
    value = record.get("featured", 0)
    if isinstance(value, bool):
        return value
    if type(value) is int and value in {0, 1}:
        return bool(value)
    raise GhostImportError(f"Ghost content {record.get('id')} has an invalid featured flag.")


def _load_export(export_path):
    path = Path(export_path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise GhostImportError(f"Cannot read Ghost export: {exc}") from exc
    if size > MAX_EXPORT_BYTES:
        raise GhostImportError(f"Ghost export is {size} bytes; the maximum is {MAX_EXPORT_BYTES}.")

    try:
        with path.open(encoding="utf-8") as export_file:
            payload = json.load(export_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GhostImportError(f"Invalid Ghost export: {exc}") from exc

    _reject_unknown_keys(payload, ALLOWED_EXPORT_KEYS, "Ghost export")
    if payload.get("schema_version") != 1:
        raise GhostImportError("Only Ghost migration schema_version 1 is supported.")
    for key in ("posts", "authors", "tags", "posts_authors", "posts_tags"):
        if not isinstance(payload.get(key), list):
            raise GhostImportError(f"Ghost export field {key!r} must be a list.")
    ghost_settings = payload.get("settings")
    if ghost_settings is not None:
        _reject_unknown_keys(
            ghost_settings,
            ALLOWED_SETTINGS_KEYS,
            "Ghost settings",
        )
        for identity_key in ("title", "description"):
            identity_value = ghost_settings.get(identity_key)
            if identity_value is not None and not isinstance(identity_value, str):
                raise GhostImportError(f"Ghost setting {identity_key} must be text.")
        default_visibility = ghost_settings.get(
            "default_content_visibility",
            "public",
        )
        if default_visibility != "public":
            raise GhostImportError(
                "Ghost settings have unsupported non-public default content visibility."
            )

    seen_ids = set()
    seen_slugs = set()
    seen_uuids = set()
    for record in payload["posts"]:
        _reject_unknown_keys(record, ALLOWED_POST_KEYS, "Ghost content record")
        ghost_id = str(record.get("id") or "")
        slug = str(record.get("slug") or "")
        if not ghost_id or ghost_id in seen_ids:
            raise GhostImportError("Ghost content IDs must be present and unique.")
        if not slug or slug in seen_slugs:
            raise GhostImportError("Ghost content slugs must be present and unique.")
        if record.get("type") not in {"page", "post"}:
            raise GhostImportError(f"Unsupported Ghost content type for {ghost_id}.")
        if record.get("status") not in {"draft", "published"}:
            raise GhostImportError(f"Unsupported Ghost status for {ghost_id}.")
        if record.get("visibility") != "public":
            raise GhostImportError(
                f"Ghost content {ghost_id} has unsupported non-public visibility."
            )
        is_featured = _ghost_featured_value(record)
        if record.get("type") == "page" and is_featured:
            raise GhostImportError(f"Ghost page {ghost_id} cannot preserve a featured-post flag.")
        ghost_uuid = _parse_uuid(record.get("uuid"))
        if ghost_uuid is None:
            raise GhostImportError(f"Ghost content {ghost_id} must have a UUID.")
        if ghost_uuid in seen_uuids:
            raise GhostImportError("Ghost content UUIDs must be unique.")
        seen_ids.add(ghost_id)
        seen_slugs.add(slug)
        seen_uuids.add(ghost_uuid)

    author_ids = _validate_identities(
        payload["authors"],
        ALLOWED_AUTHOR_KEYS,
        "Ghost author record",
    )
    tag_ids = _validate_identities(
        payload["tags"],
        ALLOWED_TAG_KEYS,
        "Ghost tag record",
    )

    seen_author_relations = set()
    author_relation_counts = {}
    for relation in payload["posts_authors"]:
        _reject_unknown_keys(
            relation,
            ALLOWED_POST_AUTHOR_KEYS,
            "Ghost post-author relation",
        )
        relation_key = (
            str(relation.get("post_id") or ""),
            str(relation.get("author_id") or ""),
        )
        if relation_key[0] not in seen_ids or relation_key[1] not in author_ids:
            raise GhostImportError("Ghost post-author relation references a missing identity.")
        if relation_key in seen_author_relations:
            raise GhostImportError("Ghost post-author relations must be unique.")
        try:
            int(relation.get("sort_order") or 0)
        except (TypeError, ValueError) as exc:
            raise GhostImportError("Ghost relation sort_order must be an integer.") from exc
        seen_author_relations.add(relation_key)
        author_relation_counts[relation_key[0]] = author_relation_counts.get(relation_key[0], 0) + 1
        if author_relation_counts[relation_key[0]] > 1:
            raise GhostImportError(
                f"Ghost content {relation_key[0]} has multiple authors; "
                "primary-author order cannot be preserved safely."
            )

    seen_tag_relations = set()
    for relation in payload["posts_tags"]:
        _reject_unknown_keys(
            relation,
            ALLOWED_POST_TAG_KEYS,
            "Ghost post-tag relation",
        )
        relation_key = (
            str(relation.get("post_id") or ""),
            str(relation.get("tag_id") or ""),
        )
        if relation_key[0] not in seen_ids or relation_key[1] not in tag_ids:
            raise GhostImportError("Ghost post-tag relation references a missing identity.")
        if relation_key in seen_tag_relations:
            raise GhostImportError("Ghost post-tag relations must be unique.")
        try:
            int(relation.get("sort_order") or 0)
        except (TypeError, ValueError) as exc:
            raise GhostImportError("Ghost relation sort_order must be an integer.") from exc
        seen_tag_relations.add(relation_key)
    return payload


def _safe_archive_name(name):
    if not name or "\\" in name:
        raise GhostImportError("Ghost archive contains an invalid member path.")
    try:
        encoded_name = name.encode("utf-8")
    except UnicodeError as exc:
        raise GhostImportError(
            "Ghost archive contains a member path that is not valid UTF-8."
        ) from exc
    if len(encoded_name) > MAX_ARCHIVE_MEMBER_NAME_BYTES:
        raise GhostImportError(
            f"Ghost archive member path exceeds the {MAX_ARCHIVE_MEMBER_NAME_BYTES}-byte limit."
        )
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise GhostImportError("Ghost archive contains a path-traversal member.")
    normalized = path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        raise GhostImportError("Ghost archive contains an empty member path.")
    return normalized


def _parse_tar_octal(field, label):
    if field and field[0] & 0x80:
        raise GhostImportError(f"Ghost archive uses unsupported base-256 {label} metadata.")
    value = field.split(b"\0", 1)[0].strip(b" ")
    if not value:
        return 0
    if any(character not in b"01234567" for character in value):
        raise GhostImportError(f"Ghost archive has invalid {label} metadata.")
    return int(value, 8)


def _scan_tar_headers(uncompressed_archive):
    uncompressed_archive.seek(0, io.SEEK_END)
    archive_size = uncompressed_archive.tell()
    uncompressed_archive.seek(0)
    member_count = 0

    while uncompressed_archive.tell() < archive_size:
        header = uncompressed_archive.read(tarfile.BLOCKSIZE)
        if not header:
            break
        if len(header) != tarfile.BLOCKSIZE:
            raise GhostImportError("Ghost archive ends inside a tar header.")
        if header == (b"\0" * tarfile.BLOCKSIZE):
            break

        member_count += 1
        if member_count > MAX_ARCHIVE_MEMBERS:
            raise GhostImportError(
                f"Ghost archive contains more than {MAX_ARCHIVE_MEMBERS} members."
            )

        typeflag = header[156:157] or tarfile.REGTYPE
        if typeflag in REJECTED_TAR_TYPEFLAGS:
            raise GhostImportError(
                "Ghost media archive uses unsupported GNU/PAX extended metadata."
            )

        raw_name = header[0:100].split(b"\0", 1)[0]
        raw_prefix = header[345:500].split(b"\0", 1)[0]
        raw_name_length = len(raw_name) + (1 if raw_prefix else 0) + len(raw_prefix)
        if raw_name_length > MAX_ARCHIVE_MEMBER_NAME_BYTES:
            raise GhostImportError(
                f"Ghost archive member path exceeds the {MAX_ARCHIVE_MEMBER_NAME_BYTES}-byte limit."
            )

        member_size = _parse_tar_octal(header[124:136], "member-size")
        padded_size = (
            (member_size + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE
        ) * tarfile.BLOCKSIZE
        if uncompressed_archive.tell() + padded_size > archive_size:
            raise GhostImportError("Ghost archive member extends beyond the archive.")
        uncompressed_archive.seek(padded_size, io.SEEK_CUR)

    uncompressed_archive.seek(0)


@contextmanager
def _open_bounded_tar_archive(archive_path):
    uncompressed_archive = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    try:
        try:
            with Path(archive_path).open("rb") as compressed_file:
                with gzip.GzipFile(fileobj=compressed_file, mode="rb") as gzip_file:
                    total_decompressed = 0
                    while True:
                        chunk = gzip_file.read(ARCHIVE_COPY_CHUNK_BYTES)
                        if not chunk:
                            break
                        total_decompressed += len(chunk)
                        if total_decompressed > MAX_ARCHIVE_DECOMPRESSED_BYTES:
                            raise GhostImportError(
                                "Ghost media archive exceeds the "
                                f"{MAX_ARCHIVE_DECOMPRESSED_BYTES}-byte "
                                "decompressed limit."
                            )
                        uncompressed_archive.write(chunk)
        except GhostImportError:
            raise
        except (EOFError, OSError) as exc:
            raise GhostImportError(f"Cannot decompress Ghost files archive: {exc}") from exc

        _scan_tar_headers(uncompressed_archive)
        try:
            archive = tarfile.open(fileobj=uncompressed_archive, mode="r:")
        except (OSError, tarfile.TarError) as exc:
            raise GhostImportError(f"Cannot read Ghost files archive: {exc}") from exc
        try:
            yield archive
        finally:
            archive.close()
    finally:
        uncompressed_archive.close()


def _canonicalize_image_bytes(name, data):
    source_sha256 = hashlib.sha256(data).hexdigest()
    canonical_formats = {
        "GIF": ("gif", "GIF"),
        "JPEG": ("jpg", "JPEG"),
        "PNG": ("png", "PNG"),
        "WEBP": ("webp", "WEBP"),
    }
    try:
        with PillowImage.open(io.BytesIO(data)) as image:
            image_format = (image.format or "").upper()
            if image_format not in canonical_formats:
                raise GhostImportError(f"Unsupported image format for {name}.")

            frame_count = int(getattr(image, "n_frames", 1))
            if frame_count < 1 or frame_count > MAX_IMAGE_FRAMES:
                raise GhostImportError(f"Image {name} exceeds the {MAX_IMAGE_FRAMES}-frame limit.")

            canonical_frames = []
            frame_durations = []
            total_pixels = 0
            first_width = 0
            first_height = 0
            for frame_number, frame in enumerate(ImageSequence.Iterator(image)):
                width, height = frame.size
                if width < 1 or height < 1:
                    raise GhostImportError(f"Image {name} has invalid dimensions.")
                total_pixels += width * height
                if total_pixels > MAX_IMAGE_PIXELS:
                    raise GhostImportError(
                        f"Image {name} exceeds the {MAX_IMAGE_PIXELS}-pixel limit."
                    )
                if frame_number == 0:
                    first_width, first_height = width, height

                canonical_frame = frame.copy()
                if image_format == "JPEG":
                    canonical_frame = ImageOps.exif_transpose(canonical_frame).convert("RGB")
                    first_width, first_height = canonical_frame.size
                elif image_format in {"PNG", "WEBP"}:
                    if "A" in canonical_frame.getbands():
                        canonical_frame = canonical_frame.convert("RGBA")
                    else:
                        canonical_frame = canonical_frame.convert("RGB")
                else:
                    canonical_frame = canonical_frame.convert("RGBA")
                canonical_frames.append(canonical_frame)
                frame_durations.append(
                    int(frame.info.get("duration", image.info.get("duration", 0)) or 0)
                )

            if not canonical_frames:
                raise GhostImportError(f"Image {name} has no decodable frames.")

            extension, pillow_format = canonical_formats[image_format]
            output = io.BytesIO()
            save_options = {}
            if pillow_format == "JPEG":
                save_options.update(
                    {
                        "optimize": True,
                        "progressive": True,
                        "quality": 95,
                    }
                )
            elif pillow_format == "PNG":
                save_options.update({"compress_level": 9, "optimize": True})
            elif pillow_format == "WEBP":
                save_options.update({"method": 6, "quality": 95})
            elif pillow_format == "GIF":
                save_options.update({"optimize": True})

            if len(canonical_frames) > 1:
                save_options.update(
                    {
                        "append_images": canonical_frames[1:],
                        "duration": frame_durations,
                        "loop": int(image.info.get("loop", 0) or 0),
                        "save_all": True,
                    }
                )
            canonical_frames[0].save(
                output,
                format=pillow_format,
                **save_options,
            )
            canonical_data = output.getvalue()
            if not canonical_data or len(canonical_data) > MAX_IMAGE_BYTES:
                raise GhostImportError(
                    f"Canonical image {name} has invalid size {len(canonical_data)}."
                )
            return CanonicalImagePayload(
                data=canonical_data,
                extension=extension,
                source_sha256=source_sha256,
                width=first_width,
                height=first_height,
                pixel_count=total_pixels,
            )
    except GhostImportError:
        raise
    except (
        EOFError,
        OSError,
        PillowImage.DecompressionBombError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        raise GhostImportError(f"Invalid image payload for {name}.") from exc


def _image_processing_work(image_payloads):
    return ImageProcessingWork(
        distinct_images=len(image_payloads),
        canonical_bytes=sum(len(payload.data) for payload in image_payloads.values()),
        decoded_pixels=sum(payload.pixel_count for payload in image_payloads.values()),
    )


def _combine_image_processing_work(*work_items):
    return ImageProcessingWork(
        distinct_images=sum(work.distinct_images for work in work_items),
        canonical_bytes=sum(work.canonical_bytes for work in work_items),
        decoded_pixels=sum(work.decoded_pixels for work in work_items),
    )


def _validate_aggregate_image_budget(image_payloads, processing_work=None):
    work = processing_work or _image_processing_work(image_payloads)
    if len(image_payloads) > MAX_ARCHIVE_MEMBERS or work.distinct_images > MAX_ARCHIVE_MEMBERS:
        raise GhostImportError(f"Import references more than {MAX_ARCHIVE_MEMBERS} total images.")
    if work.canonical_bytes > MAX_TOTAL_CANONICAL_IMAGE_BYTES:
        raise GhostImportError(
            f"Canonical images exceed the {MAX_TOTAL_CANONICAL_IMAGE_BYTES}-byte aggregate limit."
        )
    if work.decoded_pixels > MAX_TOTAL_IMAGE_PIXELS:
        raise GhostImportError(
            f"Decoded images exceed the {MAX_TOTAL_IMAGE_PIXELS}-pixel aggregate limit."
        )


def _read_required_images(archive_path, required_paths):
    required_members = {_safe_archive_name(path.lstrip("/")) for path in required_paths}
    if any(not path.startswith("content/images/") for path in required_members):
        raise GhostImportError("Required Ghost media resolved outside content/images/.")

    found = {}
    seen_files = set()
    total_bytes = 0
    total_canonical_bytes = 0
    total_decoded_pixels = 0

    with _open_bounded_tar_archive(archive_path) as archive:
        try:
            for member_number, member in enumerate(archive, start=1):
                if member_number > MAX_ARCHIVE_MEMBERS:
                    raise GhostImportError(
                        f"Ghost archive contains more than {MAX_ARCHIVE_MEMBERS} members."
                    )
                name = _safe_archive_name(member.name)
                if member.pax_headers or getattr(member, "sparse", None):
                    raise GhostImportError(
                        f"Ghost media archive uses unsupported extended metadata: {name}"
                    )
                if member.isdir():
                    if name != "content" and not (
                        name == "content/images" or name.startswith("content/images/")
                    ):
                        raise GhostImportError(
                            f"Ghost media archive contains an out-of-scope directory: {name}"
                        )
                    continue
                if not name.startswith("content/images/"):
                    raise GhostImportError(
                        f"Ghost media archive contains an out-of-scope member: {name}"
                    )
                if (
                    not member.isreg()
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or member.type == tarfile.GNUTYPE_SPARSE
                ):
                    raise GhostImportError(f"Media archive member is not a regular file: {name}")
                if name in seen_files:
                    raise GhostImportError(f"Ghost archive contains duplicate image member: {name}")
                seen_files.add(name)
                if member.size < 1 or member.size > MAX_IMAGE_BYTES:
                    raise GhostImportError(
                        f"Referenced image {name} has invalid size {member.size}."
                    )
                total_bytes += member.size
                if total_bytes > MAX_TOTAL_IMAGE_BYTES:
                    raise GhostImportError(
                        f"Referenced images exceed the {MAX_TOTAL_IMAGE_BYTES}-byte limit."
                    )
                if name not in required_members:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise GhostImportError(f"Could not stream referenced image: {name}")
                data = extracted.read(MAX_IMAGE_BYTES + 1)
                if len(data) != member.size or len(data) > MAX_IMAGE_BYTES:
                    raise GhostImportError(f"Referenced image size changed while reading: {name}")
                image_payload = _canonicalize_image_bytes(name, data)
                total_canonical_bytes += len(image_payload.data)
                if total_canonical_bytes > MAX_TOTAL_CANONICAL_IMAGE_BYTES:
                    raise GhostImportError(
                        "Canonical images exceed the "
                        f"{MAX_TOTAL_CANONICAL_IMAGE_BYTES}-byte aggregate limit."
                    )
                total_decoded_pixels += image_payload.pixel_count
                if total_decoded_pixels > MAX_TOTAL_IMAGE_PIXELS:
                    raise GhostImportError(
                        f"Decoded images exceed the {MAX_TOTAL_IMAGE_PIXELS}-pixel aggregate limit."
                    )
                found[name] = image_payload
        except GhostImportError:
            raise
        except (OSError, tarfile.TarError) as exc:
            raise GhostImportError(f"Invalid Ghost files archive: {exc}") from exc

    missing = required_members - found.keys()
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise GhostImportError(f"Ghost archive is missing referenced images: {missing_list}")
    _validate_aggregate_image_budget(found)
    return found


def _ghost_media_path(url):
    if not url or not url.startswith(GHOST_URL_PREFIX):
        return None
    path = unquote(urlsplit(url[len(GHOST_URL_PREFIX) :]).path)
    if not path.startswith("/content/images/"):
        return None
    normalized = _safe_archive_name(path.lstrip("/"))
    if not normalized.startswith("content/images/"):
        raise GhostImportError("Ghost image URL resolved outside content/images/.")
    return normalized


def _feature_image_path(record):
    value = record.get("feature_image") or ""
    if not value:
        return None
    media_path = _ghost_media_path(value)
    if media_path is None:
        raise GhostImportError(
            f"Ghost feature image for {record.get('id')} is not sanitized local media."
        )
    return media_path


def _without_srcset(html_value):
    return SRCSET_ATTRIBUTE_PATTERN.sub("", html_value or "")


def _referenced_image_paths(payload):
    paths = set()
    for record in payload["posts"]:
        html_value = _without_srcset(record.get("html") or "")
        for match in URL_ATTRIBUTE_PATTERN.finditer(html_value):
            media_path = _ghost_media_path(match.group("url"))
            if media_path:
                paths.add(media_path)
        feature_path = _feature_image_path(record)
        if feature_path:
            paths.add(feature_path)
    return paths


def _inline_png_payloads(payload, prior_work=None):
    image_payloads = {}
    data_uri_paths = {}
    prior_work = prior_work or ImageProcessingWork()
    inline_work = ImageProcessingWork()
    for record in payload["posts"]:
        html_value = record.get("html") or ""
        svg_spans = [match.span() for match in SVG_BLOCK_PATTERN.finditer(html_value)]
        for image_match in SVG_IMAGE_TAG_PATTERN.finditer(html_value):
            href_matches = list(SVG_IMAGE_HREF_PATTERN.finditer(image_match.group(0)))
            data_hrefs = [
                href_match
                for href_match in href_matches
                if html.unescape(href_match.group("url")).lower().startswith("data:")
            ]
            if not data_hrefs:
                continue
            if len(href_matches) != 1 or len(data_hrefs) != 1:
                raise GhostImportError(
                    f"Ghost content {record['id']} has an ambiguous SVG image reference."
                )
            if not any(
                svg_start <= image_match.start() and image_match.end() <= svg_end
                for svg_start, svg_end in svg_spans
            ):
                raise GhostImportError(
                    f"Ghost content {record['id']} has inline image data outside SVG."
                )

            data_uri = html.unescape(data_hrefs[0].group("url"))
            strict_match = STRICT_INLINE_PNG_PATTERN.fullmatch(data_uri)
            if strict_match is None:
                raise GhostImportError(
                    f"Ghost content {record['id']} has a non-canonical inline SVG image."
                )
            encoded_payload = strict_match.group("payload")
            if len(encoded_payload) > MAX_INLINE_IMAGE_ENCODED_BYTES:
                raise GhostImportError(
                    f"Ghost content {record['id']} has an oversized inline SVG image."
                )
            if data_uri in data_uri_paths:
                continue
            try:
                decoded_payload = base64.b64decode(
                    encoded_payload,
                    validate=True,
                )
            except (binascii.Error, ValueError) as exc:
                raise GhostImportError(
                    f"Ghost content {record['id']} has invalid inline PNG base64."
                ) from exc
            if len(decoded_payload) > MAX_IMAGE_BYTES:
                raise GhostImportError(f"Ghost content {record['id']} has an oversized inline PNG.")

            canonical = _canonicalize_image_bytes(
                f"inline SVG image in Ghost content {record['id']}",
                decoded_payload,
            )
            if canonical.extension != "png":
                raise GhostImportError(
                    f"Ghost content {record['id']} has non-PNG bytes in an inline PNG URL."
                )
            canonical_digest = hashlib.sha256(canonical.data).hexdigest()
            inline_path = f"inline-images/{canonical_digest}.png"
            image_payloads.setdefault(
                inline_path,
                replace(
                    canonical,
                    source_sha256=canonical_digest,
                ),
            )
            data_uri_paths[data_uri] = inline_path
            inline_work = ImageProcessingWork(
                distinct_images=inline_work.distinct_images + 1,
                canonical_bytes=inline_work.canonical_bytes + len(canonical.data),
                decoded_pixels=inline_work.decoded_pixels + canonical.pixel_count,
            )
            _validate_aggregate_image_budget(
                image_payloads,
                _combine_image_processing_work(prior_work, inline_work),
            )
    return image_payloads, data_uri_paths, inline_work


def _rewrite_inline_svg_images(html_value, data_uri_paths, image_urls):
    def rewrite_svg(svg_match):
        def rewrite_image(image_match):
            image_tag = image_match.group(0)
            href_matches = list(SVG_IMAGE_HREF_PATTERN.finditer(image_tag))
            if len(href_matches) != 1:
                return image_tag
            href_match = href_matches[0]
            data_uri = html.unescape(href_match.group("url"))
            inline_path = data_uri_paths.get(data_uri)
            if inline_path is None:
                return image_tag
            image_url = image_urls.get(inline_path)
            if image_url is None:
                raise GhostImportError(f"No imported inline image mapping for {inline_path}.")
            replacement = f'href="{html.escape(image_url, quote=True)}"'
            return image_tag[: href_match.start()] + replacement + image_tag[href_match.end() :]

        return SVG_IMAGE_TAG_PATTERN.sub(rewrite_image, svg_match.group(0))

    return SVG_BLOCK_PATTERN.sub(rewrite_svg, html_value or "")


def _local_internal_url(url):
    if url.startswith(GHOST_URL_PREFIX):
        return url[len(GHOST_URL_PREFIX) :] or "/"
    parsed = urlsplit(url)
    if not parsed.scheme and not parsed.netloc and url.startswith("/"):
        return url
    return None


def _active_aliases(payload):
    referenced_aliases = set()
    records_by_slug = {str(record["slug"]): record for record in payload["posts"]}
    record_slugs = set(records_by_slug)
    for record in payload["posts"]:
        html_value = _without_srcset(record.get("html") or "")
        for match in URL_ATTRIBUTE_PATTERN.finditer(html_value):
            local_url = _local_internal_url(match.group("url"))
            if not local_url:
                continue
            path = urlsplit(local_url).path
            if path in EXPLICIT_INTERNAL_ALIASES:
                referenced_aliases.add(path)

    aliases = {}
    for old_path in sorted(referenced_aliases):
        target_slug = EXPLICIT_INTERNAL_ALIASES[old_path]
        target = records_by_slug.get(target_slug)
        if not target:
            raise GhostImportError(
                f"Explicit alias {old_path} has no canonical Ghost target {target_slug}."
            )
        if target["type"] != "post" or target["status"] != "published":
            raise GhostImportError(f"Explicit alias {old_path} must target a published Ghost post.")
        old_slug = old_path.strip("/")
        if old_slug in record_slugs:
            raise GhostImportError(
                f"Explicit alias {old_path} collides with an imported content slug."
            )
        aliases[old_path] = target_slug
    return aliases


def _rewrite_alias_url(local_url):
    parsed = urlsplit(local_url)
    target_slug = EXPLICIT_INTERNAL_ALIASES.get(parsed.path)
    if not target_slug:
        return local_url
    return urlunsplit(("", "", f"/{target_slug}/", parsed.query, parsed.fragment))


def _rewrite_and_sanitize_html(
    html_value,
    image_urls,
    inline_data_uri_paths=None,
):
    with_inline_images = _rewrite_inline_svg_images(
        html_value or "",
        inline_data_uri_paths or {},
        image_urls,
    )
    without_srcset = _without_srcset(with_inline_images)

    def replace_attribute(match):
        original_url = match.group("url")
        media_path = _ghost_media_path(original_url)
        if media_path:
            if media_path not in image_urls:
                raise GhostImportError(f"No imported image mapping for {media_path}.")
            replacement = image_urls[media_path]
        else:
            local_url = _local_internal_url(original_url)
            replacement = _rewrite_alias_url(local_url) if local_url is not None else original_url
        return f"{match.group('prefix')}{replacement}{match.group('quote')}"

    rewritten = URL_ATTRIBUTE_PATTERN.sub(replace_attribute, without_srcset)
    rewritten = rewritten.replace(GHOST_URL_PREFIX, "")
    return sanitize_structural_html(rewritten)


def _validate_content_records(payload, required_paths, inline_data_uri_paths):
    media_prefix = settings.MEDIA_URL.rstrip("/")
    fake_urls = {
        path: (
            f"{media_prefix}/original_images/ghost-"
            f"{hashlib.sha256(path.encode('utf-8')).hexdigest()}.png"
        )
        for path in required_paths
    }
    for record in payload["posts"]:
        feature_path = _feature_image_path(record)
        if record["type"] == "page" and feature_path:
            raise GhostImportError(f"Ghost page {record['id']} has an unsupported feature image.")
        _rewrite_and_sanitize_html(
            record.get("html") or "",
            fake_urls,
            inline_data_uri_paths,
        )
        _parse_uuid(record.get("uuid"))
        _parse_timestamp(
            record.get("created_at"),
            "created_at",
            required=True,
        )
        _parse_timestamp(
            record.get("updated_at"),
            "updated_at",
            required=True,
        )
        published_at = _parse_timestamp(record.get("published_at"), "published_at")
        if record["status"] == "published" and published_at is None:
            raise GhostImportError(f"Published Ghost content {record['id']} has no published_at.")


def _parse_timestamp(value, field_name, *, required=False):
    if not value:
        if required:
            raise GhostImportError(f"Ghost field {field_name} is required.")
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise GhostImportError(f"Ghost field {field_name} is not a valid timestamp.")
    if is_naive(parsed):
        parsed = make_aware(parsed, timezone=UTC)
    return parsed


def _parse_uuid(value):
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise GhostImportError("Ghost uuid is invalid.") from exc


def _upsert_identity(model, record):
    ghost_id = str(record.get("id") or "")
    slug = str(record.get("slug") or "")
    if not ghost_id or not slug:
        raise GhostImportError(f"{model.__name__} requires a Ghost ID and slug.")

    by_id = model.objects.filter(ghost_id=ghost_id).first()
    by_slug = model.objects.filter(slug=slug).first()
    if by_id and by_slug and by_id.pk != by_slug.pk:
        raise GhostImportError(f"{model.__name__} identity conflicts for slug {slug}.")
    instance = by_id or by_slug or model()
    if instance.ghost_id and instance.ghost_id != ghost_id:
        raise GhostImportError(f"{model.__name__} slug {slug} belongs to another Ghost ID.")
    return instance


def _import_authors(payload):
    authors = {}
    for record in payload["authors"]:
        author = _upsert_identity(BlogAuthor, record)
        desired = {
            "ghost_id": str(record["id"]),
            "slug": str(record["slug"]),
            "name": str(record.get("name") or record.get("slug") or ""),
            "bio": str(record.get("bio") or ""),
            "website": str(record.get("website") or ""),
        }
        if author.pk is None or any(
            getattr(author, field_name) != value for field_name, value in desired.items()
        ):
            for field_name, value in desired.items():
                setattr(author, field_name, value)
            author.save()
        authors[author.ghost_id] = author
    return authors


def _import_tags(payload):
    tags = {}
    for record in payload["tags"]:
        tag = _upsert_identity(BlogTag, record)
        desired = {
            "ghost_id": str(record["id"]),
            "slug": str(record["slug"]),
            "name": str(record.get("name") or record.get("slug") or ""),
            "description": str(record.get("description") or ""),
        }
        if tag.pk is None or any(
            getattr(tag, field_name) != value for field_name, value in desired.items()
        ):
            for field_name, value in desired.items():
                setattr(tag, field_name, value)
            tag.save()
        tags[tag.ghost_id] = tag
    return tags


def _opaque_image_filename(ghost_path, image_payload):
    identity = f"{ghost_path}\0{image_payload.source_sha256}".encode("utf-8")
    opaque_digest = hashlib.sha256(identity).hexdigest()
    return f"ghost-{opaque_digest}.{image_payload.extension}"


def _image_storage_target(image_model, ghost_path, image_payload):
    image = image_model(
        title=PurePosixPath(ghost_path).name,
        width=image_payload.width,
        height=image_payload.height,
    )
    file_field = image_model._meta.get_field("file")
    filename = _opaque_image_filename(ghost_path, image_payload)
    storage_name = file_field.generate_filename(image, filename)
    if len(storage_name) > file_field.max_length:
        raise GhostImportError(f"Stable media name is too long for Wagtail: {storage_name}")
    return image, file_field.storage, storage_name


def _storage_object_matches_payload(storage, name, image_payload):
    expected_size = len(image_payload.data)
    expected_digest = hashlib.sha256(image_payload.data).digest()
    actual_digest = hashlib.sha256()
    actual_size = 0
    try:
        with storage.open(name, "rb") as stored_file:
            while True:
                chunk = stored_file.read(ARCHIVE_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                actual_size += len(chunk)
                if actual_size > expected_size:
                    return False
                actual_digest.update(chunk)
    except Exception as exc:
        raise GhostImportError(f"Could not verify existing media object {name}.") from exc
    return actual_size == expected_size and actual_digest.digest() == expected_digest


def _preflight_images(image_payloads):
    image_model = get_image_model()
    for ghost_path, image_payload in image_payloads.items():
        mapping = (
            GhostImageImport.objects.select_related("image").filter(ghost_path=ghost_path).first()
        )
        image, storage, expected_name = _image_storage_target(
            image_model,
            ghost_path,
            image_payload,
        )
        del image
        if not mapping:
            if storage.exists(expected_name):
                if not _storage_object_matches_payload(
                    storage,
                    expected_name,
                    image_payload,
                ):
                    raise GhostImportError(
                        "Stable media target exists without an import mapping "
                        f"and has unexpected bytes: {expected_name}"
                    )
            continue
        if mapping.source_sha256 != image_payload.source_sha256:
            raise GhostImportError(
                f"Imported image identity changed for {ghost_path}; use a fresh target."
            )
        if mapping.image.file.name != expected_name:
            raise GhostImportError(f"Imported image storage identity changed for {ghost_path}.")
        if not mapping.image.file.storage.exists(mapping.image.file.name):
            raise GhostImportError(f"Imported image file is missing for {ghost_path}.")
        if not _storage_object_matches_payload(
            mapping.image.file.storage,
            mapping.image.file.name,
            image_payload,
        ):
            raise GhostImportError(
                f"Imported image file bytes changed for {ghost_path}."
            )


def _import_images(image_payloads, created_files):
    image_model = get_image_model()
    image_urls = {}
    images_by_path = {}
    for ghost_path, image_payload in sorted(image_payloads.items()):
        mapping = (
            GhostImageImport.objects.select_related("image").filter(ghost_path=ghost_path).first()
        )
        if mapping:
            if mapping.source_sha256 != image_payload.source_sha256:
                raise GhostImportError(
                    f"Imported image identity changed for {ghost_path}; use a fresh target."
                )
            image_urls[ghost_path] = mapping.image.file.url
            images_by_path[ghost_path] = mapping.image
            continue

        image, storage, expected_name = _image_storage_target(
            image_model,
            ghost_path,
            image_payload,
        )
        target_existed = storage.exists(expected_name)
        if target_existed:
            if not _storage_object_matches_payload(
                storage,
                expected_name,
                image_payload,
            ):
                raise GhostImportError(
                    f"Stable media target appeared with unexpected bytes: {expected_name}."
                )
            stored_name = expected_name
        else:
            try:
                stored_name = storage.save(
                    expected_name,
                    ContentFile(image_payload.data),
                )
            except Exception as save_error:
                try:
                    target_now_exists = storage.exists(expected_name)
                except Exception:
                    raise save_error
                if not target_now_exists:
                    raise
                if not _storage_object_matches_payload(
                    storage,
                    expected_name,
                    image_payload,
                ):
                    raise GhostImportError(
                        "Media storage reported failure and left unexpected "
                        f"bytes at {expected_name}."
                    ) from save_error
                # The target was absent immediately before this save under the
                # import DB lock, so treat the verified object as this attempt's
                # file for known-rollback cleanup.
                stored_name = expected_name
                created_files.append((storage, stored_name))
            else:
                created_files.append((storage, stored_name))
                if stored_name != expected_name:
                    raise GhostImportError(
                        "Media storage changed a collision-safe target name "
                        f"unexpectedly: {stored_name}"
                    )

        image.file.name = stored_name
        image.save()
        GhostImageImport.objects.create(
            ghost_path=ghost_path,
            image=image,
            source_sha256=image_payload.source_sha256,
        )
        image_urls[ghost_path] = image.file.url
        images_by_path[ghost_path] = image
    return image_urls, images_by_path


def _cleanup_created_files(created_files):
    files_to_delete = list(reversed(created_files))
    created_files.clear()
    cleanup_failures = 0
    for storage, name in files_to_delete:
        try:
            storage.delete(name)
        except Exception:
            cleanup_failures += 1
    return cleanup_failures


def _preflight_content_identity(record, index=None):
    model = BlogPage if record["type"] == "post" else ContentPage
    other_model = ContentPage if model is BlogPage else BlogPage
    ghost_id = str(record["id"])
    ghost_uuid = _parse_uuid(record.get("uuid"))
    slug = str(record["slug"])

    if other_model.objects.filter(ghost_id=ghost_id).exists():
        raise GhostImportError(f"Ghost ID {ghost_id} already belongs to {other_model.__name__}.")
    if ghost_uuid and other_model.objects.filter(ghost_uuid=ghost_uuid).exists():
        raise GhostImportError(
            f"Ghost UUID {ghost_uuid} already belongs to {other_model.__name__}."
        )

    if index is None:
        if model.objects.filter(ghost_id=ghost_id).exists():
            raise GhostImportError(
                f"Ghost ID {ghost_id} already belongs to a site without this hostname."
            )
        if ghost_uuid and model.objects.filter(ghost_uuid=ghost_uuid).exists():
            raise GhostImportError(f"Ghost UUID {ghost_uuid} already belongs to another site.")
        return

    page = _find_content_page(model, index, ghost_id, slug)
    by_uuid = model.objects.filter(ghost_uuid=ghost_uuid).first() if ghost_uuid else None
    if by_uuid and (page is None or by_uuid.pk != page.pk):
        raise GhostImportError(f"Ghost UUID {ghost_uuid} identifies a different page for {slug}.")
    if page and page.ghost_uuid and page.ghost_uuid != ghost_uuid:
        raise GhostImportError(f"Ghost ID and UUID identify different pages for {slug}.")


def _preflight_site_and_content(payload, hostname, port):
    site = (
        Site.objects.select_related("root_page")
        .filter(
            hostname=hostname,
            port=port,
        )
        .first()
    )
    if site:
        index = site.root_page.specific
        if not isinstance(index, BlogIndexPage):
            raise GhostImportError(
                f"Existing site {hostname}:{port} is not rooted at a BlogIndexPage."
            )
        for record in payload["posts"]:
            _preflight_content_identity(record, index)
        return

    root = Page.get_first_root_node()
    root_slug = slugify(hostname) or "imported-blog"
    if root.get_children().filter(slug=root_slug).exists():
        raise GhostImportError(f"Cannot create site root; sibling slug {root_slug!r} exists.")
    for record in payload["posts"]:
        _preflight_content_identity(record)


def _preflight_alias_redirects(payload, aliases, hostname, port):
    if not aliases:
        return
    site = (
        Site.objects.select_related("root_page")
        .filter(
            hostname=hostname,
            port=port,
        )
        .first()
    )
    index = site.root_page.specific if site else None
    records_by_slug = {str(record["slug"]): record for record in payload["posts"]}

    for old_path, target_slug in aliases.items():
        normalized_path = Redirect.normalise_path(old_path)
        global_collision = Redirect.objects.filter(
            old_path=normalized_path,
            site__isnull=True,
        ).exists()
        if global_collision:
            raise GhostImportError(
                f"Explicit alias {old_path} collides with a global Wagtail redirect."
            )
        if not site:
            continue

        target_record = records_by_slug[target_slug]
        target = _find_content_page(
            BlogPage,
            index,
            str(target_record["id"]),
            target_slug,
        )
        old_slug = old_path.strip("/")
        sibling = index.get_children().filter(slug=old_slug).first()
        if sibling and (target is None or sibling.pk != target.pk):
            raise GhostImportError(f"Explicit alias {old_path} collides with an existing page.")
        existing_redirect = Redirect.objects.filter(
            old_path=normalized_path,
            site=site,
        ).first()
        if existing_redirect and (
            target is None
            or existing_redirect.redirect_page_id != target.pk
            or existing_redirect.redirect_link
            or existing_redirect.redirect_page_route_path
        ):
            raise GhostImportError(f"Explicit alias {old_path} collides with an existing redirect.")


def _preflight_database(payload, image_payloads, aliases, hostname, port):
    _preflight_site_and_content(payload, hostname, port)
    _preflight_alias_redirects(payload, aliases, hostname, port)
    for record in payload["authors"]:
        _upsert_identity(BlogAuthor, record)
    for record in payload["tags"]:
        _upsert_identity(BlogTag, record)
    _preflight_images(image_payloads)


def _lock_ghost_import():
    """Serialize media writes on the stable Wagtail tree root DB row."""

    root_page = Page.get_first_root_node()
    if root_page is None:
        raise GhostImportError("Wagtail has no root page to lock for import.")
    Page.objects.select_for_update().only("pk").get(pk=root_page.pk)


@contextmanager
def _ghost_import_transaction():
    with transaction.atomic():
        _lock_ghost_import()
        yield


def _import_alias_redirects(index, site, aliases):
    for old_path, target_slug in aliases.items():
        target = (
            BlogPage.objects.child_of(index)
            .filter(
                slug=target_slug,
                live=True,
            )
            .first()
        )
        if not target:
            raise GhostImportError(f"Explicit alias {old_path} has no live canonical target.")
        normalized_path = Redirect.normalise_path(old_path)
        redirect, created = Redirect.objects.get_or_create(
            old_path=normalized_path,
            site=site,
            defaults={
                "is_permanent": True,
                "redirect_page": target,
            },
        )
        if not created and (
            redirect.redirect_page_id != target.pk
            or redirect.redirect_link
            or redirect.redirect_page_route_path
        ):
            raise GhostImportError(f"Explicit alias {old_path} changed after preflight.")
        if not redirect.is_permanent:
            redirect.is_permanent = True
            redirect.save(update_fields=["is_permanent"])


def _get_or_create_site(
    hostname,
    port,
    site_name,
    site_description,
    site_author,
):
    site = (
        Site.objects.select_related("root_page")
        .filter(
            hostname=hostname,
            port=port,
        )
        .first()
    )
    if site:
        root_page = site.root_page.specific
        if not isinstance(root_page, BlogIndexPage):
            raise GhostImportError(
                f"Existing site {hostname}:{port} is not rooted at a BlogIndexPage."
            )
        if site.site_name != site_name:
            site.site_name = site_name
            site.save(update_fields=["site_name"])
        identity_changed = (
            root_page.intro != site_description or root_page.default_author_name != site_author
        )
        if identity_changed:
            root_page.intro = site_description
            root_page.default_author_name = site_author
            root_page.save_revision().publish()
        return site, root_page

    root = Page.get_first_root_node()
    root_slug = slugify(hostname) or "imported-blog"
    if root.get_children().filter(slug=root_slug).exists():
        raise GhostImportError(f"Cannot create site root; sibling slug {root_slug!r} exists.")

    index = BlogIndexPage(
        title=site_name,
        slug=root_slug,
        intro=site_description,
        default_author_name=site_author,
        live=True,
    )
    root.add_child(instance=index)
    index.save_revision().publish()
    site = Site.objects.create(
        hostname=hostname,
        port=port,
        site_name=site_name,
        root_page=index,
        is_default_site=False,
    )
    return site, index


def _site_identity_from_export(
    payload,
    *,
    site_name=None,
    site_description=None,
    site_author=None,
):
    ghost_settings = payload.get("settings") or {}
    resolved_name = (
        site_name if site_name is not None else ghost_settings.get("title") or settings.SITE_NAME
    )
    resolved_description = (
        site_description
        if site_description is not None
        else ghost_settings.get("description") or settings.SITE_DESCRIPTION
    )
    if site_author is None:
        author_names = {
            str(record.get("name") or "").strip()
            for record in payload["authors"]
            if str(record.get("name") or "").strip()
        }
        resolved_author = (
            next(iter(author_names)) if len(author_names) == 1 else settings.SITE_AUTHOR
        )
    else:
        resolved_author = site_author

    resolved_name = str(resolved_name).strip()
    resolved_description = str(resolved_description).strip()
    resolved_author = str(resolved_author).strip()
    if not resolved_name or len(resolved_name) > 255:
        raise GhostImportError("Site name must contain between 1 and 255 characters.")
    if len(resolved_author) > 255:
        raise GhostImportError("Site author must contain at most 255 characters.")
    return resolved_name, resolved_description, resolved_author


def _related_ids(rows, post_id, relation_key):
    return [
        str(row[relation_key])
        for row in sorted(
            (row for row in rows if str(row.get("post_id")) == post_id),
            key=lambda row: int(row.get("sort_order") or 0),
        )
    ]


def _find_content_page(model, index, ghost_id, slug):
    by_id = model.objects.filter(ghost_id=ghost_id).first()
    sibling = index.get_children().filter(slug=slug).first()
    sibling_specific = sibling.specific if sibling else None
    if sibling_specific and not isinstance(sibling_specific, model):
        raise GhostImportError(f"Sibling slug {slug!r} has the wrong page type.")
    if by_id and sibling_specific and by_id.pk != sibling_specific.pk:
        raise GhostImportError(f"Ghost ID and slug identify different pages for {slug}.")
    page = by_id or sibling_specific
    if page and page.get_parent().pk != index.pk:
        raise GhostImportError(f"Ghost page {ghost_id} belongs to a different site root.")
    if page and page.ghost_id and page.ghost_id != ghost_id:
        raise GhostImportError(f"Slug {slug!r} belongs to a different Ghost ID.")
    return page


def _desired_ghost_fields(record):
    return {
        "ghost_id": str(record["id"]),
        "ghost_uuid": _parse_uuid(record.get("uuid")),
        "ghost_created_at": _parse_timestamp(
            record.get("created_at"),
            "created_at",
            required=True,
        ),
        "ghost_updated_at": _parse_timestamp(
            record.get("updated_at"),
            "updated_at",
            required=True,
        ),
        "ghost_published_at": _parse_timestamp(
            record.get("published_at"),
            "published_at",
        ),
    }


def _raw_html_body_matches(page, sanitized_html):
    raw_data = getattr(page.body, "raw_data", [])
    return (
        len(raw_data) == 1
        and raw_data[0].get("type") == "raw_html"
        and raw_data[0].get("value") == sanitized_html
    )


def _publication_state_matches(page, is_published, published_at):
    if page.live != is_published:
        return False
    if not is_published:
        return True
    return page.first_published_at == published_at and page.last_published_at == published_at


def _save_page_state(page, is_published, published_at):
    revision = page.save_revision()
    if is_published:
        revision.publish()
        Page.objects.filter(pk=page.pk).update(
            first_published_at=published_at,
            last_published_at=published_at,
        )
        page.first_published_at = published_at
        page.last_published_at = published_at
        page.live = True
    else:
        if page.live:
            page.unpublish()
        page.live = False


def _import_record(
    record,
    index,
    image_urls,
    images_by_path,
    authors,
    tags,
    payload,
    inline_data_uri_paths,
):
    ghost_id = str(record["id"])
    slug = str(record["slug"])
    title = str(record.get("title") or slug)
    status = record["status"]
    published_at = _parse_timestamp(record.get("published_at"), "published_at")
    is_published = status == "published"
    if is_published and published_at is None:
        raise GhostImportError(f"Published Ghost content {ghost_id} has no published_at.")

    sanitized_html = _rewrite_and_sanitize_html(
        record.get("html") or "",
        image_urls,
        inline_data_uri_paths,
    )
    ghost_fields = _desired_ghost_fields(record)
    if record["type"] == "post":
        feature_path = _feature_image_path(record)
        feature_image = images_by_path.get(feature_path) if feature_path else None
        if feature_path and feature_image is None:
            raise GhostImportError(f"No imported feature image mapping for {feature_path}.")
        page = _find_content_page(BlogPage, index, ghost_id, slug)
        is_new = page is None
        if is_new:
            page = BlogPage(title=title, slug=slug)
        excerpt = str(record.get("custom_excerpt") or "")
        desired_fields = {
            "title": title,
            "slug": slug,
            "is_featured": _ghost_featured_value(record),
            "abstract": excerpt,
            "search_description": excerpt[:255],
            "featured_image_id": feature_image.pk if feature_image else None,
            "social_image_id": feature_image.pk if feature_image else None,
            "date": (
                published_at
                or _parse_timestamp(
                    record.get("created_at"),
                    "created_at",
                    required=True,
                )
            ).date(),
            **ghost_fields,
        }
        author_ids = _related_ids(payload["posts_authors"], ghost_id, "author_id")
        tag_ids = _related_ids(payload["posts_tags"], ghost_id, "tag_id")
        try:
            desired_authors = [authors[author_id] for author_id in author_ids]
            desired_tags = [tags[tag_id] for tag_id in tag_ids]
        except KeyError as exc:
            raise GhostImportError(
                f"Ghost relation for {ghost_id} references a missing identity."
            ) from exc
        fields_changed = is_new or any(
            getattr(page, field_name) != value for field_name, value in desired_fields.items()
        )
        body_changed = is_new or not _raw_html_body_matches(page, sanitized_html)
        relations_changed = is_new or (
            set(page.authors.values_list("pk", flat=True))
            != {author.pk for author in desired_authors}
            or set(page.tags.values_list("pk", flat=True)) != {tag.pk for tag in desired_tags}
        )
        publication_changed = is_new or not _publication_state_matches(
            page,
            is_published,
            published_at,
        )
        if not (fields_changed or body_changed or relations_changed or publication_changed):
            return "unchanged"

        for field_name, value in desired_fields.items():
            setattr(page, field_name, value)
        if body_changed:
            page.body = [("raw_html", sanitized_html)]
        if is_new:
            page.live = False
            index.add_child(instance=page)
        else:
            page.save()
        if relations_changed:
            page.authors.set(desired_authors)
            page.tags.set(desired_tags)
            page.save()
        _save_page_state(page, is_published, published_at)
        return "created" if is_new else "updated"

    page = _find_content_page(ContentPage, index, ghost_id, slug)
    is_new = page is None
    if is_new:
        page = ContentPage(title=title, slug=slug)
    desired_fields = {
        "title": title,
        "slug": slug,
        "search_description": str(record.get("custom_excerpt") or "")[:255],
        **ghost_fields,
    }
    fields_changed = is_new or any(
        getattr(page, field_name) != value for field_name, value in desired_fields.items()
    )
    body_changed = is_new or not _raw_html_body_matches(page, sanitized_html)
    publication_changed = is_new or not _publication_state_matches(
        page,
        is_published,
        published_at,
    )
    if not (fields_changed or body_changed or publication_changed):
        return "unchanged"

    for field_name, value in desired_fields.items():
        setattr(page, field_name, value)
    if body_changed:
        page.body = [("raw_html", sanitized_html)]
    if is_new:
        page.live = False
        index.add_child(instance=page)
    else:
        page.save()
    _save_page_state(page, is_published, published_at)
    return "created" if is_new else "updated"


def import_ghost_export(
    export_path,
    archive_path,
    *,
    hostname,
    port=443,
    site_name=None,
    site_description=None,
    site_author=None,
    dry_run=False,
):
    payload = _load_export(export_path)
    site_name, site_description, site_author = _site_identity_from_export(
        payload,
        site_name=site_name,
        site_description=site_description,
        site_author=site_author,
    )
    aliases = _active_aliases(payload)
    required_paths = _referenced_image_paths(payload)
    archive_image_payloads = _read_required_images(archive_path, required_paths)
    archive_work = _image_processing_work(archive_image_payloads)
    (
        inline_image_payloads,
        inline_data_uri_paths,
        inline_work,
    ) = _inline_png_payloads(
        payload,
        prior_work=archive_work,
    )
    image_payloads = {
        **archive_image_payloads,
        **inline_image_payloads,
    }
    _validate_aggregate_image_budget(
        image_payloads,
        _combine_image_processing_work(archive_work, inline_work),
    )
    _validate_content_records(
        payload,
        image_payloads,
        inline_data_uri_paths,
    )

    summary = ImportSummary(
        posts=sum(record["type"] == "post" for record in payload["posts"]),
        pages=sum(record["type"] == "page" for record in payload["posts"]),
        published_posts=sum(
            record["type"] == "post" and record["status"] == "published"
            for record in payload["posts"]
        ),
        draft_posts=sum(
            record["type"] == "post" and record["status"] == "draft" for record in payload["posts"]
        ),
        authors=len(payload["authors"]),
        tags=len(payload["tags"]),
        images=len(image_payloads),
        archive_images=len(archive_image_payloads),
        inline_images=len(inline_image_payloads),
        redirects=len(aliases),
    )

    if not hostname or "/" in hostname:
        raise GhostImportError("A valid site hostname is required.")
    if not 1 <= port <= 65535:
        raise GhostImportError("Site port must be between 1 and 65535.")
    if dry_run:
        _preflight_database(
            payload,
            image_payloads,
            aliases,
            hostname,
            port,
        )
        return summary
    created_files = []
    body_completed = False
    try:
        with _ghost_import_transaction():
            try:
                _preflight_database(
                    payload,
                    image_payloads,
                    aliases,
                    hostname,
                    port,
                )
                site, index = _get_or_create_site(
                    hostname,
                    port,
                    site_name,
                    site_description,
                    site_author,
                )
                authors = _import_authors(payload)
                tags = _import_tags(payload)
                image_urls, images_by_path = _import_images(
                    image_payloads,
                    created_files,
                )
                for record in payload["posts"]:
                    result = _import_record(
                        record,
                        index,
                        image_urls,
                        images_by_path,
                        authors,
                        tags,
                        payload,
                        inline_data_uri_paths,
                    )
                    if result == "created":
                        summary.created_pages += 1
                    elif result == "updated":
                        summary.updated_pages += 1
                    elif result == "unchanged":
                        summary.unchanged_pages += 1
                    else:
                        raise GhostImportError(f"Unexpected import result: {result!r}.")
                _import_alias_redirects(index, site, aliases)
                body_completed = True
            except Exception as import_error:
                # Keep the database row lock until all proven-new media objects
                # are removed, so another importer cannot race this rollback.
                cleanup_failures = _cleanup_created_files(created_files)
                if cleanup_failures:
                    raise GhostImportError(
                        f"Import failed and {cleanup_failures} new media files "
                        "could not be removed."
                    ) from import_error
                raise
    except Exception as import_error:
        if body_completed:
            # atomic().__exit__ can report a lost commit acknowledgement after
            # PostgreSQL committed. Preserve deterministic media for either
            # outcome: committed mappings still work, while a rolled-back
            # transaction is recovered on an identical retry after byte checks.
            raise GhostImportError(
                "Ghost import database commit outcome is unknown; preserved "
                f"{len(created_files)} deterministic media objects. Retry the "
                "identical import to reconcile database and media state."
            ) from import_error
        raise
    return summary
