# Task 3 Brief

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
