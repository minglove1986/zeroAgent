"""对象存储 put/get 本地路径单测。

@author 赵振明
@date 2026-11-23 17:02:48
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.shared import oss


def test_put_get_local_roundtrip(tmp_path: Path, monkeypatch) -> None:
    """mock 环境下本地读写闭环。"""
    monkeypatch.chdir(tmp_path)
    with patch("app.shared.oss._use_remote_oss", return_value=False):
        key = "kb/demo/a.txt"
        oss.put_object(key, b"hello-oss")
        assert oss.get_object(key) == b"hello-oss"
        assert (tmp_path / ".data/oss" / key).is_file()


def test_get_missing_raises(tmp_path: Path, monkeypatch) -> None:
    """本地与远端都没有时抛 FileNotFoundError。"""
    monkeypatch.chdir(tmp_path)
    with patch("app.shared.oss._use_remote_oss", return_value=False):
        try:
            oss.get_object("kb/no-such-file.bin")
            raised = False
        except FileNotFoundError:
            raised = True
        assert raised
