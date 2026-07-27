"""
v1 路由聚合。

@author 赵振明
@date 2026-07-21 16:19:57
"""

from fastapi import APIRouter

from app.api.v1 import (
    agents,
    approvals,
    auth,
    health,
    departments,
    knowledge,
    memories,
    messages,
    notifications,
    prompt_templates,
    usage,
    users,
    workflows,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(users.router)
api_router.include_router(auth.router)
api_router.include_router(departments.router)
api_router.include_router(knowledge.router)
api_router.include_router(agents.router)
api_router.include_router(messages.router)
api_router.include_router(workflows.router)
api_router.include_router(usage.router)
api_router.include_router(memories.router)
api_router.include_router(notifications.router)
api_router.include_router(prompt_templates.router)
api_router.include_router(approvals.router)
