"""百度千帆「百度搜索」Provider。

上游：POST /v2/ai_search/web_search
文档：https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5

@author 赵振明
@date 2026-09-08 10:58:43
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import httpx

from app.modules.web_search.providers.base import SearchHit

logger = logging.getLogger(__name__)

BAIDU_DEFAULT_BASE_URL = "https://qianfan.baidubce.com"
_SEARCH_PATH = "v2/ai_search/web_search"
_QUERY_MAX_UNITS = 72


class BaiduUpstreamError(Exception):
    """上游 HTTP/解析错误。"""

    def __init__(self, message: str, *, unreachable: bool = False) -> None:
        self.unreachable = unreachable
        super().__init__(message)


def truncate_baidu_query(text: str, max_units: int = _QUERY_MAX_UNITS) -> str:
    """按百度规则截断 query：汉字计 2，ASCII 计 1，总单位上限 72。

    @author 赵振明
    @date 2026-09-08 10:58:43
    """
    units = 0
    out: list[str] = []
    for ch in str(text or ""):
        # 百度文档：一个汉字占两个字符；非 ASCII 按 2 计
        cost = 2 if ord(ch) > 127 else 1
        if units + cost > max_units:
            break
        units += cost
        out.append(ch)
    return "".join(out)


def _build_auth_headers(api_key: str) -> dict[str, str]:
    """组装鉴权头；优先 Authorization Bearer（官方请求结构）。

    @author 赵振明
    @date 2026-09-08 10:58:43
    """
    token = str(api_key or "").strip()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


class BaiduProvider:
    """调用千帆百度搜索网页接口；不读库、不管开关。"""

    name = "baidu"

    async def search(
        self,
        query: str,
        *,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        limit: int,
        engines: str | None = None,
    ) -> list[SearchHit]:
        """POST web_search，映射 references → SearchHit。

        @author 赵振明
        @date 2026-09-08 10:58:43
        """
        _ = engines  # 无引擎目录类 Provider
        key = str(api_key or "").strip()
        if not key:
            raise BaiduUpstreamError("api_key required")

        root = (base_url or BAIDU_DEFAULT_BASE_URL).strip().rstrip("/") + "/"
        url = urljoin(root, _SEARCH_PATH)
        q = truncate_baidu_query(str(query or "").strip())
        if not q:
            raise BaiduUpstreamError("empty query after truncate")

        top_k = max(1, min(int(limit or 5), 50))
        body: dict[str, Any] = {
            "messages": [{"role": "user", "content": q}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": top_k}],
            "edition": "standard",
        }
        headers = _build_auth_headers(key)

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise BaiduUpstreamError("timeout", unreachable=True) from exc
        except httpx.HTTPError as exc:
            raise BaiduUpstreamError(str(exc) or "connection failed", unreachable=True) from exc

        if resp.status_code < 200 or resp.status_code >= 300:
            hint = f"http {resp.status_code}"
            try:
                err_payload: Any = resp.json()
                if isinstance(err_payload, dict):
                    code = err_payload.get("code")
                    msg = err_payload.get("message")
                    if code is not None or msg:
                        hint = f"http {resp.status_code} code={code} message={msg}"
            except ValueError:
                pass
            raise BaiduUpstreamError(hint)

        try:
            payload: Any = resp.json()
        except ValueError as exc:
            raise BaiduUpstreamError("invalid json") from exc

        if not isinstance(payload, dict):
            raise BaiduUpstreamError("invalid payload")

        # 业务错误有时仍返回 200 + code
        if payload.get("code") not in (None, 0, "0"):
            raise BaiduUpstreamError(
                f"code={payload.get('code')} message={payload.get('message')}"
            )

        raw_refs = payload.get("references")
        if raw_refs is None:
            raise BaiduUpstreamError("missing references")
        if not isinstance(raw_refs, list):
            raise BaiduUpstreamError("invalid references")

        hits: list[SearchHit] = []
        for row in raw_refs:
            if not isinstance(row, dict):
                continue
            # 本期仅网页；跳过非 web（防御）
            rtype = str(row.get("type") or "web").strip().lower()
            if rtype and rtype != "web":
                continue
            title = str(row.get("title") or "").strip()
            link = str(row.get("url") or "").strip()
            snippet = str(row.get("snippet") or row.get("content") or "").strip()
            if not title and not link:
                continue
            hits.append(SearchHit(title=title or link, url=link, snippet=snippet))
            if len(hits) >= max(1, min(int(limit or 5), 10)):
                break
        return hits
