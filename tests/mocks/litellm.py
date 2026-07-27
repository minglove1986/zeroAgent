"""LiteLLM Mock 占位。

@author 赵振明
@date 2026-07-21 15:31:36
"""


def mock_chat_stream(prompt: str) -> list[str]:
    """返回固定流式片段。"""
    return ["mock-", "reply"]
