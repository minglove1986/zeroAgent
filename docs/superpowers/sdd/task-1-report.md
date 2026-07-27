# Task 1 报告：`user_can_access_kb` + 失败单测骨架

> **计划**：`docs/superpowers/plans/2026-07-22-kb-admin-closure.md` Task 1  
> **执行时间**：2026-07-23 09:03:40（东八区）  
> **状态**：DONE

## 目标

新增 `user_can_access_kb` 单库并集鉴权辅助函数，并建立 `tests/test_kb_admin_api.py` 单测骨架（2 用例）。

## 变更文件

| 操作 | 路径 |
|---|---|
| 新建 | `tests/test_kb_admin_api.py` |
| 修改 | `src/app/modules/knowledge/permissions.py`（追加 `user_can_access_kb`） |

## TDD 证据

### Step 1 — 写失败测试

按 brief  verbatim 创建 `tests/test_kb_admin_api.py`（`@date` 使用实时东八区 `2026-07-23 09:03:40`）。

### Step 2 — RED

```text
ImportError: cannot import name 'user_can_access_kb' from 'app.modules.knowledge.permissions'
```

命令：

```powershell
cd D:\HermesWork\zeroAgent
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_kb_admin_api.py::test_user_can_access_kb_no_grants tests/test_kb_admin_api.py::test_user_can_access_kb_with_user_grant -v
```

结果：收集阶段 ERROR（符合预期）。

### Step 3 — 最小实现

在 `permissions.py` 追加 `user_can_access_kb`：

- 查询 `KbPermission` 中 `kb_id` 匹配行
- 无行 → `False`
- 有行 → 转 `KbGrant` 列表，委托 `can_access_kb_union(...)`

### Step 4 — GREEN

```text
tests/test_kb_admin_api.py::test_user_can_access_kb_no_grants PASSED
tests/test_kb_admin_api.py::test_user_can_access_kb_with_user_grant PASSED
2 passed in 0.80s
```

## 接口行为

```python
async def user_can_access_kb(
    db: AsyncSession,
    *,
    kb_id: str,
    user_id: str,
    department_ids: list[str],
    role_ids: list[str],
) -> bool
```

| 场景 | 期望 |
|---|---|
| KB 无任何 `KbPermission` 行 | `False` |
| 有权限行且并集命中（user/dept/role） | `True`（经 `can_access_kb_union`） |
| 有权限行但未命中 | `False` |

## 自检

- [x] 与 D13 `can_access_kb_union` / `list_accessible_kb_ids` 语义一致（0 行拒绝）
- [x] 未引入 API 路由或前端改动（Task 1 范围）
- [x] 无 linter 报错
- [x] 未 git commit（仓库无 `.git`）

## 遗留 / 关注点

无阻塞项。后续 Task 2+ 将在同一测试文件中追加管理 API 用例。

## 下一步

执行计划 Task 2（`document_ops` 软删/恢复 + 对应单测）。
