"""
v1 路由聚合。

@author 赵振明
@date 2026-07-21 16:19:57
"""

from fastapi import APIRouter

from app.api.v1 import (
    admin_feedbacks,
    admin_litellm,
    admin_overview,
    agents,
    approvals,
    audit_logs,
    auth,
    health,
    departments,
    intent_l2_keywords,
    kb_focus_terms,
    knowledge,
    llm_models_admin,
    llm_models_public,
    me,
    memories,
    memory_extract_fields,
    memory_extract_settings,
    menus,
    messages,
    notifications,
    prompt_templates,
    roles,
    sessions,
    system_persona,
    usage,
    users,
    web_search_engines,
    web_search_settings,
    workflows,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(users.router)
api_router.include_router(auth.router)
api_router.include_router(sessions.router)
api_router.include_router(departments.router)
api_router.include_router(knowledge.router)
api_router.include_router(kb_focus_terms.router)
api_router.include_router(agents.router)
api_router.include_router(messages.router)
api_router.include_router(llm_models_public.router)
api_router.include_router(workflows.router)
api_router.include_router(usage.router)
api_router.include_router(memories.router)
api_router.include_router(memory_extract_fields.router)
api_router.include_router(memory_extract_settings.router)
api_router.include_router(notifications.router)
api_router.include_router(prompt_templates.router)
api_router.include_router(approvals.router)
api_router.include_router(intent_l2_keywords.router)
api_router.include_router(system_persona.router)
api_router.include_router(llm_models_admin.router)
api_router.include_router(admin_litellm.router)
api_router.include_router(audit_logs.router)
api_router.include_router(admin_overview.router)
api_router.include_router(admin_feedbacks.router)
api_router.include_router(roles.router)
api_router.include_router(menus.router)
api_router.include_router(me.router)
api_router.include_router(web_search_settings.router)
api_router.include_router(web_search_settings.public_router)
api_router.include_router(web_search_engines.router)
