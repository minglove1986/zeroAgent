"""阿里云 OSS 上传工具（对齐 wish-pool OssUploadUtil）。

支持图片、文档、PDF 等任意字节内容；密钥仅从环境变量 / Settings 读取。

@author 赵振明
@date 2026-07-22 16:16:50
"""

from __future__ import annotations

import mimetypes
import uuid
from datetime import date
from pathlib import Path
from typing import BinaryIO

from app.core.config import Settings, get_settings

_TEMP_DIR = "temp"

# 常见扩展名补充（mimetypes 在部分环境不全）
_EXTRA_CONTENT_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html; charset=utf-8",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
    ".rar": "application/vnd.rar",
    ".7z": "application/x-7z-compressed",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
}


class OssUploadUtil:
    """阿里云 OSS 上传工具：写入对象并返回公网 URL。"""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket_name: str,
        access_key_id: str,
        access_key_secret: str,
        public_base_url: str,
        bucket: object | None = None,
        use_local_fallback: bool = False,
    ) -> None:
        self._endpoint = endpoint.strip()
        self._bucket_name = bucket_name.strip()
        self._access_key_id = access_key_id.strip()
        self._access_key_secret = access_key_secret.strip()
        self._public_base_url = public_base_url.rstrip("/")
        self._use_local_fallback = use_local_fallback
        self._bucket = bucket
        if self._bucket is None and not self._use_local_fallback:
            self._bucket = self._build_bucket()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> OssUploadUtil:
        """从应用配置构建实例；缺密钥或 MOCK_EXTERNAL 时走本地回落。"""
        cfg = settings or get_settings()
        has_creds = bool(cfg.oss_access_key and cfg.oss_secret_key and cfg.oss_bucket)
        use_local = bool(cfg.mock_external) or not has_creds
        public_base = (cfg.oss_public_base_url or "").strip()
        if not public_base:
            public_base = "https://mock-oss.local"
        return cls(
            endpoint=cfg.oss_endpoint or "oss-cn-hangzhou.aliyuncs.com",
            bucket_name=cfg.oss_bucket or "local",
            access_key_id=cfg.oss_access_key,
            access_key_secret=cfg.oss_secret_key,
            public_base_url=public_base,
            use_local_fallback=use_local,
        )

    def upload(self, data: bytes, original_filename: str | None = None) -> str:
        """上传字节数组到 OSS temp 目录，返回公网 URL。"""
        if data is None or len(data) == 0:
            raise ValueError("上传内容不能为空")
        object_key = self.build_object_key(original_filename)
        content_type = self.guess_content_type(original_filename)
        self._put(object_key, data, content_type)
        return self.to_public_url(object_key)

    def upload_stream(
        self,
        input_stream: BinaryIO,
        content_length: int,
        original_filename: str | None = None,
    ) -> str:
        """上传输入流到 OSS temp 目录，返回公网 URL。content_length 未知时可传 -1。"""
        if input_stream is None:
            raise ValueError("输入流不能为空")
        if content_length >= 0:
            data = input_stream.read(content_length)
        else:
            data = input_stream.read()
        return self.upload(data, original_filename)

    def upload_file(self, file_path: str | Path) -> str:
        """上传本地文件到 OSS temp 目录，返回公网 URL。"""
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"文件不存在或不是普通文件: {path}")
        return self.upload(path.read_bytes(), path.name)

    def upload_with_key(
        self,
        data: bytes,
        object_key: str,
        *,
        content_type: str | None = None,
        original_filename: str | None = None,
    ) -> str:
        """按指定 object_key 上传（如 kb/{id}/...），返回公网 URL。"""
        if data is None or len(data) == 0:
            raise ValueError("上传内容不能为空")
        if not object_key or object_key.startswith("/"):
            raise ValueError("object_key 非法")
        ctype = content_type or self.guess_content_type(original_filename or object_key)
        self._put(object_key, data, ctype)
        return self.to_public_url(object_key)

    def close(self) -> None:
        """释放底层客户端（oss2 Bucket 无显式 close，占位对齐 Java shutdown）。"""
        self._bucket = None

    def to_public_url(self, object_key: str) -> str:
        """将 object_key 转为公网访问地址。"""
        base = self._public_base_url.rstrip("/")
        key = object_key.lstrip("/")
        return f"{base}/{key}"

    @staticmethod
    def build_object_key(original_filename: str | None, *, prefix: str = _TEMP_DIR) -> str:
        """生成 OSS Key：{prefix}/{yyyyMMdd}/{uuid}{ext}。"""
        day = date.today().strftime("%Y%m%d")
        ext = OssUploadUtil.extract_extension(original_filename)
        filename = uuid.uuid4().hex + ext
        return f"{prefix.strip('/')}/{day}/{filename}"

    @staticmethod
    def extract_extension(filename: str | None) -> str:
        """从原始文件名提取小写扩展名；缺失时返回 .bin。"""
        if not filename:
            return ".bin"
        name = Path(filename).name
        dot = name.rfind(".")
        if dot < 0 or dot == len(name) - 1:
            return ".bin"
        return name[dot:].lower()

    @staticmethod
    def guess_content_type(filename: str | None) -> str:
        """按扩展名推断 Content-Type。"""
        if filename is None:
            return "application/octet-stream"
        ext = OssUploadUtil.extract_extension(filename)
        if ext in _EXTRA_CONTENT_TYPES:
            return _EXTRA_CONTENT_TYPES[ext]
        guessed, _ = mimetypes.guess_type(f"file{ext}")
        return guessed or "application/octet-stream"

    def _put(self, object_key: str, data: bytes, content_type: str) -> None:
        """写入 OSS 或本地回落目录。"""
        if self._use_local_fallback or self._bucket is None:
            local = Path(".data/oss") / object_key
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(data)
            return
        headers = {"Content-Type": content_type}
        self._bucket.put_object(object_key, data, headers=headers)

    def _build_bucket(self) -> object:
        """懒创建 oss2.Bucket。"""
        try:
            import oss2
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "未安装 oss2，请执行: pip install oss2 或 pip install -e '.[dev]'"
            ) from exc
        if not self._access_key_id or not self._access_key_secret:
            raise RuntimeError("OSS AccessKey 未配置，请设置 OSS_ACCESS_KEY / OSS_SECRET_KEY")
        endpoint = self._endpoint
        if endpoint and not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"
        auth = oss2.Auth(self._access_key_id, self._access_key_secret)
        return oss2.Bucket(auth, endpoint, self._bucket_name)
