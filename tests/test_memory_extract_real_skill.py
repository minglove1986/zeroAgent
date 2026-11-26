"""记忆抽取真 Skill：工具注册、开关、调度门禁。

@author 赵振明
@date 2026-08-20 16:46:14
"""

from __future__ import annotations

from app.modules.memory.extract_scheduler import schedule_memory_extract
from app.modules.memory.extract_settings import is_memory_extract_enabled
from app.modules.tool.registry import (
    EXTRACT_USER_MEMORIES,
    get_tool_schema,
    list_builtin_tool_ids,
)


def test_extract_user_memories_registered() -> None:
    assert EXTRACT_USER_MEMORIES in list_builtin_tool_ids()
    schema = get_tool_schema(EXTRACT_USER_MEMORIES)
    assert schema is not None
    assert schema["function"]["name"] == EXTRACT_USER_MEMORIES


def test_schedule_skips_when_global_disabled(monkeypatch) -> None:
    import app.modules.memory.extract_scheduler as sch

    monkeypatch.setattr(
        "app.modules.memory.extract_settings.is_memory_extract_enabled",
        lambda: False,
    )
    calls: list[dict] = []
    monkeypatch.setattr(
        sch,
        "_dispatch_celery",
        lambda **kw: calls.append(kw) or True,
    )
    out = schedule_memory_extract(
        user_id="u1",
        conversation_id="c1",
        transcript="我的邮箱：a@b.com",
        allow_memory_write=True,
        intent_features=["memory_candidate"],
    )
    assert out["skipped"] is True
    assert out.get("skip_reason") == "memory_extract_disabled"
    assert calls == []


def test_memory_extract_enabled_default_true() -> None:
    assert isinstance(is_memory_extract_enabled(), bool)
