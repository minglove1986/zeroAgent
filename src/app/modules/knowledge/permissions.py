"""KB 权限并集鉴权（D13）。

@author 赵振明
@date 2026-07-22 15:01:58
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import UserDepartment
from app.models.knowledge import KbPermission, KnowledgeBase


@dataclass(frozen=True)
class KbGrant:
    subject_type: str  # user | department | role
    subject_id: str


def can_access_kb_union(
    *,
    user_id: str,
    department_ids: list[str],
    role_ids: list[str],
    grants: list[KbGrant],
) -> bool:
    """本人 ∪ 任一部门 ∪ 任一角色命中即有权；禁止交集逻辑。"""
    dept_set = set(department_ids)
    role_set = set(role_ids)
    for g in grants:
        if g.subject_type == "user" and g.subject_id == user_id:
            return True
        if g.subject_type == "department" and g.subject_id in dept_set:
            return True
        if g.subject_type == "role" and g.subject_id in role_set:
            return True
    return False


async def user_can_access_kb(
    db: AsyncSession,
    *,
    kb_id: str,
    user_id: str,
    department_ids: list[str],
    role_ids: list[str],
) -> bool:
    """单库并集鉴权；无授权行 → False。"""
    rows = (
        await db.execute(select(KbPermission).where(KbPermission.kb_id == kb_id))
    ).scalars().all()
    if not rows:
        return False
    grants = [
        KbGrant(subject_type=str(r.subject_type), subject_id=str(r.subject_id))
        for r in rows
    ]
    return can_access_kb_union(
        user_id=user_id,
        department_ids=department_ids,
        role_ids=role_ids,
        grants=grants,
    )


async def load_user_department_ids(
    db: AsyncSession,
    user_id: str,
    *,
    extra_department_id: str | None = None,
) -> list[str]:
    """用户所属部门 + Actor 上的主部门。"""
    rows = (
        await db.execute(
            select(UserDepartment.department_id).where(UserDepartment.user_id == user_id)
        )
    ).scalars().all()
    ids = {str(x) for x in rows}
    if extra_department_id:
        ids.add(str(extra_department_id))
    return sorted(ids)


async def list_accessible_kb_ids(
    db: AsyncSession,
    *,
    user_id: str,
    department_ids: list[str],
    role_ids: list[str],
) -> list[str]:
    """用户可访问的 KB；某库无任何授权行 → 拒绝。"""
    kb_ids = (
        await db.execute(
            select(KnowledgeBase.id).where(KnowledgeBase.deleted_at.is_(None))
        )
    ).scalars().all()
    if not kb_ids:
        return []

    perm_rows = (await db.execute(select(KbPermission))).scalars().all()
    by_kb: dict[str, list[KbGrant]] = defaultdict(list)
    for row in perm_rows:
        by_kb[str(row.kb_id)].append(
            KbGrant(subject_type=row.subject_type, subject_id=row.subject_id)
        )

    out: list[str] = []
    for kid in kb_ids:
        kid_s = str(kid)
        grants = by_kb.get(kid_s, [])
        if not grants:
            continue
        if can_access_kb_union(
            user_id=user_id,
            department_ids=department_ids,
            role_ids=role_ids,
            grants=grants,
        ):
            out.append(kid_s)
    return out
