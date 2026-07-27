"""OSS get_object 测试。

@author 赵振明
@date 2026-07-22 12:10:00
"""

from __future__ import annotations

import pytest

from app.shared import oss as oss_mod


def test_get_object_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    key = "kb/x/doc/a.txt"
    oss_mod.put_object(key, b"hello")
    assert oss_mod.get_object(key) == b"hello"


def test_get_object_from_disk_when_memory_empty(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    key = "kb/x/doc/b.txt"
    path = tmp_path / ".data" / "oss" / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"disk")
    assert oss_mod.get_object(key) == b"disk"


def test_get_object_missing_raises(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    with pytest.raises(FileNotFoundError):
        oss_mod.get_object("missing/key.bin")


def test_put_object_mirrors_disk_when_mock_external_false(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MOCK_EXTERNAL=false + storage_backend=oss 时 put 也必须落盘，供独立 Worker get。"""
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    monkeypatch.setenv("STORAGE_BACKEND", "oss")
    from app.core.config import get_settings

    get_settings.cache_clear()
    key = "kb/x/doc/c.txt"
    oss_mod.put_object(key, b"persist-across-process")
    disk = tmp_path / ".data" / "oss" / key
    assert disk.is_file()
    assert disk.read_bytes() == b"persist-across-process"
    oss_mod._MEMORY.clear()
    assert oss_mod.get_object(key) == b"persist-across-process"
