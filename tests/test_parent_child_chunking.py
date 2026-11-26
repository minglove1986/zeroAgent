"""父子分块（LlamaIndex / native）。

@author 赵振明
@date 2026-11-20 14:27:01
"""

from __future__ import annotations

from app.modules.knowledge.chunking import build_parent_child_chunks, chunk_text


def test_native_parent_child_has_roles() -> None:
    text = ("甲句。" * 40) + ("乙句。" * 40)
    items = build_parent_child_chunks(
        text, backend="native", parent_size=120, child_size=40, overlap=0
    )
    assert items
    parents = [x for x in items if x["role"] == "parent"]
    children = [x for x in items if x["role"] == "child"]
    assert parents
    assert children
    assert all(c.get("parent_ordinal") is not None for c in children)


def test_llamaindex_backend_or_fallback() -> None:
    text = ("政策条款。" * 30) + "\n\n" + ("实施细则。" * 30)
    items = build_parent_child_chunks(
        text, backend="llamaindex", parent_size=200, child_size=80, overlap=10
    )
    assert any(x["role"] == "child" for x in items)
    assert all(x["content"].strip() for x in items)


def test_legacy_chunk_text_unchanged() -> None:
    assert chunk_text("hello world", size=5, overlap=1)
