# 管理端 LiteLLM 按模型用量成本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建独立 `modules/litellm` 包与管理端 BFF，按平台模型目录展示 LiteLLM 用量/成本汇总；页内声明以 LiteLLM 为准。

**Architecture:** `http_client` + `spend` 只调 LiteLLM Proxy；API `/api/v1/admin/litellm/spend/by-model` 与系统 `/usage` 隔离；用量页读 BFF + Alert 外链。不迁 `llm/litellm_sync`、不改 `modules/usage`。

**Tech Stack:** FastAPI、httpx、pytest；admin-web Next.js + Ant Design。

**Spec:** `docs/superpowers/specs/2026-08-12-admin-litellm-spend-by-model-design.md`

## Global Constraints

- 包 `app.modules.litellm` **禁止** import `app.modules.usage`
- 不修改 `modules/usage/*`、`modules/llm/litellm_sync.py`（除非 typo 级无关）
- 密钥仅环境变量；不回传 master key
- 注释：`@author 赵振明`；东八区实时时间
- **Git commit：** 未明确要求时跳过
- API 端口固定 `:8000`

---

## File map

| 文件 | 职责 |
|---|---|
| `src/app/modules/litellm/__init__.py` | 包文档 |
| `src/app/modules/litellm/http_client.py` | Proxy GET |
| `src/app/modules/litellm/schemas.py` | DTO |
| `src/app/modules/litellm/spend.py` | 聚合 + 对齐目录 |
| `src/app/api/v1/admin_litellm.py` | 路由 |
| `src/app/api/v1/router.py` | include |
| `tests/test_admin_litellm_spend.py` | 测 |
| `admin-web/.../operations/usage/page.tsx` | UI |
| `docs/superpowers/CHECKPOINT.md` | 断点 |

---

### Task 1: `http_client` + 纯函数聚合（TDD）

**Files:**
- Create: `src/app/modules/litellm/__init__.py`
- Create: `src/app/modules/litellm/http_client.py`
- Create: `src/app/modules/litellm/spend.py`（先聚合函数）
- Test: `tests/test_admin_litellm_spend.py`

**Interfaces:**
- Produces:
  - `async def litellm_get(path: str, *, params: dict | None = None) -> Any`
  - `def aggregate_spend_by_model(raw_rows: list[dict]) -> dict[str, dict[str, float|int]]`
  - `class LiteLLMUnavailableError(Exception)`

- [ ] **Step 1: 写失败测（聚合）**

```python
"""LiteLLM 管理端用量 BFF 测。

@author 赵振明
@date <东八区实时>
"""
from app.modules.litellm.spend import aggregate_spend_by_model

def test_aggregate_spend_by_model_sums_rows() -> None:
    rows = [
        {"model": "MiniMax-M3", "spend": 0.1, "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        {"model": "MiniMax-M3", "spend": 0.2, "prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        {"model": "other", "spend": 1.0, "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    ]
    out = aggregate_spend_by_model(rows)
    assert out["MiniMax-M3"]["spend"] == 0.3
    assert out["MiniMax-M3"]["api_requests"] == 2
    assert out["MiniMax-M3"]["total_tokens"] == 40
    assert out["other"]["spend"] == 1.0
```

- [ ] **Step 2: 跑测确认 RED**

Run: `d:\HermesWork\zeroAgent\.venv\Scripts\python.exe -m pytest tests/test_admin_litellm_spend.py::test_aggregate_spend_by_model_sums_rows -v`  
Expected: FAIL（模块不存在）

- [ ] **Step 3: 最小实现**

`__init__.py`：

```python
"""LiteLLM Proxy 专用集成（与 modules.usage / modules.llm 对话链隔离）。

@author 赵振明
"""
```

`http_client.py`：用 `get_settings().litellm_proxy_url` + `litellm_master_key`；`httpx.AsyncClient(timeout=15)`；非 2xx 抛 `LiteLLMUnavailableError`。

`spend.py` 中 `aggregate_spend_by_model`：按 `model` 或 `model_name` 键累加；缺字段当 0；每行 `api_requests += 1`。

- [ ] **Step 4: 跑测 PASS**

- [ ] **Step 5: Commit（仅用户要求时）**

---

### Task 2: `merge_catalog_with_spend` + `fetch_spend_by_model`

**Files:**
- Modify: `src/app/modules/litellm/spend.py`
- Modify: `src/app/modules/litellm/schemas.py`（可选 dataclass）
- Test: `tests/test_admin_litellm_spend.py`

**Interfaces:**
- Produces:
```python
async def fetch_spend_by_model(
    *,
    start_date: str,
    end_date: str,
    catalog: list[dict],  # {model_name, display_name, enabled}
) -> dict  # 规格 §3 成功体（无 HTTP 包装）
```

- [ ] **Step 1: 测对齐逻辑（mock http）**

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.modules.litellm import spend as spend_mod

@pytest.mark.asyncio
async def test_fetch_spend_by_model_aligns_catalog() -> None:
    catalog = [
        {"model_name": "MiniMax-M3", "display_name": "MM", "enabled": True},
        {"model_name": "idle", "display_name": "Idle", "enabled": False},
    ]
    fake_logs = [
        {"model": "MiniMax-M3", "spend": 0.5, "prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        {"model": "ghost", "spend": 9.0, "prompt_tokens": 9, "completion_tokens": 0, "total_tokens": 9},
    ]
    with patch.object(spend_mod, "_fetch_raw_spend_rows", new=AsyncMock(return_value=fake_logs)):
        data = await spend_mod.fetch_spend_by_model(
            start_date="2026-08-01", end_date="2026-08-12", catalog=catalog
        )
    assert data["source"] == "litellm"
    assert "LiteLLM" in data["disclaimer"]
    mm = next(i for i in data["items"] if i["model_name"] == "MiniMax-M3")
    assert mm["spend"] == 0.5 and mm["matched"] is True
    idle = next(i for i in data["items"] if i["model_name"] == "idle")
    assert idle["api_requests"] == 0
    assert any(u["model_name"] == "ghost" for u in data["unmatched"])
```

- [ ] **Step 2: RED → 实现 `_fetch_raw_spend_rows`**

逻辑：
1. `litellm_get("/spend/logs", params={start_date, end_date, summarize: true})`
2. 规范化为 list[dict]（若返回包在 `data`/`results` 内则展开；summarize 日聚合则展平各日 models）
3. 失败则试 `/global/spend/report`，从 metadata[].model 抽行
4. 仍失败 → `LiteLLMUnavailableError`

`fetch_spend_by_model`：聚合 → 与 catalog 对齐 → 填 `totals`、`litellm_ui_url`（`proxy.rstrip('/') + '/ui'`）。

- [ ] **Step 3: PASS**

- [ ] **Step 4: Commit（仅用户要求时）**

---

### Task 3: Admin API 路由

**Files:**
- Create: `src/app/api/v1/admin_litellm.py`
- Modify: `src/app/api/v1/router.py`
- Test: `tests/test_admin_litellm_spend.py`（ASGI + 依赖覆盖）

**Interfaces:**
- `GET /api/v1/admin/litellm/spend/by-model`
- Depends: `require_platform_admin`
- Catalog：`select(LlmModel)` → list dict；空目录则 items=[] 仍可返回 unmatched

- [ ] **Step 1: API 测**

复用项目常见内存库 fixture 风格（或 httpx ASGI + override `require_platform_admin` / mock `fetch_spend_by_model`）：

```python
@pytest.mark.asyncio
async def test_admin_spend_by_model_ok(client, monkeypatch):
    async def fake(**kwargs):
        return {
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "source": "litellm",
            "litellm_ui_url": "http://127.0.0.1:4000/ui",
            "disclaimer": "详细用量与计费以 LiteLLM 系统为准；本页仅为汇总展示。",
            "totals": {"spend": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "api_requests": 0},
            "items": [],
            "unmatched": [],
        }
    monkeypatch.setattr("app.api.v1.admin_litellm.fetch_spend_by_model", fake)
    # 或 patch spend 模块路径与路由 import 一致
    resp = await client.get(
        "/api/v1/admin/litellm/spend/by-model?start_date=2026-08-01&end_date=2026-08-12",
        headers={"X-User-Id": "usr_admin", "X-Role": "platform_admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["source"] == "litellm"
```

另测：日期颠倒 → 422；`LiteLLMUnavailableError` → 503。

- [ ] **Step 2: 实现路由**

```python
@router.get("/api/v1/admin/litellm/spend/by-model")
async def spend_by_model(...):
    # 默认近 7 天
    # catalog from db
    try:
        data = await fetch_spend_by_model(...)
    except LiteLLMUnavailableError as e:
        return JSONResponse(503, fail(50301, str(e)))
    return ok(data)
```

- [ ] **Step 3: include_router**

- [ ] **Step 4: PASS + 确认无 import usage**

Run: `rg "modules.usage" src/app/modules/litellm` → 无匹配

- [ ] **Step 5: Commit（仅用户要求时）**

---

### Task 4: 管理端用量成本页

**Files:**
- Modify: `admin-web/src/app/(admin)/operations/usage/page.tsx`

- [ ] **Step 1: 替换占位**

- `Alert` type="info"：disclaimer 文案 + `<a href={litellm_ui_url} target="_blank">打开 LiteLLM 控制台</a>`
- `RangePicker`（默认近 7 天）→ `apiJson('/api/v1/admin/litellm/spend/by-model?...')`
- `Table`：display_name、model_name、api_requests、prompt_tokens、completion_tokens、total_tokens、spend
- Collapse：unmatched
- totals 摘要一行
- 错误 `message.error`

- [ ] **Step 2: 手工验收**（登录管理端点菜单；LiteLLM 挂了应见错误提示）

- [ ] **Step 3: Commit（仅用户要求时）**

---

### Task 5: 部署热更 + CHECKPOINT + 规格状态

- Docker API：`docker cp` 新模块与 `admin_litellm.py`、`router.py` → restart `zeroagent-api`
- 规格文首 →「已实现」
- 更新 `CHECKPOINT.md`

---

## Spec coverage

| 规格 | Task |
|---|---|
| `modules/litellm` 包 | 1–2 |
| BFF by-model | 3 |
| 用量页 + disclaimer | 4 |
| 不碰 usage / litellm_sync | 全局 |
| CHECKPOINT | 5 |

## Placeholder scan

无 TBD；503 码用 `50301`；默认日期近 7 天在路由内用 `date.today()` 计算。
