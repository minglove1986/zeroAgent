"""OssUploadUtil 单测（Mock 客户端，不触真实 OSS）。

@author 赵振明
@date 2026-07-22 16:16:50
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.shared.oss_upload import OssUploadUtil


@pytest.fixture
def util() -> tuple[OssUploadUtil, MagicMock]:
    bucket = MagicMock()
    client = OssUploadUtil(
        endpoint="oss-cn-beijing.aliyuncs.com",
        bucket_name="hoolebuy",
        access_key_id="ak",
        access_key_secret="sk",
        public_base_url="https://static.hoolebuy.com",
        bucket=bucket,
    )
    return client, bucket


def test_upload_bytes_returns_public_url_and_puts_object(util) -> None:
    client, bucket = util
    url = client.upload(b"hello-pdf", "report.PDF")
    assert url.startswith("https://static.hoolebuy.com/temp/")
    assert url.lower().endswith(".pdf")
    assert bucket.put_object.called
    key, data = bucket.put_object.call_args.args[:2]
    assert key.startswith("temp/")
    assert data == b"hello-pdf"
    headers = bucket.put_object.call_args.kwargs.get("headers") or {}
    assert headers.get("Content-Type") == "application/pdf"


def test_upload_rejects_empty_bytes(util) -> None:
    client, _ = util
    with pytest.raises(ValueError, match="上传内容不能为空"):
        client.upload(b"", "a.png")


def test_upload_stream(util) -> None:
    client, bucket = util
    url = client.upload_stream(BytesIO(b"stream-data"), 11, "note.txt")
    assert url.endswith(".txt")
    assert bucket.put_object.called
    headers = bucket.put_object.call_args.kwargs.get("headers") or {}
    assert "text/plain" in headers.get("Content-Type", "")


def test_upload_file(tmp_path: Path, util) -> None:
    client, bucket = util
    path = tmp_path / "photo.webp"
    path.write_bytes(b"webp-bytes")
    url = client.upload_file(path)
    assert url.endswith(".webp")
    assert bucket.put_object.call_args.args[1] == b"webp-bytes"
    headers = bucket.put_object.call_args.kwargs.get("headers") or {}
    assert headers.get("Content-Type") == "image/webp"


def test_upload_file_missing_raises(util) -> None:
    client, _ = util
    with pytest.raises(ValueError, match="文件不存在"):
        client.upload_file(Path("no-such-file.bin"))


def test_guess_content_type_documents() -> None:
    assert OssUploadUtil.guess_content_type("a.docx") == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert OssUploadUtil.guess_content_type("a.xlsx") == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert OssUploadUtil.guess_content_type("a.doc") == "application/msword"
    assert OssUploadUtil.guess_content_type(None) == "application/octet-stream"


def test_to_public_url_strips_trailing_slash(util) -> None:
    client, _ = util
    assert client.to_public_url("temp/20260722/x.bin") == (
        "https://static.hoolebuy.com/temp/20260722/x.bin"
    )


def test_local_fallback_writes_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = OssUploadUtil(
        endpoint="oss-cn-beijing.aliyuncs.com",
        bucket_name="hoolebuy",
        access_key_id="",
        access_key_secret="",
        public_base_url="https://static.hoolebuy.com",
        use_local_fallback=True,
    )
    url = client.upload(b"local-only", "readme.md")
    assert url.startswith("https://static.hoolebuy.com/temp/")
    key = url.removeprefix("https://static.hoolebuy.com/")
    assert (tmp_path / ".data" / "oss" / key).read_bytes() == b"local-only"
