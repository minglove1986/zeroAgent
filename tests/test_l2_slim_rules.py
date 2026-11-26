"""L2 瘦身：金句命中 / 短词与弱词不短路。

@author 赵振明
@date 2026-09-09 10:40:00
"""

from __future__ import annotations

from app.modules.intent.l2_catalog_cache import reset_l2_catalog_for_tests, set_fallback_catalog
from app.modules.intent.l2_seed import DEFAULT_SEED
from app.modules.intent.rules import match_l2_rules


def setup_function() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(DEFAULT_SEED)


def test_explicit_kb_still_hits() -> None:
    d = match_l2_rules("查知识库：差旅报销")
    assert d is not None
    assert d.intent == "kb_lookup"


def test_leave_handle_gold_hits() -> None:
    for q in ("我要请假", "帮我请假明天一天", "申请年假"):
        d = match_l2_rules(q)
        assert d is not None, q
        assert d.intent == "ask_user_form", q
        assert (d.slots or {}).get("form") == "leave"


def test_leave_clue_consult_does_not_short_circuit() -> None:
    for q in ("年假有几天", "请假制度是什么"):
        assert match_l2_rules(q) is None, q


def test_summarize_no_longer_l2_doc_analyze() -> None:
    assert match_l2_rules("总结赵世龙的简历") is None
    assert match_l2_rules("这个方案不合理") is None


def test_meta_correction_still_chitchat() -> None:
    for q in (
        "别总结赵世龙的简历",
        "别帮我总结赵世龙的简历",
        "我没让你总结赵世龙的简历",
    ):
        d = match_l2_rules(q)
        assert d is not None, q
        assert d.intent == "chitchat", q


def test_weak_meta_and_person_verb_defer() -> None:
    for q in ("你怎么知道的", "刚才你说我是谁", "看看天气", "查一下张三"):
        assert match_l2_rules(q) is None, q


def test_seed_has_no_broad_doc_or_person_verbs() -> None:
    assert DEFAULT_SEED["doc_summarize"] == []
    assert DEFAULT_SEED["doc_dump"] == []
    assert DEFAULT_SEED["doc_critique"] == []
    assert DEFAULT_SEED["person_search_verb"] == []
    phrases_meta = {x["phrase"] for x in DEFAULT_SEED["meta_reply"]}
    assert "从哪里" not in phrases_meta
    assert "别总结" in phrases_meta
    assert "我没让你总结" not in phrases_meta
    assert "在知识库" not in {x["phrase"] for x in DEFAULT_SEED["explicit_kb"]}
    phrases_leave = {x["phrase"] for x in DEFAULT_SEED["leave"]}
    assert "请假" not in phrases_leave
    assert "我要请假" in phrases_leave
