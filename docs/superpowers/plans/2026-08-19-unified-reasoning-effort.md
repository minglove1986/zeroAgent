# 统一思考参数 reasoning_effort Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 业务只发 LiteLLM 统一 `reasoning_effort`；目录同步 `supports_reasoning`；员工端仅对支持思考的模型显示「深度思考」。

**Architecture:** `litellm_sync` 从 `/model/info` 提取能力位写入 `llm_models` → Redis；`get_chat_model` 发 `reasoning_effort=none|medium` 并对照目录静默降级；员工端 `/llm-models/available` 带回布尔字段控制开关显隐。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、pytest、Next.js（web/admin-web）。

**Spec:** `docs/superpowers/specs/2026-08-19-unified-reasoning-effort-design.md`

## Global Constraints

- 禁止业务硬编码厂商 `thinking.type`
- 未知/缺失 `supports_reasoning` → 0（不支持）
- 开思考固定 `medium`；关=`none`
- 注释：`@author 赵振明`；东八区实时时间
- **Git commit：** 未明确要求时跳过
- API `:8000` / 前端 `:3000` 不改端口
- 单租户；不扩大范围

---

## File map

| 文件 | 职责 |
|---|---|
| `src/app/modules/llm/litellm_sync.py` | `_extract_supports_reasoning`；同步写列；catalog 带字段 |
| `src/app/modules/llm/catalog_models.py` | ORM `supports_reasoning` |
| `migrations/versions/0042_llm_supports_reasoning.py` | 加列 |
| `src/app/modules/llm/lc_chat.py` | `reasoning_effort` + 目录防御 |
| `src/app/api/v1/llm_models_admin.py` | 列表返回字段 |
| `src/app/api/v1/llm_models_public.py` | available 返回字段 |
| `tests/test_supports_reasoning.py` | 提取 + get_chat_model + available |
| `tests/test_deep_think_wiring.py` | 改断言为 reasoning_effort |
| `tests/test_llm_lc_migration.py` | 改断言为 reasoning_effort |
| `web/src/app/chat/page.tsx` | 开关按能力位显隐 |
| `admin-web/.../llm-models/page.tsx` | 只读「支持思考」列 |
| `docs/01-产品需求/API接口规范.md` | 字段说明 |
| `docs/01-产品需求/数据库表结构.md` | 列说明 |
| `docs/superpowers/CHECKPOINT.md` | 断点 |

---

### Task 1: 提取 `supports_reasoning`（TDD）

**Files:**
- Modify: `src/app/modules/llm/litellm_sync.py`
- Test: `tests/test_supports_reasoning.py`

**Interfaces:**
- Produces: `def _extract_supports_reasoning(info: dict[str, Any]) -> bool`

- [ ] **Step 1: 写失败测**

```python
"""supports_reasoning 提取与 reasoning_effort 接线。

@author 赵振明
@date <东八区实时>
"""
from app.modules.llm.litellm_sync import _extract_supports_reasoning

def test_extract_supports_reasoning_explicit_true() -> None:
    assert _extract_supports_reasoning({"model_info": {"supports_reasoning": True}}) is True

def test_extract_supports_reasoning_missing_or_false() -> None:
    assert _extract_supports_reasoning({"model_name": "agnes-2.5-flash"}) is False
    assert _extract_supports_reasoning({"model_info": {"supports_reasoning": False}}) is False

def test_extract_supports_reasoning_from_supported_openai_params() -> None:
    assert _extract_supports_reasoning(
        {"supported_openai_params": ["temperature", "reasoning_effort"]}
    ) is True
```

- [ ] **Step 2: 跑测确认 RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_supports_reasoning.py::test_extract_supports_reasoning_explicit_true -v`  
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现提取函数**

在 `litellm_sync.py` 增加 `_extract_supports_reasoning`：扫描顶层与 `model_info` 嵌套；`supports_reasoning is True` 或 `supported_openai_params` 含 `reasoning_effort`/`reasoning`（大小写不敏感）→ True；否则 False。

- [ ] **Step 4: 跑测 GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_supports_reasoning.py -v -k extract`  
Expected: PASS

---

### Task 2: 迁移 + ORM + 同步写入 + 缓存

**Files:**
- Create: `migrations/versions/0042_llm_supports_reasoning.py`
- Modify: `src/app/modules/llm/catalog_models.py`
- Modify: `src/app/modules/llm/litellm_sync.py`（fetch 带字段、upsert、`build_catalog_payload`）
- Modify: `src/app/api/v1/llm_models_admin.py`（`_row_to_dict`）
- Modify: `src/app/api/v1/llm_models_public.py`（available items）
- Test: `tests/test_supports_reasoning.py`（追加 available）、`tests/test_llm_models_available.py`（fixture 可省略该列因 default）

**Interfaces:**
- `LlmModel.supports_reasoning: int`（0/1）
- fetch 每项含 `supports_reasoning: bool`
- catalog item 含 `supports_reasoning: bool`

- [ ] **Step 1: 迁移 0042** — `op.add_column("llm_models", sa.Column("supports_reasoning", sa.Integer(), nullable=False, server_default="0"))`
- [ ] **Step 2: ORM 加列**
- [ ] **Step 3: sync upsert 覆盖该列；build_catalog_payload / admin / public 返回布尔**
- [ ] **Step 4: 测 available 含 `supports_reasoning`**

```python
# 在 test_llm_models_available 或 test_supports_reasoning 中断言
# GET /llm-models/available 的 items[0] 含 supports_reasoning bool
```

- [ ] **Step 5: 跑相关测 GREEN**

---

### Task 3: `get_chat_model` 改 `reasoning_effort` + 目录防御（TDD）

**Files:**
- Modify: `src/app/modules/llm/lc_chat.py`
- Modify: `tests/test_deep_think_wiring.py`
- Modify: `tests/test_llm_lc_migration.py`
- Test: `tests/test_supports_reasoning.py`（追加目录防御）

**Interfaces:**
- `get_chat_model(..., enable_thinking=False)` → `extra_body={"reasoning_effort": "none"|"medium"}`，无 `thinking` 键
- 目录中该模型 `supports_reasoning` 非 true 时，强制 `none`

- [x] **Step 1: 改/写失败测**（断言 `reasoning_effort`，禁止 `thinking`；目录 false 强制 none）
- [x] **Step 2: RED**
- [x] **Step 3: 实现** — 查 `models_cache.get_models_catalog()`；在目录且非 true → 关；空目录或未命中 → 尊重调用方；只写 `reasoning_effort`
- [x] **Step 4: GREEN** — `test_deep_think_wiring` + `test_llm_lc_migration` + `test_supports_reasoning` + `test_lc_chat` 相关

---

### Task 4: 员工端开关显隐

**Files:**
- Modify: `web/src/app/chat/page.tsx`

- [x] **Step 1:** `ModelOption` 加 `supports_reasoning?: boolean`
- [x] **Step 2:** 解析当前模型（`selectedModel` 空 → `is_system_default` 或 `items[0]`）；仅 `supports_reasoning === true` 渲染按钮；`modelOptions` 为空不渲染
- [x] **Step 3:** `useEffect`：当前模型不支持时 `setDeepThink(false)`；`onSelectModel` 切到不支持时同样关闭

---

### Task 5: 管理端只读列 + 文档 + 断点

**Files:**
- Modify: `admin-web/src/app/(admin)/system/llm-models/page.tsx`
- Modify: `docs/01-产品需求/API接口规范.md`
- Modify: `docs/01-产品需求/数据库表结构.md`
- Modify: `docs/superpowers/specs/2026-08-19-unified-reasoning-effort-design.md`（状态→已确认/实现中）
- Modify: `docs/superpowers/CHECKPOINT.md`

- [x] **Step 1:** 表格加「支持思考」列（Tag 是/否），只读
- [x] **Step 2:** API/库表文档补字段与版本行
- [x] **Step 3:** 跑全套相关测；更新 CHECKPOINT

---

## Spec coverage

| 规格要求 | Task |
|---|---|
| reasoning_effort none/medium | 3 |
| 去掉 thinking.type | 3 |
| 提取 supports_reasoning | 1 |
| 表列 + 同步覆盖 | 2 |
| available/admin/cache 带字段 | 2 |
| 员工端隐藏开关 | 4 |
| 后端目录防御 | 3 |
| 管理端只读展示 | 5 |
| 文档 | 5 |
| 保留 reasoning_content 透传 | 3（不改透传，测保持绿） |
