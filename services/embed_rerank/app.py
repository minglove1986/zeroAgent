"""独立 Embedding / Rerank HTTP 服务（可替换模型）。

默认 EMBED_BACKEND=mock（确定性伪向量，便于 CI）。
生产设 EMBED_BACKEND=st 加载 sentence-transformers 模型。

@author 赵振明
@date 2026-07-22 15:20:41
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="zeroAgent embed-rerank", version="0.1.0")

EMBED_BACKEND = os.getenv("EMBED_BACKEND", "mock").lower()
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
RERANK_MODEL = os.getenv("RERANK_MODEL", "mock-rerank")
EMBED_DIM = int(os.getenv("EMBED_DIM", "512"))
DEVICE = os.getenv("DEVICE", "cpu")

_st_model = None


def _mock_embed(texts: list[str], dim: int) -> list[list[float]]:
    out: list[list[float]] = []
    for text in texts:
        digest = hashlib.sha256((text or "").encode("utf-8")).digest()
        vals: list[float] = []
        for i in range(dim):
            pair = digest[i % len(digest)] + digest[(i + 7) % len(digest)]
            vals.append((pair / 510.0) * 2.0 - 1.0)
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        out.append([v / norm for v in vals])
    return out


def _get_st_model():  # noqa: ANN202
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _st_model = SentenceTransformer(EMBED_MODEL, device=DEVICE)
    return _st_model


def embed_batch(texts: list[str]) -> tuple[str, list[list[float]]]:
    if EMBED_BACKEND == "st":
        model = _get_st_model()
        vectors = model.encode(list(texts), normalize_embeddings=True)
        return EMBED_MODEL, [list(map(float, v)) for v in vectors]
    return f"mock/{EMBED_MODEL}", _mock_embed(texts, EMBED_DIM)


def rerank_batch(query: str, documents: list[str], top_n: int) -> tuple[str, list[dict[str, Any]]]:
    """轻量 Rerank：mock 用词重叠；st 后端可换真 cross-encoder（预留）。"""
    if not documents:
        return RERANK_MODEL, []
    q_tokens = set(_tokenize(query))
    scored: list[tuple[int, float]] = []
    for i, doc in enumerate(documents):
        d_tokens = set(_tokenize(doc))
        if not q_tokens or not d_tokens:
            score = 0.0
        else:
            score = len(q_tokens & d_tokens) / float(len(q_tokens))
        scored.append((i, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    results = [{"index": i, "score": float(s)} for i, s in scored[: max(1, top_n)]]
    return RERANK_MODEL, results


def _tokenize(text: str) -> list[str]:
    """简易中英分词：连续字母数字 / 单汉字。"""
    import re

    return re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text or "")


class EmbedRequest(BaseModel):
    input: list[str] = Field(default_factory=list)


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(default_factory=list)
    top_n: int = 5


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "embed_backend": EMBED_BACKEND, "embed_model": EMBED_MODEL}


@app.post("/v1/embeddings")
def embeddings(body: EmbedRequest) -> dict[str, Any]:
    texts = list(body.input or [])
    model, vectors = embed_batch(texts)
    return {
        "model": model,
        "data": [{"index": i, "embedding": vec} for i, vec in enumerate(vectors)],
    }


@app.post("/v1/rerank")
def rerank(body: RerankRequest) -> dict[str, Any]:
    model, results = rerank_batch(body.query, list(body.documents or []), body.top_n)
    return {"model": model, "results": results}
