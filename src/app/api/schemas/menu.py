"""菜单 API Schema（PRD §5）。

@author 赵振明
@date 2026-08-07
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MenuOut(BaseModel):
    """菜单项（含父菜单引用）。"""

    code: str
    name: str
    icon: str | None = None
    path: str | None = None
    parent_code: str | None = None
    sort: int
    app: str
    is_visible: bool
    is_builtin: bool
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class MenuTreeNode(MenuOut):
    """菜单树节点（含 children）。"""

    children: list["MenuTreeNode"] = []


MenuTreeNode.model_rebuild()