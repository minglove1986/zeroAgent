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
    assert items[0]["memory_value"] == "张三"


def test_mock_rules_extract_my_name_is_colon() -> None:
    """「我的名字是：xxx」须抽出 display_name（非仅「我叫」）。"""
    items = parse_auto_extract_rules("我的名字是：赵振明")
    assert items
    assert items[0]["memory_key"] == "display_name"
    assert items[0]["memory_value"] == "赵振明"


def test_mock_rules_extract_name_variants() -> None:
    """常见自称姓名话术均应命中。"""
    for text, expect in (
        ("我的名字叫李四", "李四"),
        ("真实姓名是王五", "王五"),
        ("user: 我的名字是：赵振明\nassistant: 好的", "赵振明"),
    ):
        items = parse_auto_extract_rules(text)
        assert items, text
        assert items[0]["memory_key"] == "display_name"
        assert items[0]["memory_value"] == expect


def test_mock_rules_extract_email_to_contact() -> None:
    """格式兜底：自称邮箱在 Mock/失败路径可落入 contact（非字段扩展机制）。"""
    items = parse_auto_extract_rules("我的邮箱：28154232@qq.com")
    assert items
    hit = next(i for i in items if i["memory_key"] == "contact")
    assert hit["memory_type"] == "fact"
    assert hit["memory_value"] == "28154232@qq.com"


def test_mock_rules_extract_phone_to_contact() -> None:
    """格式兜底：自称手机号可落入 contact。"""
    items = parse_auto_extract_rules("我的电话 15011586502")
    assert items
    hit = next(i for i in items if i["memory_key"] == "contact")
    assert hit["memory_value"] == "15011586502"


def test_mock_rules_extract_email_prefers_email_key() -> None:
    """白名单含独立 email 时，格式兜底优先写 email。"""
    from app.modules.memory.extract_catalog_cache import set_extract_fields_fallback
    from app.modules.memory.extract_seed import DEFAULT_EXTRACT_FIELDS

    fields = list(DEFAULT_EXTRACT_FIELDS) + [
        {
            "category": "fact",
            "field_key": "email",
            "label": "邮箱",
            "description": "用户邮箱",
            "priority": 31,
            "seed_code": "custom_email",
        }
    ]
    set_extract_fields_fallback(fields)
    items = parse_auto_extract_rules("我的邮箱是 test@example.com")
    keys = {i["memory_key"] for i in items}
    assert "email" in keys
    assert "contact" not in keys
    assert next(i for i in items if i["memory_key"] == "email")["memory_value"] == (
        "test@example.com"
    )


def test_schedule_immediate_on_memory_candidate(monkeypatch) -> None:
    """memory_candidate 旁路应立即投递 skill_immediate（Catalog 扩展不靠 rule_hit）。"""
    import app.modules.memory.extract_scheduler as sch

    calls: list[dict] = []

    monkeypatch.setattr(
        sch,
        "_dispatch_celery",
        lambda **kw: calls.append(kw) or True,
    )
    monkeypatch.setattr(sch, "load_short_memory", lambda **_: [])
    monkeypatch.setattr(sch, "_touch_idle", lambda *a, **k: None)
    # 即使规则抽空，只要 candidate 也要立即入队
    monkeypatch.setattr(
        "app.modules.memory.service.parse_auto_extract_rules",
        lambda _t: [],
    )

    out = schedule_memory_extract(
        user_id="u1",
        conversation_id="c1",
        transcript="我的鞋码是42码",
        allow_memory_write=True,
        route_kind="chitchat",
        route_reason="chitchat",
        intent_features=["memory_candidate"],
    )
    assert out["skipped"] is False
    assert "skill_immediate" in out["scheduled"]
    assert any(
        c.get("countdown", 0) == 0 and c.get("trigger") == "skill_immediate"
        for c in calls
    )
    # 本轮已 immediate：禁止再投 idle/window，避免并发双写同 key
    assert "idle" not in out["scheduled"]
    assert "window" not in out["scheduled"]
    assert len(calls) == 1


def test_schedule_immediate_skips_window_even_when_turns_enough(monkeypatch) -> None:
    """窗口轮次已满时，若本轮已 immediate，仍不得再投 window。"""
    import app.modules.memory.extract_scheduler as sch

    calls: list[dict] = []
    monkeypatch.setattr(
        sch,
        "_dispatch_celery",
        lambda **kw: calls.append(kw) or True,
    )
    monkeypatch.setattr(
        sch,
        "load_short_memory",
        lambda **_: [{"role": "user", "content": "x"} for _ in range(20)],
    )
    monkeypatch.setattr(sch, "_touch_idle", lambda *a, **k: None)
    monkeypatch.setattr(sch, "_window_recently_fired", lambda *_: False)
    monkeypatch.setattr(
        "app.modules.memory.service.parse_auto_extract_rules",
        lambda _t: [],
    )

    out = schedule_memory_extract(
        user_id="u1",
        conversation_id="c1",
        transcript="我的手机是：15011586502",
        allow_memory_write=True,
        route_kind="chitchat",
        route_reason="chitchat",
        intent_features=["memory_candidate"],
    )
    assert "skill_immediate" in out["scheduled"]
    assert "window" not in out["scheduled"]
    assert "idle" not in out["scheduled"]
    assert [c.get("trigger") for c in calls] == ["skill_immediate"]


def test_schedule_immediate_on_email_self_intro(monkeypatch) -> None:
    """自称邮箱（Catalog 词元命中）应立即投递。"""
    import app.modules.memory.extract_scheduler as sch

    calls: list[dict] = []

    monkeypatch.setattr(
        sch,
        "_dispatch_celery",
        lambda **kw: calls.append(kw) or True,
    )
    monkeypatch.setattr(sch, "load_short_memory", lambda **_: [])
    monkeypatch.setattr(sch, "_touch_idle", lambda *a, **k: None)

    out = schedule_memory_extract(
        user_id="u1",
        conversation_id="c1",
        transcript="我的邮箱：28154232@qq.com",
        allow_memory_write=True,
        route_kind="chitchat",
    )
    assert out["skipped"] is False
    assert "skill_immediate" in out["scheduled"] or "rule_hit" in out["scheduled"]
    assert any(c.get("countdown", 0) == 0 for c in calls)


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
    assert is_explicit_remember("记住我的名字")
    assert is_explicit_remember("记住我叫张三")
    assert not is_explicit_remember("今天天气不错")


def test_schedule_immediate_on_name_self_intro(monkeypatch) -> None:
    """自称姓名话术应立即投递（不必等 idle/窗口）。"""
    import app.modules.memory.extract_scheduler as sch

    calls: list[dict] = []

    monkeypatch.setattr(
        sch,
        "_dispatch_celery",
        lambda **kw: calls.append(kw) or True,
    )
    monkeypatch.setattr(sch, "load_short_memory", lambda **_: [])
    monkeypatch.setattr(sch, "_touch_idle", lambda *a, **k: None)

    out = schedule_memory_extract(
        user_id="u1",
        conversation_id="c1",
        transcript="我的名字是：赵振明",
        allow_memory_write=True,
        route_kind="chitchat",
    )
    assert out["skipped"] is False
    assert "explicit" in out["scheduled"] or "rule_hit" in out["scheduled"]
    assert any(c.get("countdown", 0) == 0 for c in calls)
