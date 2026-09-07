from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_user_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep tests from reading or writing the real user's secret directory."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
