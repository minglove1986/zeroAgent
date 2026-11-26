"""Planner 用户句启发信号（代码守卫输入，不依赖 LLM intent）。

@author 赵振明
@date 2026-09-08 15:18:00
"""

from __future__ import annotations

_WEB_KEYWORDS = (
    "天气",
    "气温",
    "降雨",
    "新闻",
    "股价",
    "汇率",
    "网上",
    "百度一下",
    "联网",
    "搜一下网",
)
_KB_KEYWORDS = (
    "知识库",
    "制度",
    "规章",
    "内部",
    "本公司",
    "员工手册",
    "请假条例",
    "请假制度",
    "从知识库",
    "查知识库",
)
_DOC_KEYWORDS = (
    "总结全文",
    "这篇文档",
    "整篇",
    "附件",
    "pdf",
    "PDF",
    "文档理解",
)


def extract_plan_signals(text: str) -> dict[str, bool]:
    """从用户问题提取 web/kb/doc 布尔信号。

    设计思路：专名词典（项目/人名）命中时强制 kb=True，避免「好友买」被拆成
    「好友」闲聊、Planner 漏排 rag_search。

    @author 赵振明
    @date 2026-11-24 17:17:16
    """
    raw = str(text or "")
    lowered = raw.lower()
    web = any(k in raw for k in _WEB_KEYWORDS)
    # 「今天」单独不够；与天气等已在词表。公开事件弱信号：有「最新」但不强绑 web
    kb = any(k in raw for k in _KB_KEYWORDS)
    if not kb:
        try:
            from app.modules.knowledge.focus_lexicon import match_details_in_text

            for hit in match_details_in_text(raw):
                if str(hit.get("kind") or "") in {"project", "person"}:
                    kb = True
                    break
        except Exception:  # noqa: BLE001
            pass
    doc = any(k in raw or k.lower() in lowered for k in _DOC_KEYWORDS)
    return {"web": web, "kb": kb, "doc": doc}
