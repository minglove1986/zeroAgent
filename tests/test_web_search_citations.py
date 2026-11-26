"""联网搜索 items → citations 映射单测（P0 出处）。

@author 赵振明
@date 2026-09-08 17:02:42
"""

from __future__ import annotations

from app.modules.web_search.citations import web_items_to_citations


def test_web_items_to_citations_maps_title_url_snippet() -> None:
    cites = web_items_to_citations(
        [
            {
                "title": "白宫辟谣",
                "url": "https://example.com/a",
                "snippet": "特朗普在正常工作",
            },
            {"title": "", "url": "https://example.com/b", "snippet": "x"},
        ]
    )
    assert len(cites) == 2
    assert cites[0]["title"] == "白宫辟谣"
    assert cites[0]["url"] == "https://example.com/a"
    assert cites[0]["snippet"] == "特朗普在正常工作"
    assert cites[0]["source"] == "web"
    assert cites[1]["title"] == "https://example.com/b"


def test_web_items_skips_empty() -> None:
    assert web_items_to_citations([{"title": "", "url": "", "snippet": ""}]) == []
    assert web_items_to_citations(None) == []  # type: ignore[arg-type]


def test_attach_web_citations_on_ok_payload() -> None:
    from app.modules.web_search.citations import attach_web_citations

    out = attach_web_citations(
        {
            "ok": True,
            "provider": "baidu",
            "query": "q",
            "items": [{"title": "T", "url": "https://e.com", "snippet": "s"}],
        }
    )
    assert out["citations"][0]["url"] == "https://e.com"
    assert out["citations"][0]["source"] == "web"
