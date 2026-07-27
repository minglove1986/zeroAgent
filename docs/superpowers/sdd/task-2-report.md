# Task 2 报告：GET `/knowledge-bases` + create 仅超管

> **计划**：`docs/superpowers/plans/2026-07-22-kb-admin-closure.md` Task 2  
> **Brief**：`docs/superpowers/sdd/task-2-brief.md`  
> **执行时间**：2026-07-23 09:09:16（东八区）  
> **状态**：DONE

## 目标

- 新增 `GET /api/v1/knowledge-bases`：超管看全部；非超管按 `list_accessible_kb_ids` + `load_user_department_ids` 过滤。
- `POST /api/v1/knowledge-bases`：非 `platform_admin` → HTTP 403 + `fail(40301, ...)`；超管创建时 `created_by=actor.user_id`。

## 变更文件

| 操作 | 路径 |
|---|---|
| 修改 | `src/app/api/v1/knowledge.py` |
| 修改 | `tests/test_kb_admin_api.py`（保留 Task 1 两测，追加 3 个 HTTP 测） |

## TDD 证据

### Step 1 — 写失败测试

在 `tests/test_kb_admin_api.py` 追加：

- `test_list_kb_admin_sees_all`
- `test_list_kb_employee_filtered`
- `test_create_kb_forbidden_for_employee`

HTTP 模式：`create_app()` + `dependency_overrides[get_db]` + `ASGITransport`/`AsyncClient`，`finally` 清理 overrides。

### Step 2 — RED

```text
test_list_kb_admin_sees_all FAILED          — 405 Method Not Allowed（无 GET）
test_list_kb_employee_filtered FAILED       — 405 Method Not Allowed
test_create_kb_forbidden_for_employee FAILED — 200（未鉴权）
2 passed, 3 failed
```

### Step 3 — 实现

`knowledge.py`：

- `list_knowledge_bases`：`get_actor` → 超管全量 `order_by created_at.desc`；否则部门并集过滤。
- `create_kb`：接收 `Request`；非超管 `JSONResponse(403, fail(40301, ...))`；`created_by=actor.user_id`。

### Step 4 — GREEN

```text
tests/test_kb_admin_api.py::test_user_can_access_kb_no_grants PASSED
tests/test_kb_admin_api.py::test_user_can_access_kb_with_user_grant PASSED
tests/test_kb_admin_api.py::test_list_kb_admin_sees_all PASSED
tests/test_kb_admin_api.py::test_list_kb_employee_filtered PASSED
tests/test_kb_admin_api.py::test_create_kb_forbidden_for_employee PASSED
5 passed in 1.78s
```

命令：

```powershell
cd D:\HermesWork\zeroAgent
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_kb_admin_api.py -v
```

## 接口行为

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/v1/knowledge-bases` | `ok({ items: [{id,name,description,created_at}] })` |
| POST | `/api/v1/knowledge-bases` | 仅超管；否则 403 / `code=40301` |

## 自检

- [x] Task 1 单测保留且仍通过
- [x] 列表过滤复用 `list_accessible_kb_ids` / `load_user_department_ids`
- [x] 未引入 OpenIM / `tenant_id`
- [x] 未 git commit（无 `.git`）

## 遗留 / 关注点

- 未单独覆盖「超管 POST 创建成功」用例（brief 未要求）；行为已按 `created_by=actor.user_id` 实现。
- 旧同名报告（celery-harden Task 2）已被本报告覆盖；若需史料请查 git/备份。

## 下一步

计划 Task 3：permissions GET/PUT。
