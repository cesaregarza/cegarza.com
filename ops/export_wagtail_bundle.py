#!/usr/bin/env python3
"""Version-compatible, read-only exporter for a small Wagtail blog site."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

for import_root in (Path.cwd(), Path(__file__).resolve().parents[1] / "src"):
    if import_root.is_dir():
        sys.path.insert(0, str(import_root))

MAX_IMAGES = 200
MAX_PAGES = 100
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 96 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024
NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SCHEMA_VERSION = 1


class ExportError(ValueError):
    pass


def _canonical_json(payload):
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _snapshot_sha256(snapshot):
    return hashlib.sha256(_canonical_json(snapshot)).hexdigest()


def _body_prep_value(body):
    return body.stream_block.get_prep_value(body)


def _snapshot(page):
    page = page.specific
    return {
        "title": page.title,
        "slug": page.slug,
        "seo_title": page.seo_title or "",
        "search_description": page.search_description or "",
        "show_in_menus": bool(page.show_in_menus),
        "date": page.date.isoformat() if page.date else None,
        "is_featured": bool(getattr(page, "is_featured", False)),
        "abstract": getattr(page, "abstract", "") or "",
        "body": _body_prep_value(page.body),
        "featured_image_id": getattr(page, "featured_image_id", None),
        "social_image_id": getattr(page, "social_image_id", None),
    }


def _revision_state(revision):
    snapshot = _snapshot(revision.as_object())
    return {
        "snapshot": snapshot,
        "sha256": _snapshot_sha256(snapshot),
    }


def _read_file(file_field):
    payload = io.BytesIO()
    total = 0
    with file_field.storage.open(file_field.name, "rb") as source_file:
        while True:
            chunk = source_file.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise ExportError(f"Image {file_field.name} exceeds the per-file limit.")
            payload.write(chunk)
    if total < 1:
        raise ExportError(f"Image {file_field.name} is empty.")
    return payload.getvalue()


def _unsigned_url(url):
    if not url:
        return ""
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _source_urls(image):
    from django.conf import settings

    candidates = {
        _unsigned_url(image.file.url),
        f"/media/{image.file.name.lstrip('/')}",
    }
    media_url = str(getattr(settings, "MEDIA_URL", "") or "")
    if media_url:
        candidates.add(f"{media_url.rstrip('/')}/{image.file.name.lstrip('/')}")
    return sorted(url for url in candidates if url)


def _restriction_type(page):
    from wagtail.models import PageViewRestriction

    exact = list(PageViewRestriction.objects.filter(page=page))
    effective = list(page.get_view_restrictions())
    if any(restriction.page_id != page.pk for restriction in effective):
        raise ExportError(
            f"Page {page.pk} inherits an ancestor restriction, which is unsupported."
        )
    if not exact:
        return "none"
    if len(exact) != 1 or exact[0].restriction_type != PageViewRestriction.PASSWORD:
        raise ExportError(f"Page {page.pk} has an unsupported restriction.")
    return "password"


def _site_and_pages(hostname, port):
    from wagtail.models import Site

    from blog.models import BlogPage

    try:
        site = Site.objects.get(hostname=hostname, port=port)
    except Site.DoesNotExist as exc:
        raise ExportError("Source site was not found.") from exc
    pages = list(
        BlogPage.objects.descendant_of(site.root_page)
        .order_by("path")
        .select_related("live_revision")
    )
    if not pages or len(pages) > MAX_PAGES:
        raise ExportError("Source page count is empty or exceeds the export limit.")
    return site, pages


def build_bundle(hostname, port, namespace):
    from django.db import connection, transaction

    if connection.vendor != "postgresql":
        raise ExportError("Atomic bundle export requires PostgreSQL.")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
        return _build_bundle_snapshot(hostname, port, namespace)


def _build_bundle_snapshot(hostname, port, namespace):
    from django.utils import timezone
    from wagtail.images import get_image_model

    site, pages = _site_and_pages(hostname, port)
    image_model = get_image_model()
    images = list(image_model.objects.order_by("pk"))
    if len(images) > MAX_IMAGES:
        raise ExportError("Source image count exceeds the export limit.")

    image_entries = []
    media_payloads = []
    total_image_bytes = 0
    for image in images:
        data = _read_file(image.file)
        total_image_bytes += len(data)
        if total_image_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise ExportError("Source images exceed the aggregate export limit.")
        source_sha256 = hashlib.sha256(data).hexdigest()
        filename = PurePosixPath(image.file.name).name
        member = f"media/{image.pk}/{source_sha256}/{filename}"
        image_entries.append(
            {
                "source_image_id": image.pk,
                "source_name": image.file.name,
                "source_urls": _source_urls(image),
                "filename": filename,
                "member": member,
                "title": image.title or filename,
                "sha256": source_sha256,
                "size": len(data),
                "width": image.width,
                "height": image.height,
            }
        )
        media_payloads.append((member, data))

    page_entries = []
    for page in pages:
        if not page.live or page.live_revision is None:
            raise ExportError(f"Page {page.pk} has no published revision.")
        live = _revision_state(page.live_revision)
        latest_revision = page.get_latest_revision()
        draft = None
        if latest_revision and latest_revision.pk != page.live_revision_id:
            candidate = _revision_state(latest_revision)
            if candidate["sha256"] != live["sha256"]:
                draft = candidate
        if page.first_published_at is None or page.last_published_at is None:
            raise ExportError(f"Page {page.pk} is missing publication timestamps.")
        page_entries.append(
            {
                "source_page_id": page.pk,
                "live": live,
                "draft": draft,
                "first_published_at": page.first_published_at.isoformat(),
                "last_published_at": page.last_published_at.isoformat(),
                "restriction": {"type": _restriction_type(page)},
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_namespace": namespace,
        "source_index_page_id": site.root_page_id,
        "exported_at": timezone.now().isoformat(),
        "pages": page_entries,
        "images": image_entries,
    }
    return manifest, media_payloads


def _tar_member(name, data):
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mode = 0o600
    member.uid = 0
    member.gid = 0
    member.uname = ""
    member.gname = ""
    member.mtime = 0
    return member


def write_bundle(output_path, manifest, media_payloads):
    path = Path(output_path)
    descriptor = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output_file:
            descriptor = None
            with tarfile.open(
                fileobj=output_file,
                mode="w:gz",
                format=tarfile.USTAR_FORMAT,
            ) as archive:
                manifest_data = _canonical_json(manifest)
                archive.addfile(
                    _tar_member("manifest.json", manifest_data),
                    io.BytesIO(manifest_data),
                )
                for name, data in media_payloads:
                    archive.addfile(_tar_member(name, data), io.BytesIO(data))
        os.chmod(path, 0o600)
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def stream_restriction_secret(hostname, port, source_page_id):
    from wagtail.models import PageViewRestriction

    if sys.stdout.isatty():
        raise ExportError("Restriction secrets may only be written to a non-interactive pipe.")
    if os.environ.get("WAGTAIL_RESTRICTION_SECRET_STREAM") != "1":
        raise ExportError("Restriction secret streaming is not explicitly enabled.")
    site, pages = _site_and_pages(hostname, port)
    del site
    page_ids = {page.pk for page in pages}
    if source_page_id not in page_ids:
        raise ExportError("Requested page is outside the selected source site.")
    restrictions = list(PageViewRestriction.objects.filter(page_id=source_page_id))
    if len(restrictions) != 1 or restrictions[0].restriction_type != "password":
        raise ExportError("Requested page does not have one password restriction.")
    if not restrictions[0].password:
        raise ExportError("Requested page restriction password is empty.")
    sys.stdout.write(restrictions[0].password)
    sys.stdout.flush()


def _parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    bundle = subparsers.add_parser("bundle")
    bundle.add_argument("--hostname", required=True)
    bundle.add_argument("--port", type=int, required=True)
    bundle.add_argument("--source-namespace", required=True)
    bundle.add_argument("--output", required=True)
    secret = subparsers.add_parser("restriction-secret")
    secret.add_argument("--hostname", required=True)
    secret.add_argument("--port", type=int, required=True)
    secret.add_argument("--source-page-id", type=int, required=True)
    return parser


def main():
    import django

    arguments = _parser().parse_args()
    django.setup()
    if arguments.command == "bundle":
        if not NAMESPACE_PATTERN.fullmatch(arguments.source_namespace):
            raise ExportError("source_namespace is invalid.")
        manifest, media_payloads = build_bundle(
            arguments.hostname,
            arguments.port,
            arguments.source_namespace,
        )
        write_bundle(arguments.output, manifest, media_payloads)
        print(
            json.dumps(
                {
                    "images": len(manifest["images"]),
                    "pages": len(manifest["pages"]),
                    "restricted_pages": sum(
                        page["restriction"]["type"] == "password"
                        for page in manifest["pages"]
                    ),
                    "draft_pages": sum(page["draft"] is not None for page in manifest["pages"]),
                },
                sort_keys=True,
            )
        )
        return
    stream_restriction_secret(
        arguments.hostname,
        arguments.port,
        arguments.source_page_id,
    )


if __name__ == "__main__":
    try:
        main()
    except ExportError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
