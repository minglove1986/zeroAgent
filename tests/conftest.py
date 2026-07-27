"""测试全局：强制 MOCK_EXTERNAL，避免打到真实 LiteLLM。

@author 赵振明
@date 2026-07-21 16:58:11
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _force_mock_external(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
