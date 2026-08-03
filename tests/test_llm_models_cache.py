"""LLM 模型目录 Redis 缓存单测。

@author 赵振明
@date 2026-07-30 11:21:08
"""

from __future__ import annotations

from app.modules.llm import models_cache as cache


def setup_function() -> None:
    cache.reset_models_catalog_for_tests()


def teardown_function() -> None:
    cache.reset_models_catalog_for_tests()


def test_empty_cache_returns_none() -> None:
    """无 Redis、无进程回填时 get 返回 None。"""
    assert cache.get_models_catalog() is None


def test_set_fallback_then_get() -> None:
    """测试/降级路径：set_models_catalog_fallback 后可读。"""
    payload = {
        "version": 1,
        "models": [{"model_name": "m1", "enabled": True}],
        "system_default": "m1",
    }
    cache.set_models_catalog_fallback(payload)
    got = cache.get_models_catalog()
    assert got is not None
    assert got["system_default"] == "m1"
    assert len(got["models"]) == 1


def test_is_degraded_flag() -> None:
    cache.mark_models_catalog_degraded(True)
    assert cache.is_degraded() is True
    cache.mark_models_catalog_degraded(False)
    assert cache.is_degraded() is False
