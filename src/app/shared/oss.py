"""对象存储读写：真 OSS 优先，本地 `.data/oss` 回落。

设计思路：文档入库/重新切块通过 get_object 读原文。若仅写本地而 API
跑在容器内，会报 oss_missing。配置了 OSS 密钥时 put/get 走阿里云，
并镜像一份到本地便于排障；MOCK_EXTERNAL 或缺密钥时仅本地。

@author 赵振明
@date 2026-11-23 17:02:48
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from app.core.config import get_settings
from app.shared.oss_upload import OssUploadUtil

logger = logging.getLogger(__name__)

_MEMORY: dict[str, bytes] = {}

__all__ = ["OssUploadUtil", "put_object", "get_object", "put_object_b64"]


def _use_remote_oss() -> bool:
    """是否走远端 OSS（非 mock 且密钥齐全）。"""
    cfg = get_settings()
    if cfg.mock_external:
        return False
    backend = (cfg.storage_backend or "oss").strip().lower()
    if backend not in {"oss", "aliyun", "aliyun_oss"}:
        return False
    return bool(cfg.oss_access_key and cfg.oss_secret_key and cfg.oss_bucket)


def _write_local(key: str, data: bytes) -> None:
    """写入内存与本地镜像目录。"""
    _MEMORY[key] = data
    local = Path(".data/oss") / key
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)


def _read_local(key: str) -> bytes | None:
    """从内存或本地目录读取。"""
    if key in _MEMORY:
        return _MEMORY[key]
    local = Path(".data/oss") / key
    if local.is_file():
        data = local.read_bytes()
        _MEMORY[key] = data
        return data
    return None


def put_object(key: str, data: bytes) -> str:
    """写入对象；远端可用时上传 OSS，并始终落本地镜像。

    @author 赵振明
    @date 2026-11-23 17:02:48
    """
    if not key or key.startswith("/"):
        raise ValueError("object key 非法")
    payload = data or b""
    _write_local(key, payload)
    if _use_remote_oss():
        try:
            util = OssUploadUtil.from_settings()
            util.upload_with_key(payload, key, original_filename=key)
        except Exception as exc:  # noqa: BLE001
            logger.exception("oss put remote failed key=%s: %s", key, exc)
            raise
    return key


def get_object(key: str) -> bytes:
    """读取对象：内存 → 本地 → 远端 OSS。

    @author 赵振明
    @date 2026-11-23 17:02:48
    """
    local = _read_local(key)
    if local is not None:
        return local
    if _use_remote_oss():
        try:
            util = OssUploadUtil.from_settings()
            data = util.download(key)
            _write_local(key, data)
            return data
        except FileNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("oss get remote failed key=%s: %s", key, exc)
            raise FileNotFoundError(key) from exc
    raise FileNotFoundError(key)


def put_object_b64(key: str, content_b64: str) -> str:
    """Base64 内容写入对象存储。"""
    return put_object(key, base64.b64decode(content_b64))
