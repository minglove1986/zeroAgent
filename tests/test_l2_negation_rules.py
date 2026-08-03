"""L2 否定门禁。

@author 赵振明
@date 2026-07-29 10:43:00
"""

from __future__ import annotations

from app.modules.intent.l2_catalog_cache import reset_l2_catalog_for_tests, set_fallback_catalog
from app.modules.intent.l2_seed import DEFAULT_SEED
from app.modules.intent.rules import match_l2_rules


def setup_function() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(DEFAULT_SEED)


def test_user_correction_not_doc_summarize() -> None:
    d = match_l2_rules("我没让你总结赵世龙的简历")
    assert d is not None
    assert d.intent == "chitchat"
    assert d.funnel_layer == "L2"


def test_do_not_summarize_is_chitchat() -> None:
    d = match_l2_rules("不要总结赵世龙的简历")
    assert d is not None
    assert d.intent == "chitchat"


def test_positive_summarize_still_doc_analyze() -> None:
    d = match_l2_rules("总结赵世龙的简历")
    assert d is not None
    assert d.intent == "doc_analyze"
    assert (d.slots or {}).get("task") == "summarize"


def test_l3_system_prompt_mentions_user_correction() -> None:
    from app.modules.intent import classifier as clf

    assert "没让" in clf._L3_SYSTEM or "纠正" in clf._L3_SYSTEM

