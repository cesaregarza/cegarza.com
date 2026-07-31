#!/usr/bin/env python3
"""Fail when tracked paths or file contents retain the retired site identity."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _tracked_paths():
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [
        Path(raw.decode("utf-8"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def main():
    product = "sp" + "lat" + "top"
    stem = "sp" + "lat"
    forbidden = (
        product,
        f"{stem}.top",
        f"{stem}-top",
        f"{stem} top",
    )
    forbidden_bytes = tuple(value.encode() for value in forbidden)
    failures = []
    for path in _tracked_paths():
        lowered_path = path.as_posix().lower()
        if any(value in lowered_path for value in forbidden):
            failures.append(f"path: {path}")
            continue
        try:
            content = path.read_bytes().lower()
        except OSError as exc:
            failures.append(f"unreadable: {path}: {exc}")
            continue
        if any(value in content for value in forbidden_bytes):
            failures.append(f"content: {path}")
    if failures:
        details = "\n".join(failures)
        raise SystemExit(f"Retired identity remains in tracked files:\n{details}")


if __name__ == "__main__":
    main()
