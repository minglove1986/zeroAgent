"""问答 expected_chunk_hint 与原文对齐（提高命中测试可测性）。

@author 赵振明
@date 2026-11-23 09:25:20
"""

from __future__ import annotations

import re


def strip_markdown_noise(text: str) -> str:
    """去掉常见 markdown 噪声（反引号、粗体标记），保留正文。"""
    s = (text or "").strip()
    if not s:
        return ""
    s = s.replace("`", "")
    s = re.sub(r"\*+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def hint_in_text(hint: str, text: str) -> bool:
    """判断 hint 是否出现在 text 中（含去噪/去空白宽松匹配）。"""
    h = (hint or "").strip()
    t = text or ""
    if not h or not t:
        return False
    if h in t:
        return True
    hn = strip_markdown_noise(h)
    if hn and hn in t:
        return True
    if hn and hn in strip_markdown_noise(t):
        return True
    hn_compact = re.sub(r"\s+", "", hn)
    t_compact = re.sub(r"\s+", "", strip_markdown_noise(t))
    return bool(hn_compact) and hn_compact in t_compact


def align_hint_to_corpus(hint: str, corpus: list[str], *, min_len: int = 10, max_len: int = 40) -> str:
    """将模型 hint 对齐为语料中真实连续子串；失败则从最长切块截取。

    设计思路：命中测试按「hint ⊆ topK 切块正文」判分；LLM 常加反引号或改写，
    此处强制回落到原文窗口，避免「全文都匹配不到」的假失败。
    """
    cleaned = strip_markdown_noise(hint)
    texts = [c for c in corpus if (c or "").strip()]
    if not texts:
        return cleaned[:max_len]

    if cleaned and any(hint_in_text(cleaned, c) for c in texts):
        # 已是原文（或去噪后仍命中）：尽量返回去噪版且长度受限
        for c in texts:
            if cleaned in c:
                return cleaned[:max_len]
            cn = strip_markdown_noise(c)
            if cleaned in cn:
                # 在去噪语料中命中时，仍返回 cleaned（已无反引号）
                return cleaned[:max_len]
        return cleaned[:max_len]

    # 滑动窗口：从长到短找第一个出现在某切块中的子串
    if cleaned:
        upper = min(max_len, len(cleaned))
        lower = min(min_len, upper)
        for length in range(upper, lower - 1, -1):
            for start in range(0, len(cleaned) - length + 1):
                sub = cleaned[start : start + length]
                for c in texts:
                    if sub in c:
                        return sub

    # 关键词重叠：挑包含最多 hint 字符的切块，截取可读窗口
    seed = cleaned or hint or ""
    best = texts[0]
    best_score = -1
    tokens = [t for t in re.split(r"[\s，。；、：:（）()【】\[\]`]+", seed) if len(t) >= 2]
    for c in texts:
        score = sum(1 for t in tokens if t in c) if tokens else 0
        if seed and seed[:8] in c:
            score += 3
        if score > best_score:
            best_score = score
            best = c
    window = re.sub(r"\s+", " ", best).strip()
    if len(window) <= max_len:
        return window
    # 尽量落在句号附近
    cut = window[:max_len]
    for sep in ("。", "；", "！", "？", ".", ";", " "):
        idx = cut.rfind(sep)
        if idx >= min_len:
            return cut[: idx + (1 if sep != " " else 0)].strip()
    return cut.strip()


def align_qa_items_to_corpus(
    items: list[dict[str, str]],
    corpus: list[str],
) -> list[dict[str, str]]:
    """批量对齐 QA 的 expected_chunk_hint。"""
    out: list[dict[str, str]] = []
    for it in items:
        q = str(it.get("question") or "").strip()
        if not q:
            continue
        hint = align_hint_to_corpus(str(it.get("expected_chunk_hint") or ""), corpus)
        out.append({"question": q, "expected_chunk_hint": hint})
    return out
