# Task 2 Brief

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
