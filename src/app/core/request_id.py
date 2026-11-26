"""请求级 request_id：生成、ContextVar 绑定、ASGI 中间件。

设计思路：
- 入口统一生成/透传，写入 request.state 与 ContextVar；
- ok/fail 与审计 getattr(request.state, "request_id") 共用同一值；
- 响应头回写 X-Request-Id，便于网关与客户端对账。

@author 赵振明
@date 2026-11-19 09:32:32
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar, Token
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 与 config_audit_logs.request_id String(40) 对齐
_MAX_LEN: Final[int] = 40
_SAFE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{8,40}$")

_request_id_ctx: ContextVar[str | None] = ContextVar("zeroagent_request_id", default=None)


def new_request_id() -> str:
    """生成服务端 request_id（req_ + 16 hex）。"""
    return f"req_{uuid.uuid4().hex[:16]}"


def bind_request_id(request_id: str) -> Token:
    """绑定当前协程上下文的 request_id，返回可 reset 的 Token。"""
    return _request_id_ctx.set(request_id)


def clear_request_id(token: Token | None = None) -> None:
    """清除绑定：有 Token 则 reset；否则置回默认 None。"""
    if token is not None:
        _request_id_ctx.reset(token)
    else:
        _request_id_ctx.set(None)


def current_request_id() -> str | None:
    """读取当前 ContextVar 中的 request_id（可能为 None）。"""
    return _request_id_ctx.get()


def resolve_response_request_id() -> str:
    """供 ok/fail 使用：优先 ContextVar，否则现场生成（非 HTTP 调用兜底）。"""
    rid = _request_id_ctx.get()
    if rid:
        return rid
    return new_request_id()


def normalize_incoming_request_id(raw: str | None) -> str | None:
    """校验客户端透传的 X-Request-Id；非法则返回 None。"""
    if raw is None:
        return None
    value = raw.strip()
    if not value or len(value) > _MAX_LEN:
        return None
    if not _SAFE_RE.match(value):
        return None
    return value


class RequestIdMiddleware:
    """ASGI 中间件：贯通 request.state / ContextVar / 响应头。

    @author 赵振明
    @date 2026-11-19 09:32:32
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """处理 HTTP 请求：解析/生成 id，绑定上下文并回写响应头。"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        rid = normalize_incoming_request_id(headers.get("x-request-id")) or new_request_id()

        # Starlette Request.state 读写 scope["state"]
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = rid
        else:
            # 某些环境下 state 已是 State 对象
            setattr(state, "request_id", rid)

        token = bind_request_id(rid)

        async def send_with_header(message: Message) -> None:
            """在响应开始帧注入 X-Request-Id。"""
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                mutable["X-Request-Id"] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            clear_request_id(token)
