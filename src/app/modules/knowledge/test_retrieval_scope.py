"""RetrievalScope 解析单测：空绑定、权限交集、bounded soft 降级。

@author 赵振明
@date 2026-11-24 15:00:03
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.knowledge import scope as scope_mod
from app.modules.knowledge.scope import RetrievalScope, resolve_retrieval_scope

# 导入时保存真实 loader，供 SQL 形态断言（autouse fixture 会替换模块属性）
_REAL_LOAD_VISIBILITY_DOCS = scope_mod._load_visibility_docs

_FILTERS: dict[str, Any] = {
    "category_codes": ["hr.resume"],
    "metadata": [{"key": "person_name", "op": "eq", "value": "张三"}],
}


def _mock_db_empty_agent_kb() -> MagicMock:
    """构造 db：AgentKb 查询返回空行（模拟 Agent 未绑 KB）。"""
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


async def _resolve(db: Any, **overrides: Any) -> RetrievalScope:
    """以默认参数调用 resolve_retrieval_scope，按需覆盖。"""
    params: dict[str, Any] = {
        "query": "张三是谁",
        "agent_id": "agent_x",
        "kb_ids": None,
        "user_id": "u1",
        "department_ids": [],
        "role_ids": ["employee"],
        "is_platform_admin": False,
        "filters": _FILTERS,
        "filter_fallback": "soft",
    }
    params.update(overrides)
    return await resolve_retrieval_scope(db, **params)


@pytest.mark.asyncio
async def test_agent_unbound_kb_yields_empty_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """agent_id 有值但 AgentKb 无行 → kb_ids == []，且不得回落全库。"""
    list_all = AsyncMock(return_value=["kb_all"])
    monkeypatch.setattr(scope_mod, "list_all_kb_ids", list_all)
    filter_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", filter_mock)

    scope = await _resolve(_mock_db_empty_agent_kb())

    assert scope.kb_ids == []
    assert scope.document_ids == []
    assert "agent_unbound_kb" in scope.reason_codes
    list_all.assert_not_awaited()
    filter_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_soft_fallback_does_not_clear_document_scope_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """soft：各级过滤均空 → document_ids == []，且不得出现 None / legacy_full。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    filter_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", filter_mock)

    scope = await _resolve(MagicMock())

    assert scope.kb_ids == ["kb_1"]
    assert scope.document_ids == []
    assert scope.document_ids is not None
    assert scope.degrade_level in ("drop_meta", "drop_category")
    assert "legacy_full" not in scope.degrade_level
    # 原始 + drop_meta + drop_category 共三次
    assert filter_mock.await_count == 3


@pytest.mark.asyncio
async def test_soft_drop_meta_keeps_category_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """soft 第一级命中：保留分类、去掉 metadata，degrade=drop_meta。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    calls: list[dict[str, Any]] = []

    async def fake_filter(db: Any, *, kb_ids: list[str], filters: dict[str, Any] | None):
        calls.append(dict(filters or {}))
        return ["doc_1"] if not (filters or {}).get("metadata") else []

    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", fake_filter)

    scope = await _resolve(MagicMock())

    assert scope.document_ids == ["doc_1"]
    assert scope.degrade_level == "drop_meta"
    assert len(calls) == 2
    assert calls[1]["category_codes"] == ["hr.resume"]


@pytest.mark.asyncio
async def test_drop_category_none_from_filter_coerced_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 filter 行为：分类清空后返回 None → 强制 document_ids=[]，不得 kb 全库。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"])
    )

    async def fake_filter(db: Any, *, kb_ids: list[str], filters: dict[str, Any] | None):
        f = filters or {}
        return [] if (f.get("category_codes") or f.get("metadata")) else None

    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", fake_filter)

    scope = await _resolve(MagicMock())

    assert scope.kb_ids == ["kb_1"]
    assert scope.document_ids == []
    assert scope.degrade_level == "drop_category"
    assert "filters_empty_after_soft" in scope.reason_codes
    assert "legacy_full" not in scope.reason_codes


@pytest.mark.asyncio
async def test_metadata_only_filters_never_open_kb_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅 metadata 过滤：drop_meta 后 filter 返回 None 也不得放开为 kb 全库。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"])
    )

    async def fake_filter(db: Any, *, kb_ids: list[str], filters: dict[str, Any] | None):
        f = filters or {}
        return [] if f.get("metadata") else None

    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", fake_filter)

    scope = await _resolve(
        MagicMock(),
        filters={"metadata": [{"key": "person_name", "op": "eq", "value": "张三"}]},
    )

    assert scope.document_ids == []
    assert scope.degrade_level == "drop_category"


@pytest.mark.asyncio
async def test_legacy_full_only_allows_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """legacy_full：过滤空时才允许 document_ids=None，并打审计标。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "filter_documents_by_plan", AsyncMock(return_value=[])
    )

    scope = await _resolve(MagicMock(), filter_fallback="legacy_full")

    assert scope.document_ids is None
    assert scope.degrade_level == "legacy_full"
    assert "legacy_full" in scope.reason_codes


@pytest.mark.asyncio
async def test_no_filters_keeps_document_ids_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 filters → 不缩文档（None），degrade=none。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "filter_documents_by_plan", AsyncMock(return_value=None)
    )

    scope = await _resolve(MagicMock(), filters=None)

    assert scope.document_ids is None
    assert scope.degrade_level == "none"
    # Task 3：expr 含 kb 范围；无 filters 时不缩 document_id
    assert 'kb_id in ["kb_1"]' in scope.milvus_expr
    assert "document_id" not in scope.milvus_expr
    assert scope.focus_persons == ("张三",)


@pytest.mark.asyncio
async def test_scope_fills_expr_with_document_ids_and_person_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """分类化为 document_ids 后写入 expr；人名只进 person_name，不进 project_name；无 category 等值。"""
    monkeypatch.setattr(scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"]))
    monkeypatch.setattr(scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"]))
    monkeypatch.setattr(
        scope_mod, "filter_documents_by_plan", AsyncMock(return_value=["d1", "d2"])
    )
    monkeypatch.setattr(scope_mod, "apply_document_visibility", AsyncMock(return_value=["d1", "d2"]))

    scope = await _resolve(MagicMock(), query="唐亮是谁")

    assert scope.document_ids == ["d1", "d2"]
    assert 'document_id in ["d1", "d2"]' in scope.milvus_expr
    assert 'person_name == "唐亮"' in scope.milvus_expr
    assert "project_name" not in scope.milvus_expr
    assert "category_codes" not in scope.milvus_expr
    assert scope.focus_persons == ("唐亮",)
    assert scope.focus_projects == ()


@pytest.mark.asyncio
async def test_scope_document_ids_overflow_skips_expr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """document_ids 超过 64：不进 expr，打 overflow 标，document_ids 仍保留供回表过滤。"""
    many = [f"d{i}" for i in range(65)]
    monkeypatch.setattr(scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"]))
    monkeypatch.setattr(scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"]))
    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", AsyncMock(return_value=many))
    monkeypatch.setattr(scope_mod, "apply_document_visibility", AsyncMock(return_value=many))

    scope = await _resolve(MagicMock(), query="唐亮是谁")

    assert scope.document_ids == many
    assert "document_id" not in scope.milvus_expr
    assert "document_ids_overflow_skip_expr" in scope.reason_codes


@pytest.mark.asyncio
async def test_bound_kb_intersects_permission_and_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """绑定 ∩ 用户有权 ∩ 显式 kb_ids。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1", "kb_2", "kb_3"])
    )
    monkeypatch.setattr(
        scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_2", "kb_3"])
    )
    monkeypatch.setattr(
        scope_mod, "filter_documents_by_plan", AsyncMock(return_value=None)
    )

    scope = await _resolve(MagicMock(), kb_ids=["kb_1", "kb_2"], filters=None)

    assert scope.kb_ids == ["kb_2"]


@pytest.mark.asyncio
async def test_no_agent_non_admin_uses_accessible_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 agent_id 且非管理员：普通范围只取用户并集；全库仅作 public 扩大候选池。"""
    list_all = AsyncMock(return_value=["kb_all"])
    monkeypatch.setattr(scope_mod, "list_all_kb_ids", list_all)
    monkeypatch.setattr(
        scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_9"])
    )
    monkeypatch.setattr(
        scope_mod, "filter_documents_by_plan", AsyncMock(return_value=None)
    )

    scope = await _resolve(MagicMock(), agent_id=None, filters=None)

    # kb_all 无 public 文档 → 不进入范围（C1：全库仅作候选池）
    assert scope.kb_ids == ["kb_9"]


@pytest.mark.asyncio
async def test_platform_admin_with_explicit_kb(monkeypatch: pytest.MonkeyPatch) -> None:
    """platform_admin 跳过权限过滤；显式 kb_ids 仍受 agent 绑定约束。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1", "kb_2"])
    )
    perm = AsyncMock(return_value=[])
    monkeypatch.setattr(scope_mod, "list_accessible_kb_ids", perm)
    monkeypatch.setattr(
        scope_mod, "filter_documents_by_plan", AsyncMock(return_value=None)
    )

    scope = await _resolve(
        MagicMock(), is_platform_admin=True, user_id=None, kb_ids=["kb_2", "kb_x"], filters=None
    )

    assert scope.kb_ids == ["kb_2"]
    perm.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_admin_without_user_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """非管理员且无 user_id → 空范围（不放行）。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"])
    )

    scope = await _resolve(MagicMock(), user_id=None)

    assert scope.kb_ids == []
    assert scope.document_ids == []
    assert "no_user" in scope.reason_codes


@pytest.mark.asyncio
async def test_invalid_filter_fallback_rejected() -> None:
    """未知 filter_fallback 直接拒绝，避免静默放宽。"""
    with pytest.raises(ValueError):
        await _resolve(MagicMock(), filter_fallback="full")


# ---------------------------------------------------------------------------
# Task 2：apply_document_visibility（§8.2 三态）
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _default_visibility_loaders(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认：文档均无 override 且属于首个 KB、KB 无归属部门，避免既有用例触达真实 DB。"""

    async def passthrough(
        db: Any, *, kb_ids: list[str], document_ids: list[str] | None, only_overridden: bool
    ) -> list[tuple[str, str, str | None]]:
        if document_ids is None or only_overridden:
            return []
        return [(d, kb_ids[0], None) for d in document_ids]

    monkeypatch.setattr(scope_mod, "_load_visibility_docs", passthrough)
    monkeypatch.setattr(scope_mod, "_load_kb_owner_departments", AsyncMock(return_value={}))


def _patch_visibility(
    monkeypatch: pytest.MonkeyPatch,
    docs: list[tuple[str, str, str | None]],
    owners: dict[str, str | None],
) -> None:
    """按 kb_ids / document_ids / only_overridden 模拟 Document 查询。"""

    async def fake_docs(
        db: Any,
        *,
        kb_ids: list[str],
        document_ids: list[str] | None,
        only_overridden: bool,
    ) -> list[tuple[str, str, str | None]]:
        out = [d for d in docs if d[1] in kb_ids]
        if document_ids is not None:
            out = [d for d in out if d[0] in document_ids]
        if only_overridden:
            out = [d for d in out if d[2] is not None]
        return out

    async def fake_owners(db: Any, kb_ids: list[str]) -> dict[str, str | None]:
        return {k: v for k, v in owners.items() if k in kb_ids}

    monkeypatch.setattr(scope_mod, "_load_visibility_docs", fake_docs)
    monkeypatch.setattr(scope_mod, "_load_kb_owner_departments", fake_owners)


async def _visibility(**overrides: Any) -> list[str] | None:
    """以默认参数调用 apply_document_visibility。"""
    params: dict[str, Any] = {
        "kb_ids": ["kb_1"],
        "base_document_ids": None,
        "user_id": "u1",
        "department_ids": ["dept_a"],
        "is_platform_admin": False,
    }
    params.update(overrides)
    return await scope_mod.apply_document_visibility(MagicMock(), **params)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_visibility_null_override_keeps_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """null 跟随 KB：已授权 KB 内保持 base 不变。"""
    _patch_visibility(monkeypatch, [("d1", "kb_1", None), ("d2", "kb_1", None)], {"kb_1": "dept_x"})
    assert await _visibility(base_document_ids=["d1", "d2"]) == ["d1", "d2"]


@pytest.mark.asyncio
async def test_visibility_department_override_drops_foreign_dept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """department 收窄：KB public 但用户部门不匹配归属部门 → 剔除；匹配 → 保留。"""
    docs = [("d1", "kb_1", None), ("d2", "kb_1", "department")]
    _patch_visibility(monkeypatch, docs, {"kb_1": "dept_x"})
    assert await _visibility(base_document_ids=["d1", "d2"]) == ["d1"]
    assert await _visibility(base_document_ids=["d1", "d2"], department_ids=["dept_x"]) == [
        "d1",
        "d2",
    ]


@pytest.mark.asyncio
async def test_visibility_department_override_without_owner_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KB 无归属部门时 department 文档无人匹配 → 剔除（fail-closed）。"""
    _patch_visibility(monkeypatch, [("d2", "kb_1", "department")], {"kb_1": None})
    assert await _visibility(base_document_ids=["d2"]) == []


@pytest.mark.asyncio
async def test_visibility_base_none_narrowed_to_explicit_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """base=None 且存在被剔除的 department 文档 → 返回显式列表（含其余全部文档）。"""
    docs = [("d1", "kb_1", None), ("d2", "kb_1", "department")]
    _patch_visibility(monkeypatch, docs, {"kb_1": "dept_x"})
    assert await _visibility(base_document_ids=None) == ["d1"]


@pytest.mark.asyncio
async def test_visibility_base_none_unchanged_stays_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """base=None 且无需收窄/扩大 → 保持 None。"""
    docs = [("d1", "kb_1", None), ("d2", "kb_1", "public"), ("d3", "kb_1", "department")]
    _patch_visibility(monkeypatch, docs, {"kb_1": "dept_a"})
    assert await _visibility(base_document_ids=None) is None


@pytest.mark.asyncio
async def test_visibility_empty_base_stays_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """base=[] 保持 []，即使存在 public 文档也不得放宽。"""
    _patch_visibility(monkeypatch, [("d1", "kb_1", "public")], {"kb_1": "dept_a"})
    assert await _visibility(base_document_ids=[], extra_kb_ids=["kb_2"]) == []


@pytest.mark.asyncio
async def test_visibility_public_expands_from_unauthorized_kb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """public 扩大：Agent 已绑但用户无权的 KB 中，仅 public 文档可见。"""
    docs = [
        ("d1", "kb_1", None),
        ("p1", "kb_2", "public"),
        ("x1", "kb_2", None),
        ("x2", "kb_2", "department"),
    ]
    _patch_visibility(monkeypatch, docs, {"kb_1": "dept_a", "kb_2": "dept_x"})
    # base=None：授权 KB 全部文档 + 无权 KB 的 public 文档
    assert await _visibility(base_document_ids=None, extra_kb_ids=["kb_2"]) == ["d1", "p1"]
    # base 为列表（filter 已在宽范围上跑）：无权 KB 的非 public 被剔除
    assert await _visibility(
        base_document_ids=["d1", "p1", "x1", "x2"], extra_kb_ids=["kb_2"]
    ) == ["d1", "p1"]


@pytest.mark.asyncio
async def test_visibility_admin_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """平台管理员不做文档级过滤，原样返回。"""
    docs = AsyncMock(return_value=[])
    monkeypatch.setattr(scope_mod, "_load_visibility_docs", docs)
    assert await _visibility(is_platform_admin=True, base_document_ids=["d9"]) == ["d9"]
    assert await _visibility(is_platform_admin=True, base_document_ids=None) is None
    docs.assert_not_awaited()


@pytest.mark.asyncio
async def test_visibility_empty_kb_ids_non_admin_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2：非管理员 kb_ids 为空且无 extra → []（禁止 fail-open 回传 base），不查库。"""
    docs = AsyncMock(return_value=[])
    monkeypatch.setattr(scope_mod, "_load_visibility_docs", docs)
    assert await _visibility(kb_ids=[], base_document_ids=["d1"]) == []
    assert await _visibility(kb_ids=[], base_document_ids=None) == []
    docs.assert_not_awaited()


@pytest.mark.asyncio
async def test_visibility_empty_kb_ids_with_extra_scans_public_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2：kb_ids 为空但有 extra → 仅 public 文档可见，其 kb 写入出参。"""
    docs = [("p1", "kb_2", "public"), ("x1", "kb_2", None), ("x2", "kb_2", "department")]
    _patch_visibility(monkeypatch, docs, {"kb_2": "dept_a"})
    added: list[str] = []
    out = await _visibility(
        kb_ids=[], base_document_ids=None, extra_kb_ids=["kb_2"], added_kb_ids=added
    )
    assert out == ["p1"]
    assert added == ["kb_2"]
    # 无 public 文档 → []，不得为 None
    _patch_visibility(monkeypatch, [("x1", "kb_2", None)], {})
    assert await _visibility(kb_ids=[], base_document_ids=None, extra_kb_ids=["kb_2"]) == []


@pytest.mark.asyncio
async def test_visibility_unknown_override_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M1：未知 visibility_override 取值对非管理员一律剔除（列表与 None 两条路径）。"""
    docs = [("d1", "kb_1", None), ("s1", "kb_1", "secret"), ("e1", "kb_1", "")]
    _patch_visibility(monkeypatch, docs, {"kb_1": "dept_a"})
    assert await _visibility(base_document_ids=["d1", "s1", "e1"]) == ["d1"]
    assert await _visibility(base_document_ids=None) == ["d1"]


@pytest.mark.asyncio
async def test_agent_kb_load_filters_soft_deleted_kb() -> None:
    """M3：Agent 绑定读取需 join 并过滤已软删 KB。"""
    captured: list[Any] = []
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["kb_1"]

    async def fake_execute(stmt: Any) -> Any:
        captured.append(stmt)
        return result

    db = MagicMock()
    db.execute = fake_execute
    assert await scope_mod._load_agent_kb_ids(db, "agent_x") == ["kb_1"]
    sql = str(captured[0]).lower()
    assert "knowledge_bases.deleted_at is null" in sql


@pytest.mark.asyncio
async def test_visibility_doc_loader_filters_soft_deleted_kb() -> None:
    """M3：文档可见性加载需过滤已软删 KB / 未发布 / 已软删文档。"""
    captured: list[Any] = []
    result = MagicMock()
    result.all.return_value = []

    async def fake_execute(stmt: Any) -> Any:
        captured.append(stmt)
        return result

    db = MagicMock()
    db.execute = fake_execute
    # autouse fixture 已替换模块属性，这里使用导入时保存的真实实现
    await _REAL_LOAD_VISIBILITY_DOCS(
        db, kb_ids=["kb_1"], document_ids=None, only_overridden=True
    )
    sql = str(captured[0]).lower()
    assert "knowledge_bases.deleted_at is null" in sql
    assert "documents.deleted_at is null" in sql
    assert "documents.status" in sql


@pytest.mark.asyncio
async def test_resolve_wires_visibility_and_expands_kb_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve 末尾接入：department 文档剔除；public 文档所在无权 KB 并入 kb_ids。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1", "kb_2"])
    )
    monkeypatch.setattr(
        scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "filter_documents_by_plan", AsyncMock(return_value=None)
    )
    docs = [
        ("d1", "kb_1", None),
        ("d2", "kb_1", "department"),
        ("p1", "kb_2", "public"),
        ("x1", "kb_2", None),
    ]
    _patch_visibility(monkeypatch, docs, {"kb_1": "dept_x", "kb_2": "dept_x"})

    scope = await _resolve(MagicMock(), filters=None, department_ids=["dept_a"])

    assert scope.kb_ids == ["kb_1", "kb_2"]
    assert scope.document_ids == ["d1", "p1"]
    assert "visibility_applied" in scope.reason_codes


@pytest.mark.asyncio
async def test_resolve_visibility_empty_result_stays_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """可见性后文档为空 → document_ids == []，不得退化为 None。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "filter_documents_by_plan", AsyncMock(return_value=["d2"])
    )
    _patch_visibility(monkeypatch, [("d2", "kb_1", "department")], {"kb_1": "dept_x"})

    scope = await _resolve(MagicMock(), department_ids=["dept_a"])

    assert scope.document_ids == []


@pytest.mark.asyncio
async def test_resolve_admin_skips_visibility(monkeypatch: pytest.MonkeyPatch) -> None:
    """platform_admin 不进入可见性收窄。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"])
    )
    monkeypatch.setattr(
        scope_mod, "filter_documents_by_plan", AsyncMock(return_value=None)
    )
    loader = AsyncMock(return_value=[("d2", "kb_1", "department")])
    monkeypatch.setattr(scope_mod, "_load_visibility_docs", loader)

    scope = await _resolve(MagicMock(), is_platform_admin=True, user_id=None, filters=None)

    assert scope.document_ids is None
    loader.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_sole_bound_dept_kb_with_public_doc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1：唯一绑定 KB 为部门库且用户无权，但含 public 文档 → 范围含该文档，不提前判空。"""
    monkeypatch.setattr(scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_2"]))
    monkeypatch.setattr(scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", AsyncMock(return_value=None))
    docs = [("p1", "kb_2", "public"), ("x1", "kb_2", None), ("x2", "kb_2", "department")]
    _patch_visibility(monkeypatch, docs, {"kb_2": "dept_x"})

    scope = await _resolve(MagicMock(), filters=None, department_ids=["dept_a"])

    assert scope.kb_ids == ["kb_2"]
    assert scope.document_ids == ["p1"]
    assert "kb_scope_empty" not in scope.reason_codes
    assert "visibility_applied" in scope.reason_codes


@pytest.mark.asyncio
async def test_resolve_sole_bound_dept_kb_without_public_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1：无权 KB 内无 public 文档 → 空范围（扩大后仍空才判空）。"""
    monkeypatch.setattr(scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_2"]))
    monkeypatch.setattr(scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", AsyncMock(return_value=None))
    _patch_visibility(monkeypatch, [("x1", "kb_2", None)], {"kb_2": "dept_x"})

    scope = await _resolve(MagicMock(), filters=None)

    assert scope.kb_ids == []
    assert scope.document_ids == []
    assert "kb_scope_empty" in scope.reason_codes


@pytest.mark.asyncio
async def test_resolve_no_agent_loads_public_docs_and_respects_explicit_kb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1：无 agent 的系统对话也能通过 public override 看到无权 KB 的公开文档；尊重显式 kb_ids。"""
    monkeypatch.setattr(
        scope_mod, "list_all_kb_ids", AsyncMock(return_value=["kb_1", "kb_2", "kb_3"])
    )
    monkeypatch.setattr(scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"]))
    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", AsyncMock(return_value=None))
    docs = [
        ("d1", "kb_1", None),
        ("p2", "kb_2", "public"),
        ("p3", "kb_3", "public"),
    ]
    _patch_visibility(monkeypatch, docs, {"kb_1": "dept_a"})

    scope = await _resolve(MagicMock(), agent_id=None, filters=None)
    assert scope.kb_ids == ["kb_1", "kb_2", "kb_3"]
    assert scope.document_ids == ["d1", "p2", "p3"]

    # 显式 kb_ids 仅含 kb_2：kb_1（有权）与 kb_3 都被排除，只剩 kb_2 的 public 文档
    scope = await _resolve(MagicMock(), agent_id=None, filters=None, kb_ids=["kb_2"])
    assert scope.kb_ids == ["kb_2"]
    assert scope.document_ids == ["p2"]


@pytest.mark.asyncio
async def test_resolve_invisible_filter_hit_does_not_block_soft_degrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H1：无权 KB 内不可见文档命中 filter，不得阻断 soft 降级；视为未命中继续 drop_meta。"""
    monkeypatch.setattr(
        scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1", "kb_2"])
    )
    monkeypatch.setattr(scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"]))

    async def fake_filter(db: Any, *, kb_ids: list[str], filters: dict[str, Any] | None):
        # 带 metadata 时只命中无权 KB 的非 public 文档；去掉 metadata 后命中有权文档
        return ["x1"] if (filters or {}).get("metadata") else ["d1"]

    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", fake_filter)
    _patch_visibility(
        monkeypatch,
        [("d1", "kb_1", None), ("x1", "kb_2", None)],
        {"kb_1": "dept_a"},
    )

    scope = await _resolve(MagicMock())

    assert scope.document_ids == ["d1"]
    assert scope.degrade_level == "drop_meta"
    assert scope.kb_ids == ["kb_1"]


@pytest.mark.asyncio
async def test_resolve_calls_public_apply_document_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M2：resolve 使用公开入口 apply_document_visibility。"""
    monkeypatch.setattr(scope_mod, "_load_agent_kb_ids", AsyncMock(return_value=["kb_1"]))
    monkeypatch.setattr(scope_mod, "list_accessible_kb_ids", AsyncMock(return_value=["kb_1"]))
    monkeypatch.setattr(scope_mod, "filter_documents_by_plan", AsyncMock(return_value=None))
    spy = AsyncMock(return_value=None)
    monkeypatch.setattr(scope_mod, "apply_document_visibility", spy)

    scope = await _resolve(MagicMock(), filters=None)

    spy.assert_awaited_once()
    assert spy.await_args.kwargs["kb_ids"] == ["kb_1"]
    assert scope.document_ids is None
