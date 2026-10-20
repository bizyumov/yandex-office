"""Cross-process token-file transaction regressions for issue #74."""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import threading
import time

import pytest


def _process_context():
    if "fork" in multiprocessing.get_all_start_methods():
        return multiprocessing.get_context("fork")
    return multiprocessing.get_context("spawn")


def _join_process(process) -> None:
    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)


def _crash_while_serializing(token_path: str) -> None:
    """Terminate after the writer has created its private temporary file."""

    from common import auth

    auth.json.dump = lambda *args, **kwargs: os._exit(74)
    auth.save_token_file(token_path, {"email": "fixture@example.invalid"})


def _update_token_in_process(token_path: str, key: str, start) -> None:
    """Apply one delayed mutation from a separate process."""

    from common import auth

    start.wait(timeout=5)

    def mutate(token_data, _checkpoint):
        time.sleep(0.05)
        token_data[key] = {"client_id": "client", "access_token": key}
        return token_data

    auth.update_token_file(token_path, mutate)


def test_legacy_temp_residue_does_not_block_or_get_deleted(tmp_path):
    from common import auth

    token_path = tmp_path / "account.token"
    token_path.write_text("{}", encoding="utf-8")
    legacy_temp = token_path.with_suffix(".tmp")
    legacy_temp.write_text("unowned residue", encoding="utf-8")

    auth.save_token_file(token_path, {"email": "fixture@example.invalid"})

    assert json.loads(token_path.read_text(encoding="utf-8")) == {
        "email": "fixture@example.invalid"
    }
    assert legacy_temp.read_text(encoding="utf-8") == "unowned residue"


def test_abrupt_writer_residue_does_not_block_next_save(tmp_path):
    from common import auth

    token_path = tmp_path / "account.token"
    token_path.write_text('{"email": "original@example.invalid"}\n', encoding="utf-8")
    original = token_path.read_bytes()
    context = _process_context()
    process = context.Process(target=_crash_while_serializing, args=(str(token_path),))

    process.start()
    _join_process(process)

    assert process.exitcode == 74
    assert token_path.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) or list(tmp_path.glob(".*.tmp"))

    auth.save_token_file(token_path, {"email": "replacement@example.invalid"})

    assert json.loads(token_path.read_text(encoding="utf-8")) == {
        "email": "replacement@example.invalid"
    }


def test_concurrent_transaction_updates_preserve_both_changes(tmp_path):
    from common import auth

    token_path = tmp_path / "account.token"
    token_path.write_text('{"email": "fixture@example.invalid"}\n', encoding="utf-8")
    start = threading.Event()
    errors: list[BaseException] = []

    def worker(key: str) -> None:
        try:
            start.wait(timeout=5)

            def mutate(token_data, _checkpoint):
                time.sleep(0.05)
                token_data[key] = {"client_id": "client", "access_token": key}
                return token_data

            auth.update_token_file(token_path, mutate)
        except BaseException as exc:  # Captured for assertion in the test thread.
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("office-core-1",)),
        threading.Thread(target=worker, args=("office-core-2",)),
    ]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    stored = json.loads(token_path.read_text(encoding="utf-8"))
    assert stored["office-core-1"]["access_token"] == "office-core-1"
    assert stored["office-core-2"]["access_token"] == "office-core-2"


def test_cross_process_transaction_updates_preserve_both_changes(tmp_path):
    token_path = tmp_path / "account.token"
    token_path.write_text('{"email": "fixture@example.invalid"}\n', encoding="utf-8")
    context = _process_context()
    start = context.Event()
    processes = [
        context.Process(
            target=_update_token_in_process,
            args=(str(token_path), "office-core-1", start),
        ),
        context.Process(
            target=_update_token_in_process,
            args=(str(token_path), "office-core-2", start),
        ),
    ]

    for process in processes:
        process.start()
    start.set()
    for process in processes:
        _join_process(process)

    assert [process.exitcode for process in processes] == [0, 0]
    stored = json.loads(token_path.read_text(encoding="utf-8"))
    assert stored["office-core-1"]["access_token"] == "office-core-1"
    assert stored["office-core-2"]["access_token"] == "office-core-2"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not portable to Windows")
def test_transaction_files_are_private(tmp_path, monkeypatch):
    import stat
    from common import auth

    token_path = tmp_path / "account.token"
    observed_temp_modes = []
    real_dump = auth.json.dump

    def inspect_temp_mode(payload, handle, **kwargs):
        observed_temp_modes.append(stat.S_IMODE(os.fstat(handle.fileno()).st_mode))
        return real_dump(payload, handle, **kwargs)

    monkeypatch.setattr(auth.json, "dump", inspect_temp_mode)
    auth.save_token_file(token_path, {"email": "fixture@example.invalid"})

    lock_path = token_path.with_name(token_path.name + ".lock")
    assert observed_temp_modes == [0o600]
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_lock_failure_does_not_expose_private_path(tmp_path, monkeypatch):
    from common import auth

    token_path = tmp_path / "private-account.token"
    real_open = auth.os.open

    def fail_lock_open(path, flags, mode=0o777):
        if str(path).endswith(".lock"):
            raise PermissionError(13, "permission denied", str(path))
        return real_open(path, flags, mode)

    monkeypatch.setattr(auth.os, "open", fail_lock_open)
    with pytest.raises(Exception) as exc_info:
        auth.save_token_file(token_path, {"email": "fixture@example.invalid"})

    assert str(token_path) not in str(exc_info.value)
    assert "private-account" not in str(exc_info.value)


def test_file_fsync_failure_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    from common import auth

    token_path = tmp_path / "private-account.token"
    token_path.write_text('{"email": "original@example.invalid"}\n', encoding="utf-8")
    original = token_path.read_bytes()

    def fail_file_fsync(_fd):
        raise OSError(5, "fsync failed", str(token_path))

    monkeypatch.setattr(auth.os, "fsync", fail_file_fsync)
    with pytest.raises(Exception) as exc_info:
        auth.save_token_file(token_path, {"email": "replacement@example.invalid"})

    assert token_path.read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp"))
    assert str(token_path) not in str(exc_info.value)
    assert "private-account" not in str(exc_info.value)


def test_replace_failure_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    from common import auth

    token_path = tmp_path / "private-account.token"
    token_path.write_text('{"email": "original@example.invalid"}\n', encoding="utf-8")
    original = token_path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError(5, "replace failed", str(token_path))

    monkeypatch.setattr(auth.os, "replace", fail_replace)
    with pytest.raises(Exception) as exc_info:
        auth.save_token_file(token_path, {"email": "replacement@example.invalid"})

    assert token_path.read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp"))
    assert str(token_path) not in str(exc_info.value)
    assert "private-account" not in str(exc_info.value)


def test_directory_fsync_occurs_after_replace(tmp_path, monkeypatch):
    from common import auth

    token_path = tmp_path / "account.token"
    events = []
    real_replace = auth.os.replace
    real_fsync_directory = auth._fsync_directory

    def record_replace(source, target):
        events.append("replace")
        return real_replace(source, target)

    def record_directory_fsync(directory):
        events.append("directory-fsync")
        return real_fsync_directory(directory)

    monkeypatch.setattr(auth.os, "replace", record_replace)
    monkeypatch.setattr(auth, "_fsync_directory", record_directory_fsync)
    auth.save_token_file(token_path, {"email": "fixture@example.invalid"})

    assert events == ["replace", "directory-fsync"]
