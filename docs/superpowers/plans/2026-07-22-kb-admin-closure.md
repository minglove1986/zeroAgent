# KB 管理闭环（第一刀 B）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐知识库管理 API，并把 `/knowledge` 做成可用的管理闭环（列表/权限/上传进度/发布/软删恢复）。

**Architecture:** 复用 `list_accessible_kb_ids` / `can_access_kb_union`（D13）；在 `src/app/api/v1/knowledge.py` 补齐 GET/PUT/DELETE；软删清 `document_chunks` + `delete_kb_vectors_by_document`；前端单页三区对接这些接口并轮询 status。

**Tech Stack:** FastAPI、SQLAlchemy async、现有 Actor Session 头、Celery ingest（已有）、Next.js `/knowledge`、pytest

**Spec:** `docs/superpowers/specs/2026-07-22-kb-admin-closure-design.md`

## Global Constraints

- 单租户；禁止 `tenant_id`；不做 OpenIM / OSS 事件主路径  
- 创建 KB、PUT permissions：**仅** `platform_admin`  
- 文档读写/上传/发布/软删/恢复/GET permissions：超管 **或** 对该 KB 并集有权  
- 0 条权限行 → 非超管不可见该库（与检索一致）  
- 软删：写 `deleted_at` + 删 chunks + 清向量；恢复：清 `deleted_at`、status=`ready`，**不**自动 re-ingest  
- 上传不强制 QA；发布仍走 `evaluate_publish_gate`（42201）  
- 注释 `@author 赵振明`；时间用东八区实时  
- **Commit 步骤默认跳过**，除非用户明确要求 git commit  

## File Map

| 文件 | 职责 |
|---|---|
| `src/app/modules/knowledge/permissions.py` | 增加 `user_can_access_kb` |
| `src/app/modules/knowledge/document_ops.py`（新建） | `soft_delete_document` / `recover_document` |
| `src/app/api/v1/knowledge.py` | 补齐管理 API + Actor 鉴权 |
| `tests/test_kb_admin_api.py`（新建） | 管理 API 单测 |
| `web/src/app/knowledge/page.tsx` | 管理闭环 UI |
| `web/src/app/globals.css`（按需） | 知识库页少量样式 |
| `docs/superpowers/CHECKPOINT.md` | 断点 |

---

### Task 1: `user_can_access_kb` + 失败单测骨架

**Files:**
- Modify: `src/app/modules/knowledge/permissions.py`
- Create: `tests/test_kb_admin_api.py`

**Interfaces:**
- Produces: `async def user_can_access_kb(db, *, kb_id: str, user_id: str, department_ids: list[str], role_ids: list[str]) -> bool`
  - 该 KB 无任何 `KbPermission` 行 → `False`
  - 有行 → `can_access_kb_union(...)`

- [ ] **Step 1: Write the failing tests**

```python
"""KB 管理 API / 权限辅助（第一刀 B）。

@author 赵振明
@date <东八区实时>
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import KnowledgeBase, KbPermission
from app.modules.knowledge.permissions import user_can_access_kb
from app.shared.db import Base


@pytest.fixture()
async def db_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_user_can_access_kb_no_grants(db_factory) -> None:
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_x", name="x", description=None, created_by="usr_a"))
        await db.commit()
        ok = await user_can_access_kb(
            db, kb_id="kb_x", user_id="usr_1", department_ids=[], role_ids=["employee"]
        )
        assert ok is False


@pytest.mark.asyncio
async def test_user_can_access_kb_with_user_grant(db_factory) -> None:
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_y", name="y", description=None, created_by="usr_a"))
        db.add(KbPermission(kb_id="kb_y", subject_type="user", subject_id="usr_1"))
        await db.commit()
        ok = await user_can_access_kb(
            db, kb_id="kb_y", user_id="usr_1", department_ids=[], role_ids=["employee"]
        )
        assert ok is True
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
cd D:\HermesWork\zeroAgent
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_kb_admin_api.py::test_user_can_access_kb_no_grants tests/test_kb_admin_api.py::test_user_can_access_kb_with_user_grant -v
```

Expected: FAIL（`user_can_access_kb` 未定义）

- [ ] **Step 3: Minimal implementation**

在 `permissions.py` 追加：

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**（仅用户要求时）

---

### Task 2: GET `/knowledge-bases` + create 仅超管

**Files:**
- Modify: `src/app/api/v1/knowledge.py`
- Modify: `tests/test_kb_admin_api.py`

**Interfaces:**
- Consumes: `get_actor`, `is_platform_admin`, `list_accessible_kb_ids`, `load_user_department_ids`
- Produces: `GET /api/v1/knowledge-bases` → `ok({ items: [{id,name,description,created_at}] })`
- `POST /knowledge-bases`：非超管 → JSONResponse 403 + `fail(40301, ...)`

- [ ] **Step 1: Failing API tests（httpx AsyncClient + 覆盖 app）**

沿用仓库其它 API 测的挂载方式；若无现成 fixture，用：

```python
from httpx import ASGITransport, AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_list_kb_admin_sees_all(db_factory, monkeypatch) -> None:
    # monkeypatch get_db 指向内存库；请求头 X-Role=platform_admin
    ...
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/v1/knowledge-bases", headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"})
    assert r.status_code == 200
    assert r.json()["code"] == 0

@pytest.mark.asyncio
async def test_list_kb_employee_filtered(db_factory, monkeypatch) -> None:
    # 两库：仅 kb_open 授权给 usr_1
    ...
    r = await client.get(..., headers={"X-Role": "employee", "X-User-Id": "usr_1"})
    ids = [x["id"] for x in r.json()["data"]["items"]]
    assert ids == ["kb_open"]

@pytest.mark.asyncio
async def test_create_kb_forbidden_for_employee(...) -> None:
    r = await client.post("/api/v1/knowledge-bases", json={"name": "n"}, headers={"X-Role": "employee", "X-User-Id": "usr_1"})
    assert r.status_code == 403
```

实现时：先查仓库内 `tests/test_*` 是否已有 `ASGITransport` 模式（如 `test_approvals`）；有则照抄 fixture，无则在本文件内写最小 `override_get_db`。

- [ ] **Step 2: Run — expect FAIL（路由不存在或未鉴权）**

- [ ] **Step 3: Implement**

```python
@router.get("/knowledge-bases")
async def list_knowledge_bases(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    actor = get_actor(request)
    if is_platform_admin(actor):
        rows = (await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))).scalars().all()
    else:
        dept_ids = await load_user_department_ids(db, actor.user_id, extra_department_id=actor.department_id)
        allowed = await list_accessible_kb_ids(
            db, user_id=actor.user_id, department_ids=dept_ids, role_ids=[actor.role]
        )
        if not allowed:
            return ok({"items": []})
        rows = (
            await db.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.id.in_(allowed))
                .order_by(KnowledgeBase.created_at.desc())
            )
        ).scalars().all()
    items = [
        {
            "id": k.id,
            "name": k.name,
            "description": k.description,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in rows
    ]
    return ok({"items": items})
```

`create_kb` 开头加：

```python
actor = get_actor(request)
if not is_platform_admin(actor):
    return JSONResponse(status_code=403, content=fail(40301, "only platform_admin can create KB"))
# created_by=actor.user_id
```

签名改为接收 `request: Request`。

- [ ] **Step 4: Run — expect PASS**

---

### Task 3: permissions GET/PUT

**Files:**
- Modify: `src/app/api/v1/knowledge.py`
- Modify: `tests/test_kb_admin_api.py`

**Interfaces:**
- `GET .../permissions`：超管或有权用户  
- `PUT .../permissions`：仅超管；body `{ "items": [{"subject_type","subject_id"}] }` 全量替换  
- `subject_type` 必须 ∈ `user|department|role`，否则 422

- [ ] **Step 1: Failing tests**

```python
async def test_put_permissions_admin_only(...):
    # employee PUT → 403
    # admin PUT → 200；再 GET 看到 items

async def test_get_permissions_requires_access(...):
    # 无授权 employee → 403
    # 有授权 employee → 200 只读
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**

辅助函数（可放 knowledge.py 内）：

```python
async def _require_kb_read(request, db, kb_id: str) -> Actor | JSONResponse:
    actor = get_actor(request)
    if await db.get(KnowledgeBase, kb_id) is None:
        return JSONResponse(status_code=404, content=fail(40401, "kb not found"))
    if is_platform_admin(actor):
        return actor
    dept_ids = await load_user_department_ids(db, actor.user_id, extra_department_id=actor.department_id)
    if not await user_can_access_kb(db, kb_id=kb_id, user_id=actor.user_id, department_ids=dept_ids, role_ids=[actor.role]):
        return JSONResponse(status_code=403, content=fail(40301, "kb forbidden"))
    return actor
```

PUT：先删该 kb 全部 `KbPermission`，再插入 items。

- [ ] **Step 4: PASS**

---

### Task 4: documents list + status

**Files:**
- Modify: `src/app/api/v1/knowledge.py`
- Modify: `tests/test_kb_admin_api.py`

**Interfaces:**
- `GET /documents?kb_id=&include_deleted=0|1`
  - 返回 `items: [{ id, title, status, hit_rate, qa_count, deleted_at, updated_at, created_at }]`
  - 默认排除 `deleted_at IS NOT NULL`
- `GET /documents/{id}/status` → `{ status, hit_rate, qa_count, reason? }`
  - `reason`：仅 `failed` 时可选（第一刀可先不落库 reason，字段可省略）

- [ ] **Step 1: Failing tests** — 有权用户列出 ready 文档；软删文档仅 `include_deleted=1` 可见；status 含 `qa_count`

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement** — 用 `select(func.count()).where(DocumentQaPair.document_id==...)` 算 qa_count；鉴权走文档所属 `kb_id` 的 `_require_kb_read`

- [ ] **Step 4: PASS**

---

### Task 5: soft_delete + recover

**Files:**
- Create: `src/app/modules/knowledge/document_ops.py`
- Modify: `src/app/api/v1/knowledge.py`
- Modify: `tests/test_kb_admin_api.py`

**Interfaces:**
- Produces:
  - `async def soft_delete_document(db, document_id: str) -> Document | None`
  - `async def recover_document(db, document_id: str) -> Document | None`
- API: `DELETE /documents/{id}`、`POST /documents/{id}/recover`

- [ ] **Step 1: Unit tests for ops + API**

```python
@pytest.mark.asyncio
async def test_soft_delete_clears_chunks_and_sets_deleted_at(db_factory, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.knowledge.document_ops.delete_kb_vectors_by_document",
        lambda document_id: True,
    )
    # seed Document + DocumentChunk
    async with db_factory() as db:
        from app.modules.knowledge.document_ops import soft_delete_document
        doc = await soft_delete_document(db, "doc_1")
        assert doc is not None and doc.deleted_at is not None
        chunks = (await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == "doc_1"))).scalars().all()
        assert chunks == []

@pytest.mark.asyncio
async def test_recover_clears_deleted_at_sets_ready(db_factory) -> None:
    ...
    doc = await recover_document(db, "doc_1")
    assert doc.deleted_at is None
    assert doc.status == "ready"
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement**

```python
"""文档软删 / 恢复。

@author 赵振明
@date <东八区实时>
"""

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.kb_milvus import delete_kb_vectors_by_document


async def soft_delete_document(db: AsyncSession, document_id: str) -> Document | None:
    doc = await db.get(Document, document_id)
    if doc is None:
        return None
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    delete_kb_vectors_by_document(document_id)
    doc.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(doc)
    return doc


async def recover_document(db: AsyncSession, document_id: str) -> Document | None:
    doc = await db.get(Document, document_id)
    if doc is None:
        return None
    doc.deleted_at = None
    doc.status = "ready"
    await db.commit()
    await db.refresh(doc)
    return doc
```

路由层：鉴权 `_require_kb_read`（用 doc.kb_id）；404 用 `fail(40401)`。

- [ ] **Step 4: 同时给 `upload_document` / `publish_document` 加上 Request 鉴权（有权才可）**

- [ ] **Step 5: PASS**  
  `pytest tests/test_kb_admin_api.py -v`

---

### Task 6: 重做 `web/src/app/knowledge/page.tsx`

**Files:**
- Modify: `web/src/app/knowledge/page.tsx`
- Modify: `web/src/app/globals.css`（仅当需要 `.kb-*` 类时）

**Interfaces:**
- Consumes: Task 2–5 全部 API；现有 `apiJson`、`AppNav`

- [ ] **Step 1: 页面结构（client component）**

状态：`kbs`、`selectedKbId`、`docs`、`perms`、`showPerms`、`file`、`title`、`busy`、`error`、`msg`、`isAdmin`（可由首次 list 后根据「能否看到新建按钮」简化：尝试用环境/角色头不可靠；**第一刀**：始终渲染「新建」按钮，非超管点击后展示后端 403 文案；或调用登录态若前端已有 role 则用它——查 `web` 内是否存 role，有则用，无则按钮+403）。

布局：

1. 左：KB 列表 + 新建表单（name）  
2. 右：上传表单；文档表列：title / status / hit_rate / qa_count / 操作（发布、删除、恢复）  
3. 权限面板：列表 items + 增行 + 保存 PUT（失败 403 提示仅超管）

- [ ] **Step 2: 轮询**

```typescript
useEffect(() => {
  const processing = docs.filter((d) => d.status === "processing" && !d.deleted_at);
  if (!processing.length) return;
  const t = setInterval(async () => {
    // 对每个 id GET /api/v1/documents/{id}/status 更新行
  }, 2000);
  return () => clearInterval(t);
}, [docs]);
```

- [ ] **Step 3: 操作绑定**

- 发布：`POST .../publish`；422 展示 `message`  
- 删除：`DELETE ...` 后刷新列表  
- 恢复：`POST .../recover` 后提示「需重新上传/入库后才能检索」  
- 上传：沿用现有 base64 → `POST /documents/upload`

- [ ] **Step 4: 手工联调清单（打勾）**

1. 超管建库出现在列表  
2. PUT 一条 user 权限后，employee 头可见该库  
3. 上传 txt → processing → ready（需 Celery worker）或 Mock 路径下最终状态正确  
4. 无 QA 发布 → 42201  
5. 软删后 `include_deleted=1` 可见；恢复提示可读  

- [ ] **Step 5: Commit**（仅用户要求时）

---

### Task 7: CHECKPOINT + 回归

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`

- [ ] **Step 1: 跑回归**

```powershell
cd D:\HermesWork\zeroAgent
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_kb_admin_api.py tests/test_kb_d13_search.py tests/test_document_ingest.py -q
```

Expected: 全绿

- [ ] **Step 2: 更新 CHECKPOINT**  
  当前断点 = KB 管理闭环第一刀 B 已完成；下一步 = QA/hit_rate 流水线或拖拽/URL  

- [ ] **Step 3: 全量 pytest（可选但推荐）**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest -q
```

---

## Spec coverage checklist

| Spec 要求 | Task |
|---|---|
| GET KB 列表 + 并集过滤 | 2 |
| 创建仅超管 | 2 |
| GET/PUT permissions（PUT 仅超管） | 3 |
| documents 列表 + status 轮询字段 | 4 + 6 |
| 软删清向量 + recover 不自动入库 | 5 |
| upload/publish 鉴权 | 5 |
| `/knowledge` 管理闭环 UI | 6 |
| 不做拖拽/URL/批量/版本/命中算法 | —（刻意不做） |

## Placeholder scan

无 TBD；HTTP 测 fixture「照抄仓库现有模式」已在 Task 2 标明查找路径。
