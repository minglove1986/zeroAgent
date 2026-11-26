"""Phase A 检索质量闸门：空召回（G1）/ 无引用（D14）。

@author 赵振明
@date 2026-11-24 16:08:00
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CODE_NO_RECALL = "rejected_no_recall"
CODE_NO_CITATION = "rejected_no_citation"

MSG_NO_RECALL = "本轮检索未召回任何知识库内容，已拒绝展示最终答案。"
MSG_NO_CITATION = "本轮检索未产生有效引用，已拒绝展示最终答案（D14）。"


@dataclass(frozen=True)
class GateResult:
    """闸门判定结果。

    ok=True 时 code/message 为空；否则 code 为 rejected_no_recall / rejected_no_citation。

    @author 赵振明
    @date 2026-11-24 16:20:00
    """

    ok: bool
    code: str
    message: str


def evaluate_retrieval_gate(
    *, hits: list[Any], citations: list[Any], used_rag: bool
) -> GateResult:
    """判定检索结果能否进入合成/展示。

    核心逻辑：非 RAG 路径直接放行；hits 与 citations 均空 → 空召回；
    有 hits 但无 citation → D14 无引用拒展。必须在调用合成 LLM 之前执行。

    @author 赵振明
    @date 2026-11-24 16:08:00
    """
    if not used_rag:
        return GateResult(True, "", "")
    if not hits and not citations:
        return GateResult(False, CODE_NO_RECALL, MSG_NO_RECALL)
    if not citations:
        return GateResult(False, CODE_NO_CITATION, MSG_NO_CITATION)
    return GateResult(True, "", "")
