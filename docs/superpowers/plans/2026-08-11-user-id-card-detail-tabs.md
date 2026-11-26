# 用户身份证 + 详情四 Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为用户增加选填唯一 `id_card`，增强详情聚合，并落地管理端用户详情页（基本信息 / 部门与角色 / 会话历史 / 操作日志）。

**Architecture:** 迁移加列 → Schema/校验 → 创建更新与详情 GET 聚合 → 用户域审计列表 API → 管理端列表增强 + 新详情路由四 Tab。会话接口已存在，前端直接消费。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic；pytest/httpx；admin-web Next.js App Router + Ant Design。

**Spec:** `docs/superpowers/specs/2026-08-11-user-id-card-detail-tabs-design.md`

## Global Constraints

- 单租户，禁止 `tenant_id`
- API 固定 `:8000`，管理端本机多为 `:3001`；禁止随意改端口
- 管理端页只放 `admin-web/src/app/(admin)/**`，禁止页内再包 `AdminLayout`
- 注释：`@author 赵振明`；时间用东八区实时 `yyyy-MM-dd HH:mm:ss`
- TDD：每个 Task 先写失败测再实现
- **Git commit：** 本仓用户规则优先——未获用户明确「提交」指令时，**跳过**各 Task 的 commit 步骤；仍须跑通测试与验收
- 部署：改后端后需迁移 + 同步进 `zeroagent-api` 容器并重启；硬刷管理端

---

## File map

| 文件 | 职责 |
|---|---|
| `migrations/versions/0041_user_id_card.py` | 加 `users.id_card` + 唯一索引 |
| `src/app/models/user.py` | ORM 字段 `id_card` |
| `src/app/api/schemas/user.py` | Create/Update/Out + 嵌套 Dept/Role；校验 |
| `src/app/api/v1/users.py` | 写入校验、唯一冲突、详情聚合、`audit-logs` |
| `tests/test_user_id_card.py` | id_card / 手机校验 / 详情聚合 / 审计列表 |
| `admin-web/.../users/page.tsx` | 列表列、查看入口、表单字段 |
| `admin-web/.../users/[user_id]/page.tsx` | 详情顶栏 + 四 Tab |
| `docs/superpowers/CHECKPOINT.md` | 断点 |

---

### Task 1: 迁移 + ORM `id_card`

**Files:**
- Create: `migrations/versions/0041_user_id_card.py`
- Modify: `src/app/models/user.py`
- Test: `tests/test_user_id_card.py`（先写模型元数据断言；完整 API 测在 Task 2+）

**Interfaces:**
- Produces: `User.id_card: Mapped[str | None]`；DB 列 `VARCHAR(18) NULL` + unique

- [ ] **Step 1: 写失败测（元数据）**

在 `tests/test_user_id_card.py`：

```python
"""用户 id_card 与详情四 Tab 相关测。

@author 赵振明
@date <东八区实时>
"""

from __future__ import annotations

from app.models.user import User


def test_user_model_has_id_card_column() -> None:
    cols = {c.name for c in User.__table__.columns}
    assert "id_card" in cols
    assert User.__table__.c.id_card.nullable is True
```

- [ ] **Step 2: 跑测确认失败**

Run: `pytest tests/test_user_id_card.py::test_user_model_has_id_card_column -v`  
Expected: FAIL（无 `id_card`）

- [ ] **Step 3: 改 ORM**

`src/app/models/user.py` 在 `last_login_ip` 后增加：

```python
id_card: Mapped[str | None] = mapped_column(String(18), unique=True, nullable=True)
```

更新文件头 `@date` 为东八区实时。

- [ ] **Step 4: 写迁移**

`migrations/versions/0041_user_id_card.py`：

```python
"""users.id_card：选填身份证号（有值唯一）。

Revision ID: 0041_user_id_card
Revises: 0040_user_last_login_ip
Create Date: 2026-08-11

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041_user_id_card"
down_revision: Union[str, Sequence[str], None] = "0040_user_last_login_ip"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 id_card 列与唯一索引。"""
    op.add_column(
        "users",
        sa.Column("id_card", sa.String(length=18), nullable=True),
    )
    op.create_index("uk_users_id_card", "users", ["id_card"], unique=True)


def downgrade() -> None:
    """回滚 id_card。"""
    op.drop_index("uk_users_id_card", table_name="users")
    op.drop_column("users", "id_card")
```

- [ ] **Step 5: 跑测通过**

Run: `pytest tests/test_user_id_card.py::test_user_model_has_id_card_column -v`  
Expected: PASS

- [ ] **Step 6: Commit（仅用户要求时）**

```bash
git add migrations/versions/0041_user_id_card.py src/app/models/user.py tests/test_user_id_card.py
git commit -m "feat(users): add id_card column and ORM field"
```

---

### Task 2: Schema 校验 + 创建/更新读写 `id_card` / 手机

**Files:**
- Modify: `src/app/api/schemas/user.py`
- Modify: `src/app/api/v1/users.py`（create/update 归一化、唯一检查）
- Test: `tests/test_user_id_card.py`

**Interfaces:**
- Consumes: `User.id_card`
- Produces:
  - `normalize_id_card(raw: str | None) -> str | None`
  - `validate_phone_cn(phone: str) -> None`（非法抛/返回错误由路由转 422）
  - `UserCreate.id_card: str | None = None`
  - `UserUpdate.id_card: str | None = None`
  - `UserOut.id_card: str | None = None`
  - 冲突：`409` + `fail(40901, "身份证号已存在")`

- [ ] **Step 1: 写失败测**

追加到 `tests/test_user_id_card.py`（复用 `test_user_create.py` 的内存库 fixture 模式：内置 Role/Department/超管 + `X-User-Id`/`X-Role` 头）。最小 payload：

```python
def _payload(**kw):
    base = {
        "username": "u_idcard",
        "password": "123456",
        "name": "测身份证",
        "employee_no": "E_IDC_1",
        "email": "idc@example.com",
        "phone": "13800138000",
        "position": "员工",
        "hire_date": "2026-01-01",
        "main_department_id": "dept_root",
        "department_ids": ["dept_root"],
    }
    base.update(kw)
    return base

@pytest.mark.asyncio
async def test_create_user_with_id_card(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users",
        json=_payload(id_card="110101199001011234"),
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id_card"] == "110101199001011234"

@pytest.mark.asyncio
async def test_create_user_rejects_bad_id_card(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users",
        json=_payload(username="u_bad", employee_no="E_BAD", id_card="123"),
        headers=_admin_headers(),
    )
    assert resp.status_code == 422

@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_id_card(client: AsyncClient) -> None:
    card = "110101199001011235"
    r1 = await client.post("/api/v1/users", json=_payload(id_card=card), headers=_admin_headers())
    assert r1.status_code == 200
    r2 = await client.post(
        "/api/v1/users",
        json=_payload(username="u2", employee_no="E2", email="e2@x.com", phone="13800138001", id_card=card),
        headers=_admin_headers(),
    )
    assert r2.status_code == 409
    assert r2.json()["code"] == 40901

@pytest.mark.asyncio
async def test_create_user_rejects_bad_phone(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users",
        json=_payload(username="u_ph", employee_no="E_PH", phone="12345"),
        headers=_admin_headers(),
    )
    assert resp.status_code == 422

@pytest.mark.asyncio
async def test_update_user_id_card_normalize_x(client: AsyncClient) -> None:
    # 先创建无证用户，再 PUT id_card 末位 x → 存 X
    ...
```

（fixture 整段从 `tests/test_user_create.py` 复制并扩展；`create_all` 会带上新列。）

- [ ] **Step 2: 跑测确认失败**

Run: `pytest tests/test_user_id_card.py -v`  
Expected: 模型测 PASS；API 测 FAIL（无字段/未校验）

- [ ] **Step 3: Schema**

在 `src/app/api/schemas/user.py`：

```python
import re
from pydantic import field_validator, model_validator

_ID_CARD_RE = re.compile(r"^[0-9]{17}[0-9Xx]$")
_PHONE_CN_RE = re.compile(r"^1[3-9]\d{9}$")


def normalize_id_card(value: str | None) -> str | None:
    """空串→None；末位 x→X；格式非法由调用方/校验器拒绝。"""
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    if not _ID_CARD_RE.match(s):
        raise ValueError("身份证号须为 18 位（末位数字或 X）")
    return s[:-1] + s[-1].upper()


class UserCreate(BaseModel):
    # ...existing...
    id_card: str | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        if not _PHONE_CN_RE.match(v or ""):
            raise ValueError("手机号须为 11 位大陆号")
        return v

    @field_validator("id_card")
    @classmethod
    def _id_card(cls, v: str | None) -> str | None:
        return normalize_id_card(v)


class UserUpdate(BaseModel):
    # ...existing...
    id_card: str | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _PHONE_CN_RE.match(v):
            raise ValueError("手机号须为 11 位大陆号")
        return v

    @field_validator("id_card")
    @classmethod
    def _id_card(cls, v: str | None) -> str | None:
        return normalize_id_card(v)


class UserOut(BaseModel):
    # ...existing...
    id_card: str | None = None
```

Pydantic 校验失败由 FastAPI 转 422；若项目统一包 `fail(42201)`，在路由用 `try/except ValidationError` **不要**另起炉灶——优先与现有 Create 行为一致（RequestValidationError → 422）。

- [ ] **Step 4: users.py 创建/更新**

- `User(..., id_card=body.id_card)`  
- update：`if body.id_card is not None` 时写入（允许显式清空：规格为空串→None；若 Update 传 `null`，Pydantic 得区分「未传」与「清空」——**本期约定**：Update 字段 `id_card` 若出现在 body 则写入归一化结果，包括 `null` 清空。用 `model_fields_set`：

```python
if "id_card" in body.model_fields_set:
    user.id_card = body.id_card  # 已是 None 或合法串
```

- 创建/更新前查重：

```python
if body.id_card:  # create
    exists = await db.scalar(select(User.id).where(User.id_card == body.id_card))
    if exists:
        return JSONResponse(status_code=409, content=fail(40901, "身份证号已存在"))
```

更新时排除自身：`User.id != user_id`。

- [ ] **Step 5: 跑测通过**

Run: `pytest tests/test_user_id_card.py -v`  
Expected: PASS  
另跑：`pytest tests/test_user_create.py tests/test_users_api.py -v` 防回归

- [ ] **Step 6: Commit（仅用户要求时）**

```bash
git add src/app/api/schemas/user.py src/app/api/v1/users.py tests/test_user_id_card.py
git commit -m "feat(users): validate and persist id_card and CN phone"
```

---

### Task 3: 详情 GET 聚合 `departments` / `roles`

**Files:**
- Modify: `src/app/api/schemas/user.py`（可选嵌套模型文档化）
- Modify: `src/app/api/v1/users.py` `get_user`
- Test: `tests/test_user_id_card.py`

**Interfaces:**
- Produces（仅详情）：
```json
"departments": [{ "id": "dept_...", "name": "...", "is_primary": true }],
"roles": [{ "code": "employee", "name": "员工", "is_primary": true }]
```
- 兼容：保留 `extra_roles: string[]`（现有测/前端若依赖）
- 列表：`_user_to_dict` **不**带上述数组（或空数组）

- [ ] **Step 1: 写失败测**

```python
@pytest.mark.asyncio
async def test_get_user_detail_includes_departments_and_roles(client: AsyncClient) -> None:
    created = await client.post("/api/v1/users", json=_payload(username="u_d", employee_no="E_D", phone="13800138002", email="d@x.com"), headers=_admin_headers())
    uid = created.json()["data"]["id"]
    resp = await client.get(f"/api/v1/users/{uid}", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert any(d.get("id") == "dept_root" and d.get("is_primary") for d in data["departments"])
    assert any(d.get("name") for d in data["departments"])
    assert any(r.get("code") == "employee" and r.get("is_primary") for r in data["roles"])
```

- [ ] **Step 2: 跑测确认失败**

Expected: FAIL（现结构为 `department_id` / 无 `roles`）

- [ ] **Step 3: 实现 `get_user` 聚合**

伪代码：

```python
# 查 Department.name
# 主角色：user.role → Role.name
# 附加：UserRole → Role
out["departments"] = [
  {"id": d.department_id, "name": name_map.get(...), "is_primary": bool(d.is_primary)}
]
out["roles"] = [
  {"code": user.role, "name": ..., "is_primary": True},
  *[{"code": c, "name": ..., "is_primary": False} for c in extra if c != user.role],
]
out["extra_roles"] = [c for c in extra if c != user.role]  # 兼容
```

- [ ] **Step 4: 跑测通过**

Run: `pytest tests/test_user_id_card.py::test_get_user_detail_includes_departments_and_roles -v`  
另：`pytest tests/test_users_api.py::test_get_user_self -v`

- [ ] **Step 5: Commit（仅用户要求时）**

```bash
git add src/app/api/v1/users.py tests/test_user_id_card.py
git commit -m "feat(users): enrich user detail with named departments and roles"
```

---

### Task 4: `GET /api/v1/users/{user_id}/audit-logs`

**Files:**
- Modify: `src/app/api/v1/users.py`（新路由须在 `/{user_id}` 静态冲突前注意：挂在同 router 上用完整 path 或放在 `get_user` 之后均可，因后缀更长——FastAPI 按注册匹配；**放在 `get_user` 之后**即可）
- Modify: `src/app/modules/audit/service.py`（可选 `query_for_user`）
- Test: `tests/test_user_id_card.py`

**Interfaces:**
- `GET /api/v1/users/{user_id}/audit-logs?page=1&page_size=20`
- 鉴权：与 `get_user` 相同（本人 / platform+ / 范围内 department_admin）
- 过滤：`(resource_id == user_id OR actor_id == user_id)` AND `action` 前缀 ∈ `user.` / `auth.`
- 返回：`{ items: [...], total, page, page_size }`

- [ ] **Step 1: 写失败测**

```python
@pytest.mark.asyncio
async def test_user_audit_logs_lists_user_actions(client: AsyncClient) -> None:
    created = await client.post(..., headers=_admin_headers())
    uid = created.json()["data"]["id"]
    # create 已写 user.create 审计
    resp = await client.get(f"/api/v1/users/{uid}/audit-logs", headers=_admin_headers())
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert any(i["action"] == "user.create" for i in items)
```

- [ ] **Step 2: 跑测确认失败** → 404

- [ ] **Step 3: service 查询**

```python
async def query_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ConfigAuditLog], int]:
    prefixes = ("user.", "auth.")
    # WHERE (resource_id=:uid OR actor_id=:uid)
    # AND (action LIKE 'user.%' OR action LIKE 'auth.%')
    # ORDER BY created_at DESC
```

路由：权限复制 `get_user`；序列化字段对齐规格。

- [ ] **Step 4: 跑测通过**

Run: `pytest tests/test_user_id_card.py::test_user_audit_logs_lists_user_actions -v`

- [ ] **Step 5: Commit（仅用户要求时）**

```bash
git add src/app/api/v1/users.py src/app/modules/audit/service.py tests/test_user_id_card.py
git commit -m "feat(users): list user-scoped audit logs"
```

---

### Task 5: 管理端列表 — 手机/身份证列 + 表单 + 查看入口

**Files:**
- Modify: `admin-web/src/app/(admin)/organization/users/page.tsx`
- Manual verify（无强制前端测框架则手工）

**Interfaces:**
- Consumes: `UserOut.id_card`、`phone`
- Link: `/organization/users/${id}`

- [ ] **Step 1: 扩展 `UserOut` 类型与列**

```tsx
id_card?: string | null;
// columns: 手机、身份证；空 → "—"
// actions: <Link href={`/organization/users/${r.id}`}>查看</Link>
```

- [ ] **Step 2: 新建/编辑表单**

- 新建补齐：`email`、`phone`（pattern `/^1[3-9]\d{9}$/`）、`position`、`hire_date`、`id_card`（选填，pattern `/^[0-9]{17}[0-9Xx]$/`）
- 编辑增加 `id_card`；手机同校验
- `hire_date` 可用 `Input` 文本 `YYYY-MM-DD` 或 DatePicker（与现栈一致即可）

- [ ] **Step 3: 手工验收**

本机 admin `:3001` 打开用户管理：列表见两列；表单可填身份证。

- [ ] **Step 4: Commit（仅用户要求时）**

```bash
git add admin-web/src/app/(admin)/organization/users/page.tsx
git commit -m "feat(admin): show phone/id_card on users list and forms"
```

---

### Task 6: 管理端详情页四 Tab

**Files:**
- Create: `admin-web/src/app/(admin)/organization/users/[user_id]/page.tsx`

**Interfaces:**
- `GET /api/v1/users/{id}` → 基本信息 + 部门角色
- `GET /api/v1/users/{id}/sessions?limit=10`
- `POST /api/v1/users/{id}/sessions/revoke-all`
- `GET /api/v1/users/{id}/audit-logs?page=&page_size=`
- 编辑：页内 Drawer，`PUT /api/v1/users/{id}`（字段对齐列表编辑）

- [ ] **Step 1: 脚手架页面**

`"use client"`；`useParams().user_id`；`useAdminPageTitle("用户详情")`；404 空态 + `Link` 回 `/organization/users`。

- [ ] **Step 2: 顶栏**

Avatar 首字；name / `@username` / employee_no / status Tag；按钮：返回、编辑、重置密码、启停、离职（权限与列表页相同：调用同一 API）。

- [ ] **Step 3: Tabs**

1. **基本信息** — `Descriptions`：phone、email、id_card、position、hire_date、created_at、last_login_at、last_login_ip  
2. **部门与角色** — 渲染 `departments` / `roles`  
3. **会话历史** — Table：`created_at`/`client_ip`/`user_agent`；Button 注销全部 + `modal.confirm`  
4. **操作日志** — Table + pagination 调 audit-logs  

- [ ] **Step 4: 内嵌编辑 Drawer**

保存成功后 `loadDetail()`。

- [ ] **Step 5: 手工验收四 Tab**

用 `root` 打开某用户详情：四 Tab 可切换；会话可注销；操作日志可见 `user.create` 等。

- [ ] **Step 6: Commit（仅用户要求时）**

```bash
git add "admin-web/src/app/(admin)/organization/users/[user_id]/page.tsx"
git commit -m "feat(admin): user detail page with four tabs"
```

---

### Task 7: 部署、文档、断点

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`
- Optional: `docs/01-产品需求/权限用户菜单PRD.md` §3.2 补一行 `id_card`（若改 PRD，注明与实现同步）

- [ ] **Step 1: 升迁移并热更 API**

```powershell
docker cp "d:\HermesWork\zeroAgent\migrations\versions\0041_user_id_card.py" "zeroagent-api:/app/migrations/versions/0041_user_id_card.py"
# 同步改过的 py：models/user.py schemas/user.py api/v1/users.py modules/audit/service.py
docker exec -e PYTHONPATH=/app/src -w /app zeroagent-api alembic upgrade head
docker restart zeroagent-api
```

- [ ] **Step 2: 全量相关测**

Run: `pytest tests/test_user_id_card.py tests/test_user_create.py tests/test_users_api.py -v`  
Expected: PASS

- [ ] **Step 3: 更新 CHECKPOINT**

覆盖「当前断点」；日志追加一条（禁止写密码明文）。

- [ ] **Step 4: 规格状态**

将 spec 文首状态改为「已计划 / 实现中」。

- [ ] **Step 5: Commit（仅用户要求时）**

```bash
git add docs/superpowers/CHECKPOINT.md docs/superpowers/specs/2026-08-11-user-id-card-detail-tabs-design.md
git commit -m "docs: checkpoint user id_card detail tabs"
```

---

## Spec coverage（自审）

| 规格项 | Task |
|---|---|
| `id_card` 列/唯一/选填 | 1–2 |
| 手机 11 位校验 | 2 |
| 明文列表/表单 | 5 |
| GET 详情 departments/roles | 3 |
| 会话复用 | 6 |
| audit-logs 新 API | 4 |
| 详情四 Tab + 顶栏 | 6 |
| 不做脱敏/员工自助/四步向导 | 全局非目标 |
| CHECKPOINT | 7 |

## Placeholder scan

无 TBD；冲突码固定 `40901`；清空身份证用 `model_fields_set`。

## Type consistency

- 详情 `departments[].id`（非 `department_id`）；保留 `extra_roles` 兼容  
- `roles[].code` / `is_primary`  
- 审计过滤前缀 `user.` / `auth.`
