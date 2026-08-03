"""L2 catalog 缓存与种子。

@author 赵振明
@date 2026-07-29 10:40:14
"""

from __future__ import annotations

import pytest

from app.modules.intent.l2_catalog_cache import (
    get_catalog,
    reset_l2_catalog_for_tests,
    set_fallback_catalog,
)
from app.modules.intent.l2_seed import DEFAULT_SEED


def test_default_seed_has_summarize_and_negation() -> None:
    phrases_sum = {x["phrase"] for x in DEFAULT_SEED["doc_summarize"]}
    phrases_meta = {x["phrase"] for x in DEFAULT_SEED["meta_reply"]}
    assert "总结" in phrases_sum
    assert any("没让你" in p for p in phrases_meta)


def test_get_catalog_falls_back_to_seed() -> None:
    reset_l2_catalog_for_tests()
    cat = get_catalog()
    assert "doc_summarize" in cat
    assert any(x["phrase"] == "总结" for x in cat["doc_summarize"])


def test_set_fallback_overrides_get_catalog() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(
        {
            "meta_reply": [
                {"phrase": "别总结", "match_mode": "contains", "priority": 1}
            ]
        }
    )
    cat = get_catalog()
    assert cat["meta_reply"][0]["phrase"] == "别总结"


def test_intent_l2_keyword_model_tablename() -> None:
    from app.models.intent_l2 import IntentL2Keyword

    assert IntentL2Keyword.__tablename__ == "intent_l2_keywords"


@pytest.mark.asyncio
async def test_reload_l2_catalog_sets_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.intent import l2_catalog_store as store
    from app.modules.intent.l2_catalog_cache import get_catalog, reset_l2_catalog_for_tests

    reset_l2_catalog_for_tests()
    fake = {
        "meta_reply": [{"phrase": "我没让你", "match_mode": "contains", "priority": 5}],
        "doc_summarize": [{"phrase": "总结", "match_mode": "contains", "priority": 100}],
    }

    async def _fake_ensure(_db):  # noqa: ANN001
        return 0

    async def _fake_load(_db):  # noqa: ANN001
        return fake

    redis_calls: list[dict] = []

    def _fake_redis(catalog):  # noqa: ANN001
        redis_calls.append(catalog)
        return True

    monkeypatch.setattr(store, "ensure_seed_if_empty", _fake_ensure)
    monkeypatch.setattr(store, "load_catalog_from_db", _fake_load)
    monkeypatch.setattr(store, "set_catalog_in_redis", _fake_redis)

    out = await store.reload_l2_catalog(db=None)  # type: ignore[arg-type]
    assert out["meta_reply"][0]["phrase"] == "我没让你"
    assert redis_calls and redis_calls[0]["meta_reply"][0]["phrase"] == "我没让你"
    assert get_catalog()["meta_reply"][0]["phrase"] == "我没让你"
