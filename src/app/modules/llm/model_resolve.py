"""会话应用模型解析与白名单校验。

仅由 LlmGateway 编排调用；业务禁止绕过。

@author 赵振明
@date 2026-07-30 12:09:46
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.llm.catalog_models import (
    SOURCE_MISSING,
    LlmModel,
    LlmModelAgentBinding,
)
from app.modules.llm.gateway import ResolvedModel
from app.modules.llm import models_cache
from app.modules.llm.model_chain import resolve_agent_model_chain
from app.modules.llm.litellm_sync import refresh_models_cache_from_db


class ModelResolveError(ValueError):
    """模型不可用 / 不在白名单（对应业务 400）。"""


def _catalog_models() -> list[dict[str, Any]]:
    """读取热缓存 models 列表。"""
    payload = models_cache.get_models_catalog()
    if not payload:
        return []
    items = payload.get("models")
    return items if isinstance(items, list) else []


def _find_in_catalog(model_name: str) -> dict[str, Any] | None:
    name = (model_name or "").strip()
    for item in _catalog_models():
        if isinstance(item, dict) and str(item.get("model_name") or "") == name:
            return item
    return None


def resolve_window_tokens(model_name: str | None = None) -> int:
    """解析展示/打包用上下文窗：目录 max_input_tokens → 系统默认 → 环境 CONTEXT_WINDOW。

    @author 赵振明
    @date 2026-07-30 13:36:32
    """
    settings = get_settings()
    fallback = max(1, int(settings.context_window_tokens))
    name = (model_name or "").strip()
    if not name:
        payload = models_cache.get_models_catalog() or {}
        sys_def = payload.get("system_default")
        if isinstance(sys_def, str) and sys_def.strip():
            name = sys_def.strip()
    if not name:
        return fallback
    info = _find_in_catalog(name)
    if info is None:
        return fallback
    raw = info.get("max_input_tokens")
    try:
        mit = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        mit = 0
    return mit if mit > 0 else fallback


def _assert_usable(
    info: dict[str, Any] | None,
    *,
    model_name: str,
    require_system: bool,
) -> None:
    """校验启用、非缺失、系统白名单；失败抛出面向用户的中文说明。"""
    if info is None:
        raise ModelResolveError(
            f"模型「{model_name}」不在可用目录中，请重新选择模型"
        )
    if not info.get("enabled"):
        raise ModelResolveError(
            f"模型「{model_name}」已停用，请切换其他可用模型后再发送"
        )
    if str(info.get("source_status") or "") == SOURCE_MISSING:
        raise ModelResolveError(
            f"模型「{model_name}」在网关侧已不可用，请切换其他模型后再发送"
        )
    if require_system and not info.get("allow_system_chat"):
        raise ModelResolveError(
            f"模型「{model_name}」未开放系统对话，请在输入框左侧切换可用模型后再发送"
        )


async def _ensure_catalog(db: AsyncSession) -> list[dict[str, Any]]:
    """缓存 miss 时回填 MySQL。"""
    items = _catalog_models()
    if items:
        return items
    await refresh_models_cache_from_db(db)
    return _catalog_models()


async def _agent_allowed_names(db: AsyncSession, agent_id: str) -> list[str]:
    """Agent 绑定的 model_name 列表（默认优先）。"""
    binds = list(
        (
            await db.execute(
                select(LlmModelAgentBinding).where(
                    LlmModelAgentBinding.agent_id == agent_id
                )
            )
        ).scalars()
    )
    if not binds:
        return []
    id_order = sorted(binds, key=lambda b: (0 if b.is_default else 1, b.id or 0))
    model_ids = [b.model_id for b in id_order]
    rows = list(
        (await db.execute(select(LlmModel).where(LlmModel.id.in_(model_ids)))).scalars()
    )
    by_id = {r.id: r for r in rows}
    names: list[str] = []
    for mid in model_ids:
        row = by_id.get(mid)
        if row and row.model_name not in names:
            names.append(row.model_name)
    return names


async def resolve_conversation_model(
    db: AsyncSession,
    conversation: Any,
) -> ResolvedModel:
    """解析会话模型：selected → Agent 绑定/主模型 → 系统默认 → 环境默认。

    目录非空时强制白名单校验；目录为空时降级旧链，避免未同步阻断对话。
    """
    settings = get_settings()
    catalog = await _ensure_catalog(db)
    agent_id = getattr(conversation, "agent_id", None)
    selected = getattr(conversation, "selected_model", None)
    selected_name = selected.strip() if isinstance(selected, str) else ""

    # 目录为空：兼容旧行为
    if not catalog:
        if selected_name:
            return ResolvedModel(model_name=selected_name, fallback_models=[])
        chain = await resolve_agent_model_chain(
            db, str(agent_id) if agent_id else None
        )
        return ResolvedModel(
            model_name=chain[0] if chain else settings.litellm_model,
            fallback_models=list(chain[1:]) if chain else [],
        )

    require_system = not bool(agent_id)

    if selected_name:
        if agent_id:
            allowed = await _agent_allowed_names(db, str(agent_id))
            if allowed and selected_name not in allowed:
                raise ModelResolveError(
                    f"模型「{selected_name}」未绑定到当前 Agent，请切换其他可用模型"
                )
        info = _find_in_catalog(selected_name)
        _assert_usable(info, model_name=selected_name, require_system=require_system)
        assert info is not None
        return ResolvedModel(
            model_name=selected_name,
            fallback_models=[],
            max_input_tokens=info.get("max_input_tokens"),
            max_output_tokens=info.get("max_output_tokens"),
        )

    if agent_id:
        allowed = await _agent_allowed_names(db, str(agent_id))
        if allowed:
            primary = allowed[0]
            info = _find_in_catalog(primary)
            _assert_usable(info, model_name=primary, require_system=False)
            assert info is not None
            fallbacks: list[str] = []
            for name in allowed[1:]:
                fb = _find_in_catalog(name)
                if fb and fb.get("enabled") and fb.get("source_status") != SOURCE_MISSING:
                    fallbacks.append(name)
            return ResolvedModel(
                model_name=primary,
                fallback_models=fallbacks,
                max_input_tokens=info.get("max_input_tokens"),
                max_output_tokens=info.get("max_output_tokens"),
            )
        # 无绑定：回落 Agent.main_model_id 链，但仍须在目录且启用
        chain = await resolve_agent_model_chain(db, str(agent_id))
        usable: list[str] = []
        for name in chain:
            info = _find_in_catalog(name)
            try:
                _assert_usable(info, model_name=name, require_system=False)
            except ModelResolveError:
                continue
            usable.append(name)
        if not usable:
            raise ModelResolveError(
                "当前 Agent 没有可用模型，请联系管理员在「模型治理」中绑定"
            )
        info = _find_in_catalog(usable[0])
        assert info is not None
        return ResolvedModel(
            model_name=usable[0],
            fallback_models=usable[1:],
            max_input_tokens=info.get("max_input_tokens"),
            max_output_tokens=info.get("max_output_tokens"),
        )

    # 系统对话：系统默认
    default_name = None
    payload = models_cache.get_models_catalog() or {}
    if isinstance(payload.get("system_default"), str) and payload["system_default"]:
        default_name = payload["system_default"]
    if not default_name:
        for item in catalog:
            if (
                isinstance(item, dict)
                and item.get("is_system_default")
                and item.get("enabled")
                and item.get("allow_system_chat")
            ):
                default_name = str(item.get("model_name") or "")
                break
    if not default_name:
        # 任意系统白名单启用模型
        for item in catalog:
            if (
                isinstance(item, dict)
                and item.get("enabled")
                and item.get("allow_system_chat")
                and item.get("source_status") != SOURCE_MISSING
            ):
                default_name = str(item.get("model_name") or "")
                break
    if not default_name:
        # 最后降级环境变量（若也在目录则校验）
        env_name = settings.litellm_model
        info = _find_in_catalog(env_name)
        if info is not None:
            _assert_usable(info, model_name=env_name, require_system=True)
            return ResolvedModel(
                model_name=env_name,
                fallback_models=[],
                max_input_tokens=info.get("max_input_tokens"),
                max_output_tokens=info.get("max_output_tokens"),
            )
        raise ModelResolveError(
            "尚未配置系统对话可用模型，请联系管理员在「模型治理」中启用并加入系统白名单"
        )

    info = _find_in_catalog(default_name)
    _assert_usable(info, model_name=default_name, require_system=True)
    assert info is not None
    return ResolvedModel(
        model_name=default_name,
        fallback_models=[],
        max_input_tokens=info.get("max_input_tokens"),
        max_output_tokens=info.get("max_output_tokens"),
    )


async def list_available_models(
    db: AsyncSession,
    *,
    agent_id: str | None,
) -> list[dict[str, Any]]:
    """员工端可选列表：系统白名单或 Agent 绑定且启用。"""
    catalog = await _ensure_catalog(db)
    if not catalog:
        settings = get_settings()
        return [
            {
                "model_name": settings.litellm_model,
                "display_name": settings.litellm_model,
                "enabled": True,
            }
        ]

    if agent_id:
        allowed = set(await _agent_allowed_names(db, str(agent_id)))
        out = []
        for item in catalog:
            if not isinstance(item, dict):
                continue
            name = str(item.get("model_name") or "")
            if name not in allowed:
                continue
            if not item.get("enabled") or item.get("source_status") == SOURCE_MISSING:
                continue
            out.append(item)
        return out

    return [
        item
        for item in catalog
        if isinstance(item, dict)
        and item.get("enabled")
        and item.get("allow_system_chat")
        and item.get("source_status") != SOURCE_MISSING
    ]
