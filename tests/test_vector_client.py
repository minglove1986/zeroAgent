"""向量公共层测试。

@author 赵振明
@date 2026-07-22 12:22:00
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.modules.vector import client as vec_client
from app.modules.memory import milvus_store as mem_store


def test_milvus_disabled_when_uri_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("MILVUS_URI", "")
    get_settings.cache_clear()
    assert vec_client.milvus_enabled() is False
    assert mem_store.delete_memory_vector("mem_x") is False


def test_settings_embed_and_chunk_defaults() -> None:
    get_settings.cache_clear()
    s = get_settings()
    assert s.embed_dim == 512
    assert s.kb_milvus_collection == "za_kb_chunks_v2"
    assert s.kb_chunk_size == 800
    assert s.kb_chunk_overlap == 100
