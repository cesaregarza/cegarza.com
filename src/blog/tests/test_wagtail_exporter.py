from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from django.db import connection

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "ops" / "export_wagtail_bundle.py"
SPEC = importlib.util.spec_from_file_location("export_wagtail_bundle", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {SCRIPT_PATH}")
EXPORT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT_MODULE)


def test_bundle_export_uses_repeatable_read_only_postgres_transaction() -> None:
    with (
        patch.object(connection, "vendor", "postgresql"),
        patch("django.db.transaction.atomic") as atomic,
        patch.object(connection, "cursor") as cursor,
        patch.object(
            EXPORT_MODULE,
            "_build_bundle_snapshot",
            return_value=("manifest", "media"),
        ) as snapshot,
    ):
        assert EXPORT_MODULE.build_bundle("source.example", 443, "source-primary") == (
            "manifest",
            "media",
        )

    atomic.return_value.__enter__.assert_called_once_with()
    cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    )
    snapshot.assert_called_once_with("source.example", 443, "source-primary")


def test_bundle_export_rejects_non_postgres_sources() -> None:
    with (
        patch.object(connection, "vendor", "sqlite"),
        pytest.raises(EXPORT_MODULE.ExportError, match="requires PostgreSQL"),
    ):
        EXPORT_MODULE.build_bundle("source.example", 443, "source-primary")
