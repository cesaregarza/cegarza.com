from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from ruamel.yaml import YAML

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "ops" / "update_cegarza_deployment.py"
)
SPEC = importlib.util.spec_from_file_location(
    "update_cegarza_deployment",
    SCRIPT_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {SCRIPT_PATH}")
UPDATE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATE_MODULE)
YAML_PARSER = YAML(typ="safe")


def _values(phase: str) -> dict:
    old_selector = "splat" + "top-blog"
    old_repository = f"registry.digitalocean.com/sendouq/{old_selector}"
    old_settings = f"{old_selector.replace('-', '')}.settings"
    phases = {
        "substrate": {
            "repository": old_repository,
            "settings": old_settings,
            "selector": old_selector,
            "replace": False,
            "network": [old_selector, "cegarza-blog"],
        },
        "activation": {
            "repository": "registry.digitalocean.com/sendouq/cegarza-blog",
            "settings": "cegarza_site.settings",
            "selector": "cegarza-blog",
            "replace": True,
            "network": [old_selector, "cegarza-blog"],
        },
        "steady-state": {
            "repository": "registry.digitalocean.com/sendouq/cegarza-blog",
            "settings": "cegarza_site.settings",
            "selector": "cegarza-blog",
            "replace": False,
            "network": ["cegarza-blog"],
        },
    }
    selected = phases[phase]
    return {
        "blog": {
            "selectorName": selected["selector"],
            "replaceOnSync": selected["replace"],
            "image": {
                "repository": selected["repository"],
                "tag": "v1.0.36",
                "digest": f"sha256:{'a' * 64}",
            },
            "env": {"DJANGO_SETTINGS_MODULE": selected["settings"]},
        },
        "networkPolicy": {"selectorNames": selected["network"]},
    }


def _write_values(path: Path, values: dict) -> None:
    yaml = YAML()
    with path.open("w", encoding="utf-8") as values_stream:
        yaml.dump(values, values_stream)


@pytest.mark.parametrize(
    ("phase", "expected_replace"),
    [
        ("substrate", True),
        ("activation", True),
        ("steady-state", False),
    ],
)
def test_update_preserves_one_time_replacement_state(
    tmp_path: Path,
    phase: str,
    expected_replace: bool,
) -> None:
    values_path = tmp_path / "values.yaml"
    _write_values(values_path, _values(phase))
    digest = f"sha256:{'b' * 64}"

    assert (
        UPDATE_MODULE.update_values(
            values_path,
            tag="v1.0.37",
            digest=digest,
        )
        == phase
    )

    updated = YAML_PARSER.load(values_path)
    blog = updated["blog"]
    assert blog["image"] == {
        "repository": "registry.digitalocean.com/sendouq/cegarza-blog",
        "tag": "v1.0.37",
        "digest": digest,
    }
    assert blog["env"]["DJANGO_SETTINGS_MODULE"] == "cegarza_site.settings"
    assert blog["selectorName"] == "cegarza-blog"
    assert blog["replaceOnSync"] is expected_replace
    assert f"    digest: {digest}\n" in values_path.read_text(encoding="utf-8")


def test_update_rejects_an_unordered_rollout_state(tmp_path: Path) -> None:
    values_path = tmp_path / "values.yaml"
    values = _values("steady-state")
    values["networkPolicy"]["selectorNames"].insert(0, "splat" + "top-blog")
    _write_values(values_path, values)
    original = values_path.read_bytes()

    with pytest.raises(ValueError, match="safe substrate"):
        UPDATE_MODULE.update_values(
            values_path,
            tag="v1.0.37",
            digest=f"sha256:{'b' * 64}",
        )

    assert values_path.read_bytes() == original
