"""OSS Mock / 简易存储 + 真 OSS 上传入口。

本地开发默认写内存与 `.data/oss`；公网 URL 上传请用 `OssUploadUtil`。

@author 赵振明
@date 2026-07-22 16:16:50
"""

from __future__ import annotations

import base64
from pathlib import Path

from app.shared.oss_upload import OssUploadUtil

_MEMORY: dict[str, bytes] = {}

__all__ = ["OssUploadUtil", "put_object", "get_object", "put_object_b64"]


def put_object(key: str, data: bytes) -> str:
    """写入内存并镜像到 `.data/oss/{key}`（真 OSS SDK 落地前保证跨进程可读）。"""
    _MEMORY[key] = data
    local = Path(".data/oss") / key
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)
    return key


def get_object(key: str) -> bytes:
    """按 key 读取对象；优先内存，其次 `.data/oss/{key}`。"""
    if key in _MEMORY:
        return _MEMORY[key]
    local = Path(".data/oss") / key
    if local.is_file():
        data = local.read_bytes()
        _MEMORY[key] = data
        return data
    raise FileNotFoundError(key)


def put_object_b64(key: str, content_b64: str) -> str:
    return put_object(key, base64.b64decode(content_b64))
