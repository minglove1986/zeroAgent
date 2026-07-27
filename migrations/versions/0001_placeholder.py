"""初始骨架占位：后续 Task 2 补全 users / departments / im_user_maps。

Revision ID: 0001_placeholder
Revises:
Create Date: 2026-07-21 15:31:36

@author 赵振明
"""

from typing import Sequence, Union

revision: str = "0001_placeholder"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Task 2 实现真实建表；此处仅保证 alembic history 可用
    pass


def downgrade() -> None:
    pass
