"""检索范围解析：RetrievalScope（绑定 / 权限 / 意图过滤 / bounded soft 降级）。

设计要点（见 kb-retrieval-architecture-design §4）：
- 有 agent_id 且未绑 KB → 空范围，禁止回落全库；
- 无 agent_id 的非管理员直接取用户并集，不先拉全库再碰运气；
- soft 降级最高 drop_category；document_ids=None 仅在 legacy_full 或「无需缩文档」时出现。

- Task 2：文档级 visibility_override 三态（PRD §8.2），在 filter / 降级之后收敛；
  department 收窄、public 扩大（含 Agent 已绑但用户无并集权 KB 内的 public 文档）。

- Task 3：解析末尾按 focus 分槽 + document_ids + kb_ids 填充 milvus_expr 与 focus_*；
  空范围（_empty_scope）不生成 expr；分类不写 category_codes 等值，经 document_ids 下推。

@author 赵振明
@date 2026-11-24 15:00:49
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentKb
from app.models.knowledge import Document, KnowledgeBase
from app.modules.knowledge.chunk_metadata import (
    MILVUS_DOC_ID_IN_LIMIT,
    build_milvus_filter_expr,
    parse_json_obj,
)
from app.modules.knowledge.entity_filter import FocusSlots, extract_focus_slots
from app.modules.knowledge.permissions import list_accessible_kb_ids
from app.modules.knowledge.retrieval_plan import (
    apply_category_fallback,
    apply_soft_fallback,
    filter_documents_by_plan,
)

logger = logging.getLogger(__name__)

DEGRADE_NONE = "none"
DEGRADE_DROP_META = "drop_meta"
DEGRADE_DROP_CATEGORY = "drop_category"
DEGRADE_LEGACY_FULL = "legacy_full"

_ALLOWED_FALLBACK = frozenset({"soft", "legacy_full"})


@dataclass(frozen=True)
class RetrievalScope:
    """一次检索的最终范围（不可变）。

    @author 赵振明
    @date 2026-11-24 15:00:49
    """

    kb_ids: list[str]
    # None=不缩文档；[]=空结果（调用方不得再放宽）
    document_ids: list[str] | None
    milvus_expr: str = ""
    focus_persons: tuple[str, ...] = ()
    focus_projects: tuple[str, ...] = ()
    focus_titles: tuple[str, ...] = ()
    focus_keywords: tuple[str, ...] = ()
    # none | drop_meta | drop_category | legacy_full
    degrade_level: str = DEGRADE_NONE
    reason_codes: tuple[str, ...] = ()


async def list_all_kb_ids(db: AsyncSession) -> list[str]:
    """查询全部未软删知识库 id（仅 platform_admin 无 agent 场景使用）。"""
    rows = (
        await db.execute(
            select(KnowledgeBase.id).where(KnowledgeBase.deleted_at.is_(None))
        )
    ).scalars().all()
    return [str(r) for r in rows]


async def _load_agent_kb_ids(db: AsyncSession, agent_id: str) -> list[str]:
    """读取 Agent 绑定且未软删的 KB；无绑定返回空列表（与旧 lookup 回落全库不同）。"""
    rows = (
        await db.execute(
            select(AgentKb.kb_id)
            .join(KnowledgeBase, KnowledgeBase.id == AgentKb.kb_id)
            .where(AgentKb.agent_id == agent_id, KnowledgeBase.deleted_at.is_(None))
        )
    ).scalars().all()
    # 去重保序，避免重复绑定导致重复检索
    return list(dict.fromkeys(str(x) for x in rows))


def _empty_scope(*reason_codes: str) -> RetrievalScope:
    """空范围：kb_ids 与 document_ids 均为空，下游必须直接返回零命中。"""
    return RetrievalScope(
        kb_ids=[],
        document_ids=[],
        degrade_level=DEGRADE_NONE,
        reason_codes=tuple(reason_codes),
    )


async def _resolve_kb_ids(
    db: AsyncSession,
    *,
    agent_id: str | None,
    kb_ids: list[str] | None,
    user_id: str | None,
    department_ids: list[str] | None,
    role_ids: list[str] | None,
    is_platform_admin: bool,
) -> tuple[list[str], tuple[str, ...], list[str]]:
    """解析 KB 范围：绑定 → 显式 kb_ids 交集 → 权限并集。

    返回 (ids, reason_codes, unauthorized)：
    unauthorized 仅非管理员场景非空，为「候选但用户无并集权」的 KB，仅供文档级
    public 扩大使用（PRD §8.2），不进入普通检索范围：
    - 有 agent_id：Agent 已绑定 ∩ 显式 kb_ids 中无权者；
    - 无 agent_id（系统对话）：全部未软删 KB ∩ 显式 kb_ids 中无权者。
    """
    reasons: list[str] = []
    unauthorized: list[str] = []
    accessible: set[str] | None = None

    async def _accessible() -> list[str]:
        return [
            str(x)
            for x in await list_accessible_kb_ids(
                db,
                user_id=str(user_id),
                department_ids=list(department_ids or []),
                role_ids=list(role_ids or []),
            )
        ]

    if not is_platform_admin and not user_id:
        # 非管理员缺少身份：不放行，避免权限旁路
        return [], ("no_user",), []

    if agent_id:
        ids = await _load_agent_kb_ids(db, agent_id)
        if not ids:
            return [], ("agent_unbound_kb",), []
    elif is_platform_admin:
        ids = await list_all_kb_ids(db)
    else:
        # 无 agent 的系统对话：直接用用户并集
        ids = await _accessible()
        accessible = set(ids)

    if kb_ids:
        wanted = {str(x) for x in kb_ids}
        ids = [x for x in ids if x in wanted]

    if not is_platform_admin:
        if accessible is None:
            accessible = set(await _accessible())
        if agent_id:
            unauthorized = [x for x in ids if x not in accessible]
        else:
            # 系统对话：候选池为全部未软删 KB（仅用于 public 文档扩大，不进普通范围）
            pool = await list_all_kb_ids(db)
            if kb_ids:
                wanted_set = {str(x) for x in kb_ids}
                pool = [x for x in pool if x in wanted_set]
            unauthorized = [x for x in pool if x not in accessible]
        ids = [x for x in ids if x in accessible]

    if not ids:
        reasons.append("kb_scope_empty")
    return ids, tuple(reasons), unauthorized


_IN_CHUNK = 1000


async def _load_visibility_docs(
    db: AsyncSession,
    *,
    kb_ids: list[str],
    document_ids: list[str] | None,
    only_overridden: bool,
) -> list[tuple[str, str, str | None]]:
    """加载未软删且已发布的文档 (id, kb_id, visibility_override)。

    document_ids 给定时按 id 分片 IN 查询（避免超长 IN）；
    only_overridden=True 仅返回 visibility_override 非空的行（廉价预检）。
    """
    if not kb_ids or document_ids == []:
        return []

    def _stmt(id_clause: Any = None) -> Any:
        stmt = (
            select(Document.id, Document.kb_id, Document.visibility_override)
            .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
            .where(KnowledgeBase.deleted_at.is_(None))
        ).where(
            Document.kb_id.in_(kb_ids),
            Document.deleted_at.is_(None),
            Document.status == "published",
        )
        if only_overridden:
            stmt = stmt.where(Document.visibility_override.is_not(None))
        if id_clause is not None:
            stmt = stmt.where(id_clause)
        return stmt.order_by(Document.id)

    if document_ids is None:
        rows = (await db.execute(_stmt())).all()
        return [(str(r[0]), str(r[1]), r[2]) for r in rows]

    out: list[tuple[str, str, str | None]] = []
    for i in range(0, len(document_ids), _IN_CHUNK):
        chunk = document_ids[i : i + _IN_CHUNK]
        rows = (await db.execute(_stmt(Document.id.in_(chunk)))).all()
        out.extend((str(r[0]), str(r[1]), r[2]) for r in rows)
    return out


async def _load_kb_owner_departments(
    db: AsyncSession, kb_ids: list[str]
) -> dict[str, str | None]:
    """读取 KB 归属部门；department override 以此判定部门匹配。"""
    if not kb_ids:
        return {}
    rows = (
        await db.execute(
            select(KnowledgeBase.id, KnowledgeBase.owner_department_id).where(
                KnowledgeBase.id.in_(kb_ids), KnowledgeBase.deleted_at.is_(None)
            )
        )
    ).all()
    return {str(r[0]): (str(r[1]) if r[1] else None) for r in rows}


async def apply_document_visibility(
    db: AsyncSession,
    *,
    kb_ids: list[str],
    base_document_ids: list[str] | None,
    user_id: str | None,
    department_ids: list[str],
    is_platform_admin: bool,
    extra_kb_ids: Sequence[str] = (),
    added_kb_ids: list[str] | None = None,
) -> list[str] | None:
    """null 跟随；department 收窄；public 在已授权 KB 内及 extra_kb_ids 内扩大可见文档。

    规则（PRD §8.2 / spec §4.1-3）：
    - kb_ids（已授权）内：override 为 None/public 保留；department 且用户部门 ∌ KB 归属部门
      剔除；其它未知取值一律剔除（fail-closed）；
    - extra_kb_ids（Agent 已绑 / 系统对话候选，但用户无并集权）内：仅 public 可见；
      这些文档所属 kb_id 追加写入出参 added_kb_ids（由调用方并入 scope.kb_ids）；
    - 非管理员 kb_ids 与 extra 均空 → []，禁止 fail-open；
    - base 为 [] 恒为 []；base 为 None 且无需收窄/扩大时保持 None（仅限已有授权 KB），
      否则返回显式列表；归属部门缺失时 department 文档无人匹配；
    - 仅认已发布且未软删（文档与 KB 均未软删）的文档；平台管理员原样返回。

    Args:
        added_kb_ids: 可选出参，函数先清空再写入因 public 扩大而并入的 kb_id。
    """
    if added_kb_ids is not None:
        added_kb_ids.clear()
    if is_platform_admin:
        return base_document_ids
    if not user_id:
        # 非管理员缺少身份：不放行
        return []
    authorized = set(kb_ids)
    extra = [x for x in dict.fromkeys(extra_kb_ids) if x not in authorized]
    if not authorized and not extra:
        # 无任何候选 KB：不得原样返回 base（防 fail-open）
        return []
    if base_document_ids is not None and not base_document_ids:
        return []

    scan = [*kb_ids, *extra]
    dept_set = {str(x) for x in department_ids}
    owners: dict[str, str | None] | None = None

    async def _authorized_visible(kb_id: str, override: str | None) -> bool:
        """授权 KB 内单文档可见性；未知 override 取值 fail-closed。"""
        nonlocal owners
        if override is None or override == "public":
            return True
        if override != "department":
            return False
        if owners is None:
            owners = await _load_kb_owner_departments(db, list(kb_ids))
        owner = owners.get(kb_id)
        return owner is not None and owner in dept_set

    if base_document_ids is not None:
        rows = await _load_visibility_docs(
            db, kb_ids=scan, document_ids=list(base_document_ids), only_overridden=False
        )
        meta = {r[0]: (r[1], r[2]) for r in rows}
        kept: list[str] = []
        added: list[str] = []
        for doc_id in dict.fromkeys(base_document_ids):
            found = meta.get(doc_id)
            if found is None:
                # 未发布 / 已删 / 不在范围内：不放行
                continue
            kb_id, override = found
            if kb_id in authorized:
                if not await _authorized_visible(kb_id, override):
                    continue
            elif override == "public":
                added.append(kb_id)
            else:
                continue
            kept.append(doc_id)
        if added_kb_ids is not None:
            added_kb_ids.extend(dict.fromkeys(added))
        return kept

    # base=None：先用廉价预检判断是否需要枚举
    marked = await _load_visibility_docs(
        db, kb_ids=scan, document_ids=None, only_overridden=True
    )
    denied: set[str] = set()
    public_extra: list[tuple[str, str]] = []
    for doc_id, kb_id, override in marked:
        if kb_id in authorized:
            if not await _authorized_visible(kb_id, override):
                denied.add(doc_id)
        elif override == "public":
            public_extra.append((doc_id, kb_id))
    if not denied and not public_extra:
        # 有授权 KB 且无需调整 → None；仅有候选 KB 却无 public 文档 → []
        return None if authorized else []

    # 需要收窄或扩大：枚举授权 KB 内全部已发布文档（排除 denied），再并入 public 扩大项
    all_rows = await _load_visibility_docs(
        db, kb_ids=list(kb_ids), document_ids=None, only_overridden=False
    )
    result = [r[0] for r in all_rows if r[0] not in denied]
    result.extend(d for d, _ in public_extra)
    if added_kb_ids is not None:
        added_kb_ids.extend(dict.fromkeys(k for _, k in public_extra))
    return list(dict.fromkeys(result))


def _expand_slot(terms: Sequence[str]) -> list[str]:
    """槽内专名展开别名（仅同槽内展开，不跨槽）；词典不可用时原样返回。"""
    if not terms:
        return []
    try:
        from app.modules.knowledge.focus_lexicon import expand_match_strings

        return expand_match_strings(terms)
    except Exception:  # noqa: BLE001 — 词典不可用不阻断检索
        return list(terms)


def _build_scope_expr(
    kb_ids: list[str],
    document_ids: list[str] | None,
    slots: FocusSlots,
) -> tuple[str, tuple[str, ...]]:
    """由 KB 范围 + 文档范围 + 分槽专名组装 milvus_expr，返回 (expr, reason_codes)。

    - 人名/项目/标题各用各的槽，keywords 不进 expr（CSV 字段，spec §5.3）；
    - 分类已在上游化为 document_ids，这里不写 category_codes 条件；
    - document_ids 超过 MILVUS_DOC_ID_IN_LIMIT 时不写入 expr，打
      ``document_ids_overflow_skip_expr``，由检索回表阶段按 document_ids 过滤。
    """
    reasons: list[str] = []
    if document_ids is not None and len(document_ids) > MILVUS_DOC_ID_IN_LIMIT:
        reasons.append("document_ids_overflow_skip_expr")
    expr = build_milvus_filter_expr(
        kb_ids=kb_ids,
        person_names=_expand_slot(slots.persons),
        project_names=_expand_slot(slots.projects),
        title_terms=_expand_slot(slots.titles),
        document_ids=document_ids,
    )
    return expr, tuple(reasons)


async def _match_focus_document_ids(
    db: AsyncSession,
    *,
    kb_ids: list[str],
    slots: FocusSlots,
) -> list[str] | None:
    """专名 → 文档 id 列表。

    返回约定：
    - ``None``：无 person/project/title 槽，不缩文档；
    - ``[]``：有专名但标题/文档 meta 均未命中（fail-closed）；
    - 非空：标题包含专名，或 documents.metadata_json 的 person/project 命中。

    设计思路：Milvus 切块 ``project_name`` 常为空，若仍 AND ``project_name==``
    会把 ANN 清零；先把专名落到 ``document_id in [...]``，expr 不再依赖空标量。

    @author 赵振明
    @date 2026-11-24 17:24:24
    """
    persons = _expand_slot(slots.persons)
    projects = _expand_slot(slots.projects)
    titles = _expand_slot(slots.titles)
    if not persons and not projects and not titles:
        return None
    if not kb_ids:
        return []
    try:
        rows = (
            await db.execute(
                select(Document.id, Document.title, Document.metadata_json).where(
                    Document.kb_id.in_(kb_ids),
                    Document.status == "published",
                    Document.deleted_at.is_(None),
                )
            )
        ).all()
    except Exception as exc:  # noqa: BLE001 — 单测 MagicMock / 临时故障时跳过本路径
        logger.debug("focus document match skipped: %s", exc)
        return None

    matched: list[str] = []
    try:
        for doc_id, title, meta_raw in rows:
            title_s = str(title or "")
            meta = parse_json_obj(meta_raw if isinstance(meta_raw, str) else None)
            if not isinstance(meta, dict):
                # metadata_json 偶发非 str
                if isinstance(meta_raw, dict):
                    meta = meta_raw
                else:
                    meta = {}
            person_meta = str(meta.get("person_name") or "")
            project_meta = str(meta.get("project_name") or "")
            hit = False
            if projects and (
                any(t in title_s for t in projects)
                or any(t and t == project_meta for t in projects)
            ):
                hit = True
            if persons and (
                any(t in title_s for t in persons)
                or any(t and t == person_meta for t in persons)
            ):
                hit = True
            if titles and any(t in title_s for t in titles):
                hit = True
            if hit:
                matched.append(str(doc_id))
    except (TypeError, ValueError) as exc:
        logger.debug("focus document match iterate skipped: %s", exc)
        return None
    return list(dict.fromkeys(matched))


async def resolve_retrieval_scope(
    db: AsyncSession,
    *,
    query: str,
    agent_id: str | None,
    kb_ids: list[str] | None,
    user_id: str | None,
    department_ids: list[str] | None,
    role_ids: list[str] | None,
    is_platform_admin: bool,
    filters: dict[str, Any] | None,
    filter_fallback: str = "soft",
) -> RetrievalScope:
    """解析检索范围。

    核心逻辑：
    1. KB 范围：Agent 绑定（空绑定→空范围）∩ 显式 kb_ids ∩ 用户有权 KB；
    2. 文档范围：按 filters 求 document_ids；
    3. 空集降级：soft 依次 drop_meta → drop_category，仍空则保持 []；
       仅 legacy_full 才允许退为 document_ids=None 并打审计标；
    4. 文档可见性：null/department/public 三态；结果为 [] 时保持 []，不放宽为 None。

    Args:
        query: 用户查询，用于抽取分槽焦点词并组装 milvus_expr。
        filter_fallback: ``soft`` 或 ``legacy_full``；其它值抛 ValueError。

    Raises:
        ValueError: filter_fallback 非法。
    """
    if filter_fallback not in _ALLOWED_FALLBACK:
        raise ValueError(f"unsupported filter_fallback: {filter_fallback!r}")

    ids, reasons, unauthorized = await _resolve_kb_ids(
        db,
        agent_id=agent_id,
        kb_ids=kb_ids,
        user_id=user_id,
        department_ids=department_ids,
        role_ids=role_ids,
        is_platform_admin=is_platform_admin,
    )
    if not ids and not unauthorized:
        return _empty_scope(*(reasons or ("kb_scope_empty",)))

    # 过滤在「授权 KB ∪ 候选无权 KB」上执行，使 public 文档能参与 filters
    scan_ids = list(dict.fromkeys([*ids, *unauthorized]))
    codes = list(reasons)
    degrade = DEGRADE_NONE
    added_kb_ids: list[str] = []

    async def _visible(docs: list[str] | None) -> list[str] | None:
        """对一次 filter 结果立即套用可见性，并记录因 public 扩大并入的 kb。"""
        sink: list[str] = []
        out = await apply_document_visibility(
            db,
            kb_ids=ids,
            base_document_ids=docs,
            user_id=user_id,
            department_ids=list(department_ids or []),
            is_platform_admin=is_platform_admin,
            extra_kb_ids=unauthorized,
            added_kb_ids=sink,
        )
        added_kb_ids[:] = sink
        return out

    async def _filter_visible(f: dict[str, Any] | None) -> list[str] | None:
        """filter 后立即做可见性；不可见文档不得满足过滤、阻断 soft 降级。

        返回 None 表示 filter 无约束（可见性留待最终统一处理）；
        可见集合为空则返回 []，调用方按「未命中」继续降级。
        """
        docs = await filter_documents_by_plan(db, kb_ids=scan_ids, filters=f)
        if docs:
            return await _visible(docs)
        return docs

    doc_ids = await _filter_visible(filters)

    # doc_ids 为 None 表示 filters 无需缩文档；仅 [] 才进入降级
    if doc_ids is not None and len(doc_ids) == 0 and filters:
        if filter_fallback == "legacy_full":
            doc_ids = None
            degrade = DEGRADE_LEGACY_FULL
            codes.append("legacy_full")
        else:
            # soft 第一级：去 metadata，保留分类
            doc_ids = await _filter_visible(apply_soft_fallback(filters))
            degrade = DEGRADE_DROP_META
            codes.append("filters_empty_drop_meta")
            # 仅 metadata 过滤时 drop_meta 后会得到 None（无约束），同样视为未命中
            if not doc_ids:
                # soft 第二级：分类也放宽；终点，不再升级到全文
                doc_ids = await _filter_visible(apply_category_fallback(filters))
                degrade = DEGRADE_DROP_CATEGORY
                codes.append("filters_empty_drop_category")
                if not doc_ids:
                    # 裁定：soft 终点绝不为 None（None 会等价 kb 全库检索）；
                    # 分类清空后 filter 返回 None 也强制收敛为 []，宁空勿全文
                    doc_ids = []
                    codes.append("filters_empty_after_soft")

    # doc_ids 仍为 None（无 filters / legacy_full）：对「整库」套用可见性（§8.2）
    if doc_ids is None:
        doc_ids = await _visible(None)
        if doc_ids is not None or added_kb_ids:
            codes.append("visibility_applied")
    elif added_kb_ids:
        codes.append("visibility_applied")

    final_ids = list(dict.fromkeys([*ids, *added_kb_ids]))
    if not final_ids:
        # 无授权 KB 且无 public 文档可扩大 → 空范围
        return _empty_scope(*[c for c in codes if c != "kb_scope_empty"], "kb_scope_empty")
    # 授权为空但 public 扩大成功：kb_scope_empty 不再成立
    codes = [c for c in codes if c != "kb_scope_empty"]

    slots = extract_focus_slots(query)
    # 专名先落到 document_ids，避免空 Milvus 标量 AND 清零
    focus_docs = await _match_focus_document_ids(
        db, kb_ids=final_ids, slots=slots
    )
    expr_slots = slots
    if focus_docs is not None:
        codes.append("focus_document_ids")
        focus_set = set(focus_docs)
        if not focus_docs:
            doc_ids = []
            codes.append("focus_document_ids_empty")
        elif doc_ids is None:
            doc_ids = list(focus_docs)
        else:
            doc_ids = [d for d in doc_ids if d in focus_set]
            if not doc_ids:
                codes.append("focus_document_ids_empty")
        # document_ids 已表达专名范围；expr 不再写 person/project/title 等值
        expr_slots = FocusSlots(
            persons=(),
            projects=(),
            titles=(),
            keywords=slots.keywords,
        )
    expr, expr_reasons = _build_scope_expr(final_ids, doc_ids, expr_slots)
    codes.extend(expr_reasons)

    return RetrievalScope(
        kb_ids=final_ids,
        document_ids=doc_ids,
        milvus_expr=expr,
        focus_persons=slots.persons,
        focus_projects=slots.projects,
        focus_titles=slots.titles,
        focus_keywords=slots.keywords,
        degrade_level=degrade,
        reason_codes=tuple(codes),
    )
