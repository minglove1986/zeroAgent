"""KB 权限并集测试（Task 4）。

@author 赵振明
@date 2026-07-21 16:35:49
"""

from app.modules.knowledge.permissions import KbGrant, can_access_kb_union


def test_union_dept_a_or_b_grants_access() -> None:
    """用户属部门 A+B，KB 仅授 A → 并集有权。"""
    grants = [KbGrant(subject_type="department", subject_id="dept_a")]
    assert (
        can_access_kb_union(
            user_id="usr_1",
            department_ids=["dept_a", "dept_b"],
            role_ids=["role_employee"],
            grants=grants,
        )
        is True
    )


def test_no_matching_grant_denied() -> None:
    grants = [KbGrant(subject_type="department", subject_id="dept_c")]
    assert (
        can_access_kb_union(
            user_id="usr_1",
            department_ids=["dept_a", "dept_b"],
            role_ids=["role_employee"],
            grants=grants,
        )
        is False
    )


def test_user_or_role_grant() -> None:
    assert can_access_kb_union(
        user_id="usr_1",
        department_ids=[],
        role_ids=["role_hr"],
        grants=[KbGrant(subject_type="role", subject_id="role_hr")],
    )
    assert can_access_kb_union(
        user_id="usr_1",
        department_ids=[],
        role_ids=[],
        grants=[KbGrant(subject_type="user", subject_id="usr_1")],
    )
