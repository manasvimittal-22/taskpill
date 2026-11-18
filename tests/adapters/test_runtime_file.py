import os
import sys

import pytest

from taskpill.adapters.atomic import write_text_atomic
from taskpill.adapters.runtime_file import (
    RuntimeInfo,
    read_runtime,
    remove_runtime_if_owned,
    write_runtime,
)

INFO = RuntimeInfo(port=51234, token="t" * 43, pid=4120, version="0.1.0")


def test_round_trip(tmp_path):
    path = tmp_path / "sub" / "runtime.json"
    write_runtime(path, INFO)
    assert read_runtime(path) == INFO


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_file_is_private_on_posix(tmp_path):
    path = tmp_path / "runtime.json"
    write_runtime(path, INFO)
    assert (os.stat(path).st_mode & 0o777) == 0o600


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "[]",
        '{"port": 1}',
        '{"port": "80", "token": "x", "pid": 1, "version": "v"}',
        '{"port": 0, "token": "x", "pid": 1, "version": "v"}',
        '{"port": 70000, "token": "x", "pid": 1, "version": "v"}',
        '{"port": 80, "token": 5, "pid": 1, "version": "v"}',
    ],
)
def test_bad_files_read_as_none(tmp_path, content):
    path = tmp_path / "runtime.json"
    path.write_text(content, encoding="utf-8")
    assert read_runtime(path) is None


def test_missing_file_reads_as_none(tmp_path):
    assert read_runtime(tmp_path / "nope.json") is None


def test_remove_only_if_owned(tmp_path):
    path = tmp_path / "runtime.json"
    write_runtime(path, INFO)
    remove_runtime_if_owned(path, pid=999)  # a different instance: keep it
    assert path.exists()
    remove_runtime_if_owned(path, pid=INFO.pid)
    assert not path.exists()
    remove_runtime_if_owned(path, pid=INFO.pid)  # already gone: no error


def test_atomic_write_leaves_no_temp_files(tmp_path):
    path = tmp_path / "f.txt"
    write_text_atomic(path, "one")
    write_text_atomic(path, "two")
    assert path.read_text(encoding="utf-8") == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["f.txt"]


def test_atomic_write_retries_while_another_program_holds_the_file(tmp_path, monkeypatch):
    import taskpill.adapters.atomic as atomic

    real_replace = atomic.os.replace
    calls = []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(atomic.os, "replace", flaky)
    monkeypatch.setattr(atomic, "REPLACE_WAIT", 0)
    path = tmp_path / "f.txt"
    write_text_atomic(path, "new")
    assert path.read_text(encoding="utf-8") == "new"
    assert len(calls) == 3


def test_atomic_write_gives_up_and_cleans_up(tmp_path, monkeypatch):
    import taskpill.adapters.atomic as atomic

    def always_denied(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(atomic.os, "replace", always_denied)
    monkeypatch.setattr(atomic, "REPLACE_WAIT", 0)
    path = tmp_path / "f.txt"
    path.write_text("old", encoding="utf-8")
    with pytest.raises(PermissionError):
        write_text_atomic(path, "new")
    assert path.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["f.txt"]  # no temp file left
