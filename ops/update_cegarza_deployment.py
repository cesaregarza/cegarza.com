#!/usr/bin/env python3
"""Update the dedicated GitOps values without repeating one-time replacement."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

CANONICAL_SELECTOR = "cegarza-blog"
CANONICAL_REPOSITORY = "registry.digitalocean.com/sendouq/cegarza-blog"
CANONICAL_SETTINGS = "cegarza_site.settings"
LEGACY_SELECTOR = "splat" + "top-blog"
LEGACY_REPOSITORY = f"registry.digitalocean.com/sendouq/{LEGACY_SELECTOR}"
LEGACY_SETTINGS = f"{LEGACY_SELECTOR.replace('-', '')}.settings"
DUAL_SELECTORS = [LEGACY_SELECTOR, CANONICAL_SELECTOR]
TAG_PATTERN = re.compile(r"v\d+\.\d+\.\d+")
DIGEST_PATTERN = re.compile(r"sha256:[a-f0-9]{64}")


def _rollout_phase(values: dict[str, Any]) -> str:
    blog = values["blog"]
    signature = (
        blog["image"]["repository"],
        blog["env"]["DJANGO_SETTINGS_MODULE"],
        blog["selectorName"],
        blog["replaceOnSync"],
        list(values["networkPolicy"]["selectorNames"]),
    )
    phases = (
        (
            (
                LEGACY_REPOSITORY,
                LEGACY_SETTINGS,
                LEGACY_SELECTOR,
                False,
                DUAL_SELECTORS,
            ),
            "substrate",
        ),
        (
            (
                CANONICAL_REPOSITORY,
                CANONICAL_SETTINGS,
                CANONICAL_SELECTOR,
                True,
                DUAL_SELECTORS,
            ),
            "activation",
        ),
        (
            (
                CANONICAL_REPOSITORY,
                CANONICAL_SETTINGS,
                CANONICAL_SELECTOR,
                False,
                [CANONICAL_SELECTOR],
            ),
            "steady-state",
        ),
    )
    for expected, phase in phases:
        if signature == expected:
            return phase
    raise ValueError(
        "cegarza-blog values are not one of the safe substrate, activation, "
        f"or steady-state phases: {signature!r}"
    )


def update_values(path: Path, *, tag: str, digest: str) -> str:
    if TAG_PATTERN.fullmatch(tag) is None:
        raise ValueError(f"invalid image tag: {tag}")
    if DIGEST_PATTERN.fullmatch(digest) is None:
        raise ValueError(f"invalid image digest: {digest}")

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    with path.open(encoding="utf-8") as values_stream:
        values = yaml.load(values_stream)
    if not isinstance(values, dict):
        raise ValueError(f"{path} must contain one YAML mapping")

    previous_phase = _rollout_phase(values)
    blog = values["blog"]
    blog["image"]["repository"] = CANONICAL_REPOSITORY
    blog["image"]["tag"] = tag
    blog["image"]["digest"] = digest
    blog["env"]["DJANGO_SETTINGS_MODULE"] = CANONICAL_SETTINGS

    if previous_phase == "substrate":
        blog["selectorName"] = CANONICAL_SELECTOR
        blog["replaceOnSync"] = True

    with path.open("w", encoding="utf-8") as values_stream:
        yaml.dump(values, values_stream)
    return previous_phase


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("values_file", type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--digest", required=True)
    args = parser.parse_args()

    previous_phase = update_values(
        args.values_file,
        tag=args.tag,
        digest=args.digest,
    )
    print(
        f"Updated {args.values_file} with {CANONICAL_REPOSITORY}@{args.digest} "
        f"({args.tag}); previous rollout phase: {previous_phase}"
    )


if __name__ == "__main__":
    main()
