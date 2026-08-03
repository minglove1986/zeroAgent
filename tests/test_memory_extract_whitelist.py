"""记忆抽取白名单与调度。

@author 赵振明
@date 2026-07-29 11:26:00
"""

from __future__ import annotations

from app.modules.memory.extract_catalog_cache import reset_extract_fields_for_tests
from app.modules.memory.extract_scheduler import (
    is_explicit_remember,
    schedule_memory_extract,
    should_skip_extract,
)
from app.modules.memory.service import (
    build_memory_system_prompt,
    parse_auto_extract_rules,
    parse_memory_json,
)
from app.models.memory import UserMemory


def setup_function() -> None:
    reset_extract_fields_for_tests()


def test_parse_rejects_open_keys() -> None:
    raw = (
        '[{"memory_type":"fact","memory_key":"person_of_interest",'
        '"memory_value":"唐亮","confidence":0.9}]'
    )
    assert parse_memory_json(raw) == []


def test_parse_accepts_hobby() -> None:
    raw = (
        '[{"memory_type":"fact","memory_key":"hobby",'
        '"memory_value":"摄影","confidence":0.9}]'
    )
    items = parse_memory_json(raw)
    assert len(items) == 1
    assert items[0]["memory_key"] == "hobby"


def test_mock_rules_map_to_whitelist_keys() -> None:
    items = parse_auto_extract_rules("我叫张三")
    assert items
    assert items[0]["memory_key"] == "display_name"


def test_prompt_filters_non_whitelist_memories() -> None:
    rows = [
        UserMemory(
            id="mem_1",
            user_id="u1",
            memory_type="fact",
            memory_key="person_of_interest",
            memory_value="唐亮",
        ),
        UserMemory(
            id="mem_2",
            user_id="u1",
            memory_type="fact",
            memory_key="hobby",
            memory_value="跑步",
        ),
    ]
    text = build_memory_system_prompt(rows)
    assert "唐亮" not in text
    assert "hobby" in text
    assert "跑步" in text


def test_meta_reply_skips_schedule() -> None:
    assert should_skip_extract(
        allow_memory_write=True,
        transcript="我没有让你总结赵世龙简历",
        route_reason="meta_conversation",
        route_kind="chitchat",
    )
    assert should_skip_extract(
        allow_memory_write=True,
        transcript="查一下唐亮",
        route_kind="kb_lookup",
    )
    assert not should_skip_extract(
        allow_memory_write=True,
        transcript="请记住我喜欢简洁回答",
        route_kind="chitchat",
    )


def test_schedule_does_not_call_extract_sync(monkeypatch) -> None:
    calls: list[tuple] = []

    class _FakeTask:
        def delay(self, *args, **kwargs):
            calls.append(("delay", args, kwargs))
            return None

        def apply_async(self, **kwargs):
            calls.append(("apply_async", (), kwargs))
            return None

    monkeypatch.setattr(
        "app.workers.tasks.extract_memories.extract_memories_task",
        _FakeTask(),
        raising=False,
    )
    # patch import path used inside scheduler
    import app.modules.memory.extract_scheduler as sch

    monkeypatch.setattr(
        sch,
        "_dispatch_celery",
        lambda **kw: calls.append(("dispatch", kw)) or True,
    )

    out = schedule_memory_extract(
        user_id="u1",
        conversation_id="c1",
        transcript="请记住：我喜欢简洁",
        allow_memory_write=True,
        route_kind="chitchat",
    )
    assert out["skipped"] is False
    assert "explicit" in out["scheduled"]
    assert calls


def test_explicit_remember_detect() -> None:
    assert is_explicit_remember("请记住我叫李四")
    assert not is_explicit_remember("今天天气不错")
