#!/usr/bin/env python3
"""Regression tests for Yandex Forms discovery helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import discover_forms


def test_extract_form_ids_from_file_finds_supported_urls(tmp_path: Path) -> None:
    path = tmp_path / "message.txt"
    path.write_text(
        "https://forms.yandex.ru/u/abc123/\n"
        "https://forms.yandex.ru/surveys/xyz789/\n",
        encoding="utf-8",
    )

    assert discover_forms.extract_form_ids_from_file(path) == {"abc123", "xyz789"}


def test_scan_for_forms_filters_by_account(tmp_path: Path) -> None:
    msg_dir = tmp_path / "incoming" / "2026-03-12_ctiis_uid15"
    msg_dir.mkdir(parents=True)
    (msg_dir / "email_body.txt").write_text(
        "See https://forms.yandex.ru/u/form123/",
        encoding="utf-8",
    )
    other_dir = tmp_path / "archive" / "2026-03-12_bdi_uid16"
    other_dir.mkdir(parents=True)
    (other_dir / "email_body.txt").write_text(
        "See https://forms.yandex.ru/u/form999/",
        encoding="utf-8",
    )

    found = discover_forms.scan_for_forms(tmp_path, account="ctiis")

    assert found == {
        "form123": {
            "sources": ["incoming/2026-03-12_ctiis_uid15/email_body.txt"],
            "first_seen": "2026-03-12T00:00:00",
            "accounts": ["ctiis"],
        }
    }


def test_discover_forms_merges_registry_and_api_stats(monkeypatch, tmp_path: Path) -> None:
    saved = {}

    monkeypatch.setattr(
        discover_forms,
        "load_registry",
        lambda _data_dir: {"forms": {"known": {"discovered_from": "seed"}}},
    )
    monkeypatch.setattr(
        discover_forms,
        "scan_for_forms",
        lambda _data_dir, _account: {
            "newform": {"first_seen": "2026-03-12T00:00:00", "accounts": ["acct"]}
        },
    )
    monkeypatch.setattr(
        discover_forms,
        "get_form_info",
        lambda form_id, _token: {"title": f"Form {form_id}", "status": "active"},
    )
    monkeypatch.setattr(
        discover_forms,
        "get_monthly_totals",
        lambda _form_id, _token: {"2026-03": 5},
    )
    monkeypatch.setattr(
        discover_forms,
        "save_registry",
        lambda _data_dir, registry: saved.setdefault("registry", registry),
    )

    result = discover_forms.discover_forms("acct", tmp_path, "token", update_registry=True)

    assert result["forms"]["known"]["api_accessible"] is True
    assert result["forms"]["newform"]["title"] == "Form newform"
    assert saved["registry"]["forms"]["newform"]["accounts"] == ["acct"]
    assert result["registry_path"].endswith("forms/registry.json")
