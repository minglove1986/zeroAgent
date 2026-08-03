# L2 否定门禁与关键词 DB+Redis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 否定纠正句不再误进 `doc_analyze`/`kb_lookup`；L2 关键词 MySQL 持久化、启动加载 Redis、管理 CRUD 双写同步。

**Architecture:** `DEFAULT_SEED` 兜底；`intent_l2_keywords` 为真相源；Redis `za:intent:l2_catalog:v1` 热读；`match_l2_rules` 只消费 `get_catalog()`；管理 API 写库后全量刷缓存；lifespan 启动 reload。

**Tech Stack:** FastAPI、SQLAlchemy Async、Alembic、Redis、pytest。

**Spec:** `docs/superpowers/specs/2026-07-29-l2-negation-catalog-design.md`

## Global Constraints

- 单租户，禁止 `tenant_id`
- P0 `match_mode` 仅 `contains` / `equals` / `prefix`，禁止管理员自定义 regex
- 匹配热路径禁止每轮 `SELECT`（仅 Redis miss 回源一次）
- CRUD：先 MySQL 成功，再刷新 Redis；刷失败需可观测 + `/reload-cache`
- 管理 API 仅 `platform_admin` / `super_admin`
- `@author 赵振明`；注释时间东八区实时
- **仅用户明确要求时 git commit**（下列 Commit 步骤默认跳过）

## File Structure

| 文件 | 职责 |
|---|---|
| `src/app/modules/intent/l2_seed.py` | `DEFAULT_SEED` 常量（按 category 短语列表） |
| `src/app/modules/intent/l2_catalog_cache.py` | Redis get/set/version；进程降级状态 |
| `src/app/modules/intent/l2_catalog_store.py` | DB 查询、seed 空表、reload→Redis、CRUD 写后刷缓存 |
| `src/app/models/intent_l2.py` | ORM `IntentL2Keyword` |
| `migrations/versions/0024_intent_l2_keywords.py` | 建表 + seed |
| `src/app/modules/intent/rules.py` | 消费 `get_catalog()`；匹配顺序含纠正门禁 |
| `src/app/api/v1/intent_l2_keywords.py` | 管理 CRUD + reload-cache |
| `src/app/api/v1/router.py` | 挂载路由 |
| `src/app/main.py` | lifespan 启动 `reload_l2_catalog` |
| `src/app/modules/intent/classifier.py` | L3 prompt 纠正条款 |
| `tests/test_l2_catalog_cache.py` | 缓存/种子 |
| `tests/test_l2_negation_rules.py` | 否定门禁 |
| `tests/test_intent_l2_keywords_api.py` | API 权限与同步 |
| `docs/01-产品需求/数据库表结构.md` / `API接口规范.md` | 对齐文档 |
| `docs/superpowers/CHECKPOINT.md` | 断点 |

---

### Task 1：DEFAULT_SEED + Redis 缓存读路径

**Files:**
- Create: `src/app/modules/intent/l2_seed.py`
- Create: `src/app/modules/intent/l2_catalog_cache.py`
- Create: `tests/test_l2_catalog_cache.py`

**Interfaces:**
- Produces:
  - `L2Category = Literal["explicit_kb","leave","meta_reply","doc_dump","doc_summarize","doc_critique","person_search_verb"]`
  - `DEFAULT_SEED: dict[str, list[dict]]` 每项含 `phrase`, `match_mode`（默认 `contains`）, `priority`
  - `REDIS_KEY = "za:intent:l2_catalog:v1"`, `REDIS_VER_KEY = "za:intent:l2_catalog:ver"`
  - `def set_catalog_in_redis(catalog: dict) -> bool`
  - `def get_catalog_from_redis() -> dict | None`
  - `def get_catalog() -> dict`：Redis → 否则内存 `_fallback`（默认 DEFAULT_SEED）
  - `def set_fallback_catalog(catalog: dict) -> None`（供 store/测试）
  - `def reset_l2_catalog_for_tests() -> None`

- [ ] **Step 1: 写失败单测**

```python
"""L2 catalog 缓存与种子。

@author 赵振明
@date <东八区实时>
"""

from __future__ import annotations

from app.modules.intent.l2_catalog_cache import get_catalog, reset_l2_catalog_for_tests, set_fallback_catalog
from app.modules.intent.l2_seed import DEFAULT_SEED


def test_default_seed_has_summarize_and_negation() -> None:
    phrases_sum = {x["phrase"] for x in DEFAULT_SEED["doc_summarize"]}
    phrases_meta = {x["phrase"] for x in DEFAULT_SEED["meta_reply"]}
    assert "总结" in phrases_sum
    assert any("没让你" in p or p == "我没让你" for p in phrases_meta)


def test_get_catalog_falls_back_to_seed() -> None:
    reset_l2_catalog_for_tests()
    cat = get_catalog()
    assert "doc_summarize" in cat
    assert any(x["phrase"] == "总结" for x in cat["doc_summarize"])


def test_set_fallback_overrides_get_catalog() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog({"meta_reply": [{"phrase": "别总结", "match_mode": "contains", "priority": 1}]})
    cat = get_catalog()
    assert cat["meta_reply"][0]["phrase"] == "别总结"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\HermesWork\zeroAgent && & "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_l2_catalog_cache.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 seed + cache**

`l2_seed.py`：把现行 `rules.py` 口令迁入 `DEFAULT_SEED`，并新增纠正短语：`我没让你`、`我没有让你`、`不是让你`、`我没叫你`、`不要`、`别`（`meta_reply`；`不要`/`别` 需注意过宽——规格允许，但单测锁定「不要总结…」走纠正；若「不要」过宽导致误伤，改为 `不要总结`/`别总结` 等更长短语——**实现时优先较长纠正短语**：`我没让你`、`我没有让你`、`不是让你`、`我没叫你`、`不要总结`、`别总结`、`不要概括`、`别概括`）。

`l2_catalog_cache.py`：仿 `thresholds._redis_client`；`get_catalog` 先 Redis JSON，失败用 `_fallback`。

- [ ] **Step 4: Run test to verify it passes**

Run: 同 Step 2，Expected: PASS

- [ ] **Step 5: Commit**（默认跳过）

---

### Task 2：ORM + Migration + Seed

**Files:**
- Create: `src/app/models/intent_l2.py`
- Modify: `src/app/models/__init__.py`（导出）
- Create: `migrations/versions/0024_intent_l2_keywords.py`
- Modify: `docs/01-产品需求/数据库表结构.md`（追加表 DDL）

**Interfaces:**
- Produces: `class IntentL2Keyword` 字段对齐规格 §4.1
- Migration `revision=0024_intent_l2_keywords`, `down_revision=0023_seed_skill_doc_understand`
- upgrade：建表 + INSERT DEFAULT_SEED 各短语（id=`l2k_`+uuid hex 截断）

- [ ] **Step 1: 写失败单测（模型可导入 + 表名）**

```python
def test_intent_l2_keyword_model_tablename() -> None:
    from app.models.intent_l2 import IntentL2Keyword
    assert IntentL2Keyword.__tablename__ == "intent_l2_keywords"
```

放入 `tests/test_l2_catalog_cache.py` 或新建 `tests/test_intent_l2_model.py`。

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: 实现 ORM + migration + 文档表段落**
- [ ] **Step 4: Run → PASS**；本地可 `alembic upgrade head`（若环境有库）
- [ ] **Step 5: Commit**（跳过）

---

### Task 3：Store：DB→Redis reload + 空表 seed

**Files:**
- Create: `src/app/modules/intent/l2_catalog_store.py`
- Modify: `tests/test_l2_catalog_cache.py`（或 `tests/test_l2_catalog_store.py`）

**Interfaces:**
- Produces:
  - `async def load_catalog_from_db(db: AsyncSession) -> dict`
  - `async def ensure_seed_if_empty(db: AsyncSession) -> int`（插入条数）
  - `async def reload_l2_catalog(db: AsyncSession) -> dict`：ensure_seed → load → set Redis + set_fallback → return
  - `def catalog_phrases(category: str) -> list[str]` 便捷（从 get_catalog）

单测：用 AsyncMock/内存假 DB 或 monkeypatch `load_catalog_from_db` 返回固定 dict，断言 `reload_l2_catalog` 调用 `set_catalog_in_redis` 与 `set_fallback_catalog`。

- [ ] **Step 1–4: TDD 如上**
- [ ] **Step 5: Commit**（跳过）

---

### Task 4：rules 消费 catalog + 否定门禁

**Files:**
- Modify: `src/app/modules/intent/rules.py`
- Create: `tests/test_l2_negation_rules.py`
- Modify: `tests/test_chat_routing_hotfix.py` / `tests/test_doc_analyze_graph.py`（若破坏则修）

**Interfaces:**
- `match_l2_rules` 顺序：explicit_kb → leave → meta_reply → doc_* → lexicon → person_search
- 短语匹配：按 `match_mode`（contains/equals/prefix）
- 测试前 `reset_l2_catalog_for_tests()` 并 `set_fallback_catalog(DEFAULT_SEED)`

- [ ] **Step 1: 写失败单测**

```python
"""L2 否定门禁。

@author 赵振明
@date <东八区实时>
"""

from __future__ import annotations

from app.modules.intent.l2_catalog_cache import reset_l2_catalog_for_tests, set_fallback_catalog
from app.modules.intent.l2_seed import DEFAULT_SEED
from app.modules.intent.rules import match_l2_rules


def setup_function() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(DEFAULT_SEED)


def test_user_correction_not_doc_summarize() -> None:
    d = match_l2_rules("我没让你总结赵世龙的简历")
    assert d is not None
    assert d.intent == "chitchat"
    assert d.funnel_layer == "L2"


def test_do_not_summarize_is_chitchat() -> None:
    d = match_l2_rules("不要总结赵世龙的简历")
    assert d is not None
    assert d.intent == "chitchat"


def test_positive_summarize_still_doc_analyze() -> None:
    d = match_l2_rules("总结赵世龙的简历")
    assert d is not None
    assert d.intent == "doc_analyze"
    assert (d.slots or {}).get("task") == "summarize"


def test_contract_summarize_still_works() -> None:
    d = match_l2_rules("帮我总结一下这份合同")
    assert d is not None
    assert d.intent == "doc_analyze"
```

- [ ] **Step 2: Run → 当前「我没让你…」会 FAIL（得到 doc_analyze）** — 正确红灯
- [ ] **Step 3: 改 rules 消费 get_catalog；删除硬编码词表**
- [ ] **Step 4: 全绿 + 跑 `tests/test_doc_analyze_graph.py::` 相关 + `test_chat_routing_hotfix.py`**
- [ ] **Step 5: Commit**（跳过）

---

### Task 5：lifespan 启动加载

**Files:**
- Modify: `src/app/main.py`
- Modify: `src/app/shared/db.py`（确认可获取 session factory）

**Interfaces:**
- `create_app` 增加 `@asynccontextmanager async def lifespan(app)`：创建 AsyncSession → `await reload_l2_catalog(db)`；异常只记日志不阻断启动

参考现有 `get_db` / `async_session_factory` 写法。

- [ ] **Step 1: 单测**可用 TestClient + monkeypatch `reload_l2_catalog` 断言被调用；或轻量测 lifespan 钩子存在
- [ ] **Step 2–4: TDD**
- [ ] **Step 5: Commit**（跳过）

---

### Task 6：管理 API CRUD + 权限 + 刷缓存

**Files:**
- Create: `src/app/api/v1/intent_l2_keywords.py`
- Create: `src/app/api/schemas/intent_l2.py`（可选）
- Modify: `src/app/api/v1/router.py`
- Create: `tests/test_intent_l2_keywords_api.py`
- Modify: `docs/01-产品需求/API接口规范.md`

**Interfaces:**
- `GET/POST /api/v1/intent/l2-keywords`
- `PATCH/DELETE /api/v1/intent/l2-keywords/{id}`
- `POST /api/v1/intent/l2-keywords/reload-cache`
- 写操作后调用 `reload_l2_catalog`
- 非平台管理员 → 40301

单测模式：仿现有 API 测试（依赖覆盖 `get_db` / `get_actor`）；断言 create 后 `get_catalog_from_redis` 或 fallback 含新短语。

- [ ] **Step 1–4: TDD**
- [ ] **Step 5: Commit**（跳过）

---

### Task 7：L3 prompt 防御 + 回归 + CHECKPOINT

**Files:**
- Modify: `src/app/modules/intent/classifier.py`（`_L3_SYSTEM` 增加纠正/否定 → chitchat）
- Modify: `docs/superpowers/CHECKPOINT.md`
- Modify: `docs/superpowers/specs/2026-07-29-l2-negation-catalog-design.md` 状态保持「已确认」

- [ ] **Step 1: 可选单测**断言 system prompt 含「没让」或「纠正」关键字（字符串包含即可）
- [ ] **Step 2–4: 实现 + 跑相关 intent/routing 回归**
- [ ] **Step 5: 更新 CHECKPOINT；Commit 跳过**

---

## Spec Coverage Checklist

| 规格要求 | Task |
|---|---|
| 否定 → chitchat | Task 4 |
| 正向总结仍 doc_analyze | Task 4 |
| MySQL 表 + seed | Task 2 |
| 启动加载 Redis | Task 5 + 3 |
| CRUD 双写 | Task 6 |
| reload-cache | Task 6 |
| 降级 DEFAULT_SEED | Task 1 |
| 禁自定义 regex | Task 6 校验 |
| 澄清卡不改（复用） | 无新 task（回归） |
| L3 防御 | Task 7 |
| API/库表文档 | Task 2、6 |
| CHECKPOINT | Task 7 |

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-29-l2-negation-catalog.md`.

**Two execution options:**

1. **Subagent-Driven（推荐）** — 每 Task 派生子代理，任务间审查  
2. **Inline Execution** — 本会话按 executing-plans 连续执行  

Which approach?
