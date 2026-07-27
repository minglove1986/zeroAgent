# Task 1 Brief

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
