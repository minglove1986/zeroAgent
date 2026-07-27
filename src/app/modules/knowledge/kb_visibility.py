"""KB 可见性与默认权限模板。

@author 赵振明
@date 2026-07-23 14:42:13
"""

from __future__ import annotations

from typing import Literal

Visibility = Literal["public", "department"]


def build_default_permission_items(
    *,
    visibility: Visibility,
    owner_department_id: str | None,
    created_by: str,
) -> list[dict[str, str]]:
    """按可见性生成并集授权行（创建 KB 时写入）。

    public: role/employee + 可选 department + user/创建者
    department: department/归属 + user/创建者（无归属则仅创建者）
    """
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(subject_type: str, subject_id: str) -> None:
        key = (subject_type, subject_id)
        if not subject_id or key in seen:
            return
        seen.add(key)
        items.append({"subject_type": subject_type, "subject_id": subject_id})

    if visibility == "public":
        _add("role", "employee")
        if owner_department_id:
            _add("department", owner_department_id)
        _add("user", created_by)
    else:
        if owner_department_id:
            _add("department", owner_department_id)
        _add("user", created_by)
    return items
