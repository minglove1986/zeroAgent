"""ORM 模型包。

@author 赵振明
@date 2026-07-21 16:19:57
"""

from app.models.agent import (
    Agent,
    AgentCallableAgent,
    AgentKb,
    AgentSkill,
    Skill,
    SkillTool,
    SkillVersion,
)
from app.models.alert_webhook import AlertWebhook
from app.models.approval import ApprovalTask
from app.modules.audit.models import ConfigAuditLog
from app.modules.system.models import SystemPersonaSetting
from app.modules.llm.catalog_models import LlmModel, LlmModelAgentBinding
from app.models.conversation import Conversation, Message, MessageCard, MessageFeedback
from app.models.department import Department, UserDepartment
from app.models.intent_l2 import IntentL2Keyword
from app.models.knowledge import (
    DocCategory,
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentQaPair,
    KbPermission,
    KnowledgeBase,
)
from app.models.memory import UserMemory
from app.models.memory_extract import MemoryExtractField
from app.models.notification import Notification
from app.models.prompt import PromptTemplate, PromptTemplateVersion
from app.models.usage import DailyUsage
from app.models.user import User
from app.models.workflow import Workflow, WorkflowInstance

__all__ = [
    "User",
    "Department",
    "UserDepartment",
    "KnowledgeBase",
    "KbPermission",
    "DocCategory",
    "DocumentCategory",
    "Document",
    "DocumentChunk",
    "DocumentQaPair",
    "Agent",
    "AgentSkill",
    "AgentCallableAgent",
    "AgentKb",
    "Skill",
    "SkillVersion",
    "SkillTool",
    "Conversation",
    "Message",
    "MessageCard",
    "MessageFeedback",
    "Workflow",
    "WorkflowInstance",
    "DailyUsage",
    "UserMemory",
    "MemoryExtractField",
    "Notification",
    "PromptTemplate",
    "PromptTemplateVersion",
    "ApprovalTask",
    "IntentL2Keyword",
    "ConfigAuditLog",
    "SystemPersonaSetting",
    "LlmModel",
    "LlmModelAgentBinding",
    "AlertWebhook",
]
