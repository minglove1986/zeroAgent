"""WebSearchPolicy 单测。

@author 赵振明
@date 2026-09-07 17:22:45
"""

from __future__ import annotations

from app.modules.web_search.policy import (
    WEB_SEARCH_SKILL_ID,
    WebSearchDecision,
    decide_web_search_skill,
    filter_skill_catalog,
)


def test_decide_non_web_skill_always_allow():
    assert (
        decide_web_search_skill(
            admin_available=False,
            user_allow=False,
            skill_id="skill_datetime",
        )
        == WebSearchDecision.ALLOW
    )


def test_decide_confirm_when_admin_ok_user_deny():
    assert (
        decide_web_search_skill(
            admin_available=True,
            user_allow=False,
            skill_id=WEB_SEARCH_SKILL_ID,
        )
        == WebSearchDecision.CONFIRM
    )


def test_decide_allow_when_user_allow():
    assert (
        decide_web_search_skill(
            admin_available=True,
            user_allow=True,
            skill_id=WEB_SEARCH_SKILL_ID,
        )
        == WebSearchDecision.ALLOW
    )


def test_decide_block_when_admin_unavailable():
    assert (
        decide_web_search_skill(
            admin_available=False,
            user_allow=True,
            skill_id=WEB_SEARCH_SKILL_ID,
        )
        == WebSearchDecision.BLOCK
    )


def test_filter_catalog_removes_when_unavailable_or_excluded():
    cat = [
        {"id": "skill_datetime", "name": "时间"},
        {"id": WEB_SEARCH_SKILL_ID, "name": "联网"},
    ]
    assert len(filter_skill_catalog(cat, admin_available=True, exclude_web_search_skill=False)) == 2
    out = filter_skill_catalog(cat, admin_available=False, exclude_web_search_skill=False)
    assert [c["id"] for c in out] == ["skill_datetime"]
    out2 = filter_skill_catalog(cat, admin_available=True, exclude_web_search_skill=True)
    assert [c["id"] for c in out2] == ["skill_datetime"]
