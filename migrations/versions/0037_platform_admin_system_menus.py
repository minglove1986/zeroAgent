"""补齐 platform_admin 系统治理菜单权限（记忆白名单 / L2 / 系统人格）。

0031 种子误将 system.* 排除在 platform_admin 之外，与主 PRD D37 /
角色矩阵冲突；菜单树按 Actor.menus 过滤后侧栏「系统治理」叶子消失。

Revision ID: 0037_platform_admin_system_menus
Revises: 0036_menu_models_path
Create Date: 2026-08-11

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_platform_admin_system_menus"
down_revision: Union[str, Sequence[str], None] = "0036_menu_models_path"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 须补授的系统治理叶子（分组 group.system 已由 0032 授予）
_SYSTEM_LEAF_MENUS = (
    "system.memory-fields",
    "system.l2-keywords",
    "system.persona",
)


def upgrade() -> None:
    """为 platform_admin 补授系统治理叶子菜单可见性。"""
    conn = op.get_bind()
    for menu in _SYSTEM_LEAF_MENUS:
        conn.execute(
            sa.text(
                "INSERT IGNORE INTO role_menu_permissions "
                "(role_code, menu_code, can_view, can_edit) "
                "VALUES ('platform_admin', :menu, 1, 0)"
            ),
            {"menu": menu},
        )


def downgrade() -> None:
    """回滚：移除本次补授的 platform_admin 系统治理叶子。"""
    conn = op.get_bind()
    for menu in _SYSTEM_LEAF_MENUS:
        conn.execute(
            sa.text(
                "DELETE FROM role_menu_permissions "
                "WHERE role_code = 'platform_admin' AND menu_code = :menu"
            ),
            {"menu": menu},
        )
