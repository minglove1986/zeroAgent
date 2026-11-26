"""菜单数据模型（PRD §5.2）。

@author 赵振明
@date 2026-08-11 13:34:50
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Menu(Base):
    """菜单定义：admin-web + web 共享一套菜单。"""

    __tablename__ = "menus"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    app: Mapped[str] = mapped_column(
        String(16), nullable=False, default="both"
    )  # admin / web / both
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# === 菜单种子（与主 PRD §5.6 / 5.7 + 权限用户菜单PRD §9.1 对齐） ===

BUILTIN_MENUS: tuple[tuple, ...] = (
    # (code, name, icon, path, parent_code, sort, app)
    ("overview", "总览", "DashboardOutlined", "/overview", None, 10, "admin"),
    ("group.agents", "智能体", None, None, None, 20, "admin"),
    ("agents", "Agent 管理", "RobotOutlined", "/agents", "group.agents", 21, "admin"),
    ("skills", "技能管理", "ThunderboltOutlined", "/skills", "group.agents", 22, "admin"),
    ("models", "模型与服务商", "CloudOutlined", "/system/llm-models", "group.agents", 23, "admin"),
    ("prompts", "Prompt 模板", "FileTextOutlined", "/prompts", "group.agents", 24, "admin"),
    ("group.knowledge", "知识与编排", None, None, None, 30, "admin"),
    ("knowledge", "知识库", "BookOutlined", "/knowledge", "group.knowledge", 31, "admin"),
    ("workflows", "工作流", "BranchesOutlined", "/workflows", "group.knowledge", 32, "admin"),
    ("kg", "知识图谱", "NodeIndexOutlined", "/knowledge-graph", "group.knowledge", 33, "admin"),
    ("knowledge.focus-terms", "检索专名", "TagOutlined",
     "/knowledge/focus-terms", "group.knowledge", 36, "admin"),
    ("group.system", "系统治理", None, None, None, 40, "admin"),
    ("system.memory-fields", "记忆抽取白名单", "FilterOutlined",
     "/system/memory-fields", "group.system", 41, "admin"),
    ("system.l2-keywords", "L2 关键词规则", "TagsOutlined",
     "/system/l2-keywords", "group.system", 42, "admin"),
    ("system.persona", "系统人格", "UserOutlined",
     "/system/persona", "group.system", 43, "admin"),
    ("group.org", "组织权限", None, None, None, 50, "admin"),
    ("org.users", "用户管理", "TeamOutlined", "/organization/users", "group.org", 51, "admin"),
    ("org.roles", "角色权限", "SafetyCertificateOutlined",
     "/organization/roles", "group.org", 52, "admin"),
    ("org.departments", "部门管理", "ApartmentOutlined",
     "/organization/departments", "group.org", 53, "admin"),
    ("org.menus", "菜单管理", "MenuOutlined",
     "/organization/menus", "group.org", 54, "admin"),
    ("group.operations", "运维审计", None, None, None, 60, "admin"),
    ("operations.usage", "用量成本", "BarChartOutlined",
     "/operations/usage", "group.operations", 61, "admin"),
    ("operations.alerts", "通知告警", "BellOutlined",
     "/operations/alerts", "group.operations", 62, "admin"),
    ("operations.audit", "配置审计", "AuditOutlined",
     "/operations/audit", "group.operations", 63, "admin"),
    ("chat", "系统对话", "MessageOutlined", "/chat", None, 10, "web"),
    ("profile", "个人中心", "UserOutlined", "/profile", None, 20, "web"),
)

# 平台管理员默认可见菜单（主 PRD D37：含记忆白名单 / L2 / 系统人格）
PLATFORM_ADMIN_DEFAULT_MENU_CODES: frozenset[str] = frozenset(
    {m[0] for m in BUILTIN_MENUS if m[6] == "admin"}
)