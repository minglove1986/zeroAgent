"""会话模型上下文窗解析。

@author 赵振明
@date 2026-07-30 13:36:32
"""

from __future__ import annotations

from app.modules.llm import models_cache
from app.modules.llm.model_resolve import resolve_window_tokens


def test_resolve_window_tokens_uses_catalog_max_input(monkeypatch):
    monkeypatch.setattr(
        models_cache,
        "get_models_catalog",
        lambda: {
            "system_default": "MiniMax-M3",
            "models": [
                {
                    "model_name": "agnes-2.5-flash",
                    "max_input_tokens": 128000,
                    "enabled": True,
                },
                {
                    "model_name": "MiniMax-M3",
                    "max_input_tokens": 8000,
                    "enabled": True,
                    "is_system_default": True,
                },
            ],
        },
    )
    assert resolve_window_tokens("agnes-2.5-flash") == 128000
    assert resolve_window_tokens("MiniMax-M3") == 8000
    assert resolve_window_tokens(None) == 8000


def test_resolve_window_tokens_falls_back_to_settings(monkeypatch):
    monkeypatch.setattr(models_cache, "get_models_catalog", lambda: None)
    monkeypatch.setattr(
        "app.modules.llm.model_resolve.get_settings",
        lambda: type("S", (), {"context_window_tokens": 4096})(),
    )
    assert resolve_window_tokens("unknown-model") == 4096
