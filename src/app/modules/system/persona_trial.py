"""系统人格无副作用试聊。

@author 赵振明
@date 2026-07-29 16:00:36
"""

from __future__ import annotations

from typing import Any

from app.modules.llm.gateway import chat_json
from app.modules.system.persona_store import get_persona_prompt_for_inject
from app.modules.system.platform_safety import PLATFORM_SAFETY_RULE

TRIAL_IDENTITY = "【当前用户身份】\n姓名：管理员（试聊）\n账号：admin-trial"


def build_trial_system_prompt(*, candidate_prompt: str | None) -> tuple[str, bool]:
    """组装试聊 system：安全 + 人格(可选) + 极简身份；不加载记忆。

    candidate_prompt 为 None 时用当前生效人格；空字符串表示强制不带人格段。
    返回 (system 全文, 是否注入了人格)。
    """
    sections: list[str] = [f"【平台安全】\n{PLATFORM_SAFETY_RULE}"]
    used_persona = False
    if candidate_prompt is None:
        active = get_persona_prompt_for_inject(include=True)
        if active:
            sections.append("【系统人格】\n" + active)
            used_persona = True
    else:
        text = candidate_prompt.strip()
        if text:
            sections.append("【系统人格】\n" + text)
            used_persona = True
    sections.append(TRIAL_IDENTITY)
    return "\n\n".join(sections), used_persona


async def run_persona_trial(
    *,
    message: str,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """单轮 LiteLLM 试聊；不写记忆/会话。"""
    msg = (message or "").strip()
    if not msg:
        raise ValueError("message required")
    if len(msg) > 2000:
        raise ValueError("message max 2000 chars")
    if system_prompt is not None and len(system_prompt) > 4000:
        raise ValueError("system_prompt max 4000 chars")

    system_text, used_persona = build_trial_system_prompt(candidate_prompt=system_prompt)
    reply = await chat_json(
        messages=[
            {"role": "system", "content": system_text},
            {"role": "user", "content": msg},
        ]
    )
    return {
        "reply": str(reply or "").strip(),
        "used_persona": used_persona,
        "message": msg,
    }
