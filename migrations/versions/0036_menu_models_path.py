"""修正菜单 models 路径：/models → /system/llm-models（与 admin-web 页面一致）。

Revision ID: 0036_menu_models_path
Revises: 0035_user_sessions
Create Date: 2026-08-10

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036_menu_models_path"
down_revision: Union[str, Sequence[str], None] = "0035_user_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE menus SET path = '/system/llm-models' "
            "WHERE code = 'models' AND (path IS NULL OR path = '/models')"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE menus SET path = '/models' "
            "WHERE code = 'models' AND path = '/system/llm-models'"
        )
    )
