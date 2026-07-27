"""本地 BM25（Hybrid 稀疏侧回落；不依赖外部模型）。

@author 赵振明
@date 2026-07-22 15:22:10
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Sequence


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text or "")


def bm25_scores(
    query: str,
    documents: Sequence[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """对 documents 计算相对 query 的 BM25 分数。"""
    q_tokens = tokenize(query)
    if not q_tokens or not documents:
        return [0.0] * len(documents)

    docs_tokens = [tokenize(d) for d in documents]
    n = len(docs_tokens)
    avgdl = sum(len(t) for t in docs_tokens) / float(n) or 1.0

    df: Counter[str] = Counter()
    for toks in docs_tokens:
        for term in set(toks):
            df[term] += 1

    scores: list[float] = []
    q_tf = Counter(q_tokens)
    for toks in docs_tokens:
        tf = Counter(toks)
        dl = len(toks) or 1
        score = 0.0
        for term, qf in q_tf.items():
            if term not in tf:
                continue
            n_q = df.get(term, 0)
            idf = math.log(1.0 + (n - n_q + 0.5) / (n_q + 0.5))
            freq = tf[term]
            denom = freq + k1 * (1.0 - b + b * dl / avgdl)
            score += idf * (freq * (k1 + 1.0) / denom) * qf
        scores.append(float(score))
    return scores


def rrf_fuse(
    ranked_lists: list[list[str]],
    *,
    k: int = 60,
    limit: int = 50,
    secondary: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion；同分时用 secondary（如 BM25 分）打破平局。"""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    sec = secondary or {}
    ordered = sorted(
        scores.items(),
        key=lambda x: (x[1], sec.get(x[0], 0.0)),
        reverse=True,
    )
    return ordered[:limit]
