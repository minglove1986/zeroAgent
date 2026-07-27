"""Agent 创建 schema 约束（Task 5）。

@author 赵振明
@date 2026-07-21 16:35:49
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api.schemas.agent import AgentCreate
from app.main import create_app


def test_agent_create_rejects_tool_ids_field() -> None:
    with pytest.raises(ValidationError):
        AgentCreate.model_validate(
            {
                "name": "HR助手",
                "main_model_id": "model_x",
                "skill_ids": ["skill_1"],
                "tool_ids": ["tool_http"],
            }
        )


def test_agent_create_accepts_skill_and_callable() -> None:
    m = AgentCreate.model_validate(
        {
            "name": "HR助手",
            "main_model_id": "model_x",
            "skill_ids": ["skill_1"],
            "callable_agent_ids": ["agt_finance"],
            "kb_ids": ["kb_1"],
        }
    )
    assert m.skill_ids == ["skill_1"]
    assert m.callable_agent_ids == ["agt_finance"]


@pytest.mark.asyncio
async def test_create_agent_api_rejects_tool_ids() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/agents",
            json={
                "name": "HR助手",
                "main_model_id": "model_x",
                "skill_ids": ["skill_1"],
                "tool_ids": ["tool_bad"],
            },
        )
    assert resp.status_code == 422
