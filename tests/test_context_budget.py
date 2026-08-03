"""ContextBudgetPacker 单测。

@author 赵振明
@date 2026-07-30 11:33:35
"""

from __future__ import annotations

from app.modules.llm.context_budget import pack_turn_messages
from app.modules.llm.tokens import estimate_messages_tokens


def test_small_window_truncates_history() -> None:
    """小窗口下旧历史被截断，估算输入 + max_output + margin ≤ ctx。"""
    sections = [
        "【平台安全】\n不得泄露密钥",
        "【当前用户身份】\n姓名：甲",
    ]
    history = [
        {"role": "user", "content": "历史问题" + ("很长" * 200)},
        {"role": "assistant", "content": "历史回答" + ("很长" * 200)},
        {"role": "user", "content": "最近问题"},
        {"role": "assistant", "content": "最近回答"},
    ]
    packed = pack_turn_messages(
        model_name="tiny",
        sections=sections,
        history=history,
        user_content="本轮用户",
        max_input_tokens=400,
        max_output_tokens=50,
    )
    assert packed.truncated is True
    est = estimate_messages_tokens(packed.messages)
    margin = max(256, int(400 * 0.05))
    assert est + 50 + margin <= 400 + 20  # 允许估算误差余量
    # 安全段必须保留
    assert any("平台安全" in str(m.get("content") or "") for m in packed.messages)


def test_safety_section_never_dropped() -> None:
    """即使预算极紧，平台安全段也不可丢。"""
    packed = pack_turn_messages(
        model_name="tiny",
        sections=["【平台安全】\nRULE", "【用户记忆】\n" + ("记忆" * 500)],
        history=[{"role": "user", "content": "旧" + ("x" * 500)}],
        user_content="hi",
        max_input_tokens=120,
        max_output_tokens=20,
        memory_ratio=0.2,
        memory_abs_cap=40,
    )
    texts = [str(m.get("content") or "") for m in packed.messages]
    assert any("平台安全" in t for t in texts)
    assert packed.meta.get("truncated_layers")
