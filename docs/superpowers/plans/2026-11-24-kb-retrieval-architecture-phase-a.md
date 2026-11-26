# 知识库检索架构 Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地检索契约闭环：ScopeResolver（绑定/权限/可见性/bounded 降级）+ Metadata 增强下推 + Gate 前置（G1 空证据 + D14 简）+ 删除 stub，使无 citation 时不泄模型正文。

**Architecture:** `run_kb_lookup` 变薄编排；新建 `scope.py` 产出 `RetrievalScope`；`search_kb_chunks` 只消费 Scope；`quality_gate_phase_a`（可先放 `quality_gate.py` 内最小函数）在合成/respond 前短路；Agent 图内拒展 preset，禁止空检索无限 replan。

**Tech Stack:** FastAPI、SQLAlchemy async、Milvus 标量 expr、既有 BM25/RRF、pytest。

**Spec:** `docs/superpowers/specs/2026-11-24-kb-retrieval-architecture-design.md`（含 §14 二次自检）

## Global Constraints

- 单租户；无 `tenant_id`
- 默认 `filter_fallback="soft"` 最高只到 `drop_category`；全文仅 `legacy_full`
- 有 `agent_id` 且未绑 KB → 空范围（偏离知识库 PRD §8.3，以本 spec 为准）
- `visibility_override` 按知识库 PRD §8.2 三态（含 public 扩大）
- `category_codes`/`keywords` 为 CSV：分类走 SQL→`document_id in`；keywords 只回表加权
- Gate 在首个模型正文 `content_delta` 之前；thought 可保留
- 注释 `@author 赵振明`；时间东八区实时
- 单测 Mock LiteLLM/Milvus/OSS；后端端口固定 8000
- **默认不自动 git commit**；仅用户明确要求时提交

## File Map

| 文件 | 职责 |
|---|---|
| `src/app/modules/knowledge/scope.py` | `RetrievalScope`、`resolve_retrieval_scope`、`apply_document_visibility` |
| `src/app/modules/knowledge/chunk_metadata.py` | `build_milvus_filter_expr` 支持分槽 + `document_ids`；不对 CSV 假 `==` |
| `src/app/modules/knowledge/search.py` | 消费 Scope；删专名空则仅 kb 回退；keywords 加权 |
| `src/app/modules/knowledge/lookup.py` | 编排 Scope→search→citations；bounded soft |
| `src/app/modules/knowledge/quality_gate.py` | Phase A：`evaluate_retrieval_gate`（空 hits→G1；used_rag 无 cite→D14） |
| `src/app/modules/knowledge/entity_filter.py` | `extract_focus_slots`（分槽）；保留/收敛 `prefer_hits` |
| `src/app/modules/conversation/handlers/kb_lookup.py` | 去 stub；合成前 Gate |
| `src/app/modules/conversation/runtime.py` | 删除或隔离 `rag_stub_has_citation`；plan 路径兜底 |
| `src/app/modules/agent/graph/plan_execute.py` | rag 空则拒展 preset，不进流式 respond |
| `src/app/modules/agent/graph/plan_replan.py` | 空 rag 不无限 replan |
| `tests/modules/knowledge/test_retrieval_scope.py` | Scope/可见性/绑定 |
| `tests/modules/knowledge/test_search_vector_first.py` | 扩展 Scope 消费与 expr |
| `tests/modules/conversation/` 或现有 plan 测 | Gate 流式时序 |
| `docs/superpowers/CHECKPOINT.md` | 断点 |

---

### Task 1: RetrievalScope 类型与空绑定 / bounded soft

**Files:**
- Create: `src/app/modules/knowledge/scope.py`
- Create: `tests/modules/knowledge/test_retrieval_scope.py`（若目录惯例为 `src/app/modules/knowledge/test_*.py` 则跟仓库现有：放 `src/app/modules/knowledge/test_retrieval_scope.py`）

**Interfaces:**
- Produces:
```python
@dataclass(frozen=True)
class RetrievalScope:
    kb_ids: list[str]
    document_ids: list[str] | None  # None=不缩；[]=空
    milvus_expr: str
    focus_persons: tuple[str, ...]
    focus_projects: tuple[str, ...]
    focus_titles: tuple[str, ...]
    focus_keywords: tuple[str, ...]
    degrade_level: str  # none|drop_meta|drop_category|legacy_full
    reason_codes: tuple[str, ...]

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
    filters: dict | None,
    filter_fallback: str = "soft",  # soft|legacy_full
) -> RetrievalScope: ...
```

- [x] **Step 1: 写失败单测**

```python
@pytest.mark.asyncio
async def test_agent_unbound_kb_yields_empty_scope(db_session, monkeypatch):
    # agent_id 有值但 AgentKb 无行 → kb_ids == []
    scope = await resolve_retrieval_scope(
        db_session,
        query="张三是谁",
        agent_id="agent_x",
        kb_ids=None,
        user_id="u1",
        department_ids=[],
        role_ids=["employee"],
        is_platform_admin=False,
        filters={"category_codes": ["hr.resume"], "metadata": [{"key": "person_name", "op": "eq", "value": "张三"}]},
        filter_fallback="soft",
    )
    assert scope.kb_ids == []
    assert scope.document_ids == [] or scope.kb_ids == []


@pytest.mark.asyncio
async def test_soft_fallback_does_not_clear_document_scope_to_none(db_session):
    # 构造 filters 导致空文档集；soft 最多 drop_category 后仍无文档 → document_ids == [] 而非 None
    ...
    assert scope.document_ids == []
    assert scope.degrade_level in ("drop_meta", "drop_category")
    assert "legacy_full" not in scope.degrade_level
```

- [x] **Step 2: 跑测确认失败**  
  `pytest src/app/modules/knowledge/test_retrieval_scope.py -q`  
  Expected: FAIL（模块不存在）

- [x] **Step 3: 实现 `scope.py` 最小逻辑**  
  - 绑定：复用/迁移 `resolve_kb_ids_for_agent`，改为空绑定→`[]`  
  - 无 agent：`list_accessible_kb_ids`（非 admin）；admin 可用全库未删  
  - soft：`apply_soft_fallback` → `apply_category_fallback`；仍空则 `document_ids=[]`，**不要** `None`  
  - `legacy_full`：才允许 `document_ids=None`  

- [x] **Step 4: 跑测通过**

---

### Task 2: `apply_document_visibility`（§8.2 三态）

**Files:**
- Modify: `src/app/modules/knowledge/scope.py`
- Modify: `src/app/modules/knowledge/test_retrieval_scope.py`

**Interfaces:**
```python
async def apply_document_visibility(
    db: AsyncSession,
    *,
    kb_ids: list[str],
    base_document_ids: list[str] | None,
    user_id: str,
    department_ids: list[str],
    is_platform_admin: bool,
) -> list[str] | None:
    """null 跟随；department 收窄；public 在已授权 KB 内扩大可见文档。"""
```

- [x] **Step 1: 单测**  
  - KB department 授权仅部门 A；文档 `visibility_override=public` → 部门 B 用户若对 KB 无并集权仍不可见；若用户对 KB 有权（或 public 扩大语义按 PRD：对全员可见需结合 KB 授权——严格按 PRD：「即使 KB 是 department，本文档对全员可见」）→ **按 PRD 字面：public 文档对全员可见**（实现时以 §8.2 表格为准，单测锁定）。  
  - `department` override：KB public 用户无部门匹配 → 剔除。  

- [x] **Step 2: 实现并接入 `resolve_retrieval_scope`**  
- [x] **Step 3: 测绿**

---

### Task 3: 分槽 focus + milvus_expr（含 document_ids，禁 CSV 假等值）

**Files:**
- Modify: `src/app/modules/knowledge/entity_filter.py`（新增 `extract_focus_slots`）
- Modify: `src/app/modules/knowledge/chunk_metadata.py`（`build_milvus_filter_expr`）
- Modify: `src/app/modules/knowledge/test_chunk_metadata.py` 或新建测

**Interfaces:**
```python
@dataclass(frozen=True)
class FocusSlots:
    persons: tuple[str, ...]
    projects: tuple[str, ...]
    titles: tuple[str, ...]
    keywords: tuple[str, ...]

def extract_focus_slots(query: str) -> FocusSlots: ...

def build_milvus_filter_expr(
    *,
    kb_ids: list[str],
    person_names: list[str] | None = None,
    project_names: list[str] | None = None,
    title_terms: list[str] | None = None,
    doc_types: list[str] | None = None,
    document_ids: list[str] | None = None,
) -> str: ...
```

- [x] **Step 1: 单测**  
  - 人名槽不写入 `project_name ==`  
  - `document_ids=["d1","d2"]` → expr 含 `document_id in [...]`  
  - 不出现 `category_codes ==`  

- [x] **Step 2: 实现**  
- [x] **Step 3: Scope 组装时填 milvus_expr**（分类已化为 document_ids）  
- [x] **Step 4: 测绿**

---

### Task 4: `search_kb_chunks` 消费 Scope

**Files:**
- Modify: `src/app/modules/knowledge/search.py`
- Modify: `src/app/modules/knowledge/test_search_vector_first.py`
- Modify: `src/app/modules/knowledge/lookup.py`（改为先 resolve 再 search）

**Interfaces:**
```python
async def search_kb_chunks(
    *,
    db: AsyncSession,
    scope: RetrievalScope,
    query: str,
    top_k: int = 5,
) -> list[dict]: ...
```
兼容：可保留旧签名包装为内部构造临时 Scope，但 **lookup 主路径必须传 Scope**。

- [x] **Step 1: 单测**  
  - Mock milvus：断言传入 expr 含 scope 内容  
  - 专名 0 命中：**不再**自动二次「仅 kb_id」搜索（可用 mock 调用次数断言）  
  - keywords 加权：含词 hit 排前；全无 keywords 不整表清空  

- [x] **Step 2: 实现改造 + 删除 295–301 回退**  
- [x] **Step 3: lookup 接 Scope；`filter_fallback` 传入**  
- [ ] **Step 4: 相关测全绿**（未勾：见 task-7 报告，存量/环境失败）
  `pytest src/app/modules/knowledge/test_search_vector_first.py src/app/modules/knowledge/test_retrieval_scope.py -q`

---

### Task 5: Phase A Gate + 系统 kb_lookup 去 stub

**Files:**
- Create: `src/app/modules/knowledge/quality_gate.py`
- Modify: `src/app/modules/conversation/handlers/kb_lookup.py`
- Modify: `src/app/modules/conversation/runtime.py`（stub 仅测用或删除）
- Create/Modify: 对应单测

**Interfaces:**
```python
@dataclass(frozen=True)
class GateResult:
    ok: bool
    code: str  # "" | rejected_no_recall | rejected_no_citation
    message: str

def evaluate_retrieval_gate(*, hits: list, citations: list, used_rag: bool) -> GateResult:
    if not used_rag:
        return GateResult(True, "", "")
    if not hits and not citations:
        return GateResult(False, "rejected_no_recall", "...")
    if not citations:
        return GateResult(False, "rejected_no_citation", "...")
    return GateResult(True, "", "")
```

- [x] **Step 1: 单测 Gate + `execute_system_kb_lookup` 无 stub**  
  - 用户内容含「无引用」仍执行检索（不再短路）  
  - hits 空 → `rejected_no_recall`，不调用合成 LLM（mock 断言）  

- [x] **Step 2: 实现并接线**  
- [ ] **Step 3: 测绿**（未勾：见 task-7 报告，存量/环境失败）

---

### Task 6: Agent 流式 Gate 前置 + 禁无限 replan

**Files:**
- Modify: `src/app/modules/agent/graph/plan_execute.py`
- Modify: `src/app/modules/agent/graph/plan_replan.py`
- Modify: `src/app/modules/conversation/runtime.py`（兜底：若 content 已流且 gate 失败，不得再当作成功；主路径应不再触发）
- Test: 现有 plan_execute / runtime 测或新建 `test_rag_gate_stream.py`

- [x] **Step 1: 写失败单测（契约）**  
  - plan 含 `rag_search` 且 citations 空 → 收集到的 SSE **不得**出现模型正文 delta（拒展文案除外，可用固定前缀断言）  
  - `should_replan_after_step`：rag 已失败/空 cite 后再次计划不得仍首步 `rag_search`（或 replan_count 触顶）  

- [x] **Step 2: `_execute_rag_search` / `_node_execute`：空结果设 `final_answer` 拒展 preset，跳过流式 respond**  
- [x] **Step 3: 调整 `plan_replan` 黑名单**  
- [ ] **Step 4: 测绿**（未勾：见 task-7 报告，存量/环境失败）

---

### Task 7: 观测字段 + 断点 + spec 状态

**Files:**
- Modify: `lookup` 返回增加 `degrade_level` / `reason_codes` / `used_milvus`（若已有则对齐）
- Modify: `turn_trace` 调用点增加 `scope_resolved` / `gate_rejected`
- Modify: `docs/superpowers/specs/2026-11-24-kb-retrieval-architecture-design.md` 文首状态 → `Phase A 实现中` 或完成后 `Phase A 已实现`
- Modify: `docs/superpowers/CHECKPOINT.md`

- [x] **Step 1: 确认返回字段与 trace 键名与 spec §7.3 一致**  
- [x] **Step 2: 跑知识检索相关测合集**  
  `pytest src/app/modules/knowledge/ -q --tb=line`  
- [x] **Step 3: 更新 CHECKPOINT**  

---

## Spec 覆盖对照（自检）

| Spec 项 | Task |
|---|---|
| 空绑定空范围 | T1 |
| soft 不上全文 / legacy_full | T1 |
| visibility §8.2 | T2 |
| 分槽 + document_id 下推 + 禁 CSV 假等值 | T3 |
| search 消费 Scope、删仅 kb 回退、keywords 加权 | T4 |
| 去 stub、G1/D14、合成前 Gate | T5 |
| 流式前置、禁无限 replan | T6 |
| Evidence/trace | T7 |
| Phase B/C | **不在本计划** |

## 占位符扫描

无 TBD；commit 步骤改为「用户要求时再提交」。
