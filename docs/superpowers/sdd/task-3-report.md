# Task 3 报告：GET/PUT `/knowledge-bases/{id}/permissions`

> **计划**：`docs/superpowers/plans/2026-07-22-kb-admin-closure.md` Task 3  
> **Brief**：`docs/superpowers/sdd/task-3-brief.md`  
> **执行时间**：2026-07-23 09:15:40（东八区）  
> **状态**：DONE

## 目标

- `GET /api/v1/knowledge-bases/{kb_id}/permissions`：超管或 `user_can_access_kb` 有权用户可读。
- `PUT .../permissions`：仅 `platform_admin`；body `{ items: [{subject_type, subject_id}] }` **全量替换**。
- `subject_type` ∈ `user|department|role`，否则 HTTP 422。
- 抽出 `_require_kb_read`（404 / 403 / Actor）。

## 变更文件

| 操作 | 路径 |
|---|---|
| 修改 | `src/app/api/v1/knowledge.py` |
| 修改 | `tests/test_kb_admin_api.py`（保留 Task 1–2，追加 3 个权限测） |

## TDD 证据

### Step 1 — 写失败测试

- `test_put_permissions_admin_only`：employee PUT → 403；admin PUT → 200 且 GET 见 items
- `test_get_permissions_requires_access`：无授权 → 403；有授权 → 200 只读
- `test_put_permissions_invalid_subject_type`：非法 `subject_type` → 422

### Step 2 — RED

```text
test_put_permissions_admin_only FAILED              — 404（路由未注册）
test_get_permissions_requires_access FAILED         — 404
test_put_permissions_invalid_subject_type FAILED    — 404
3 failed
```

### Step 3 — 实现

- `_require_kb_read`：KB 不存在 404；超管放行；否则并集鉴权，失败 403。
- `GET`：经 `_require_kb_read` 后返回 `ok({items})`。
- `PUT`：仅超管；删该 kb 全部 `KbPermission` 再插入；`KbPermissionItem.subject_type` 用 `Literal` 约束。

### Step 4 — GREEN

```text
tests/test_kb_admin_api.py  ........  8 passed in 1.94s
```

命令：

```powershell
cd D:\HermesWork\zeroAgent
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_kb_admin_api.py -q
```

## 接口行为

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/v1/knowledge-bases/{kb_id}/permissions` | 超管或有权；`ok({ items })` |
| PUT | `/api/v1/knowledge-bases/{kb_id}/permissions` | 仅超管全量替换；非法 type → 422 |

## 自检

- [x] Task 1–2 单测保留且仍通过（共 8 passed）
- [x] PUT 全量替换；GET 走 `_require_kb_read`
- [x] 未引入 OpenIM / `tenant_id`
- [x] 未 git commit

## 遗留 / 关注点

- 非法 `subject_type` 由 Pydantic `Literal` 直接 422（FastAPI 默认校验体），未走业务 `fail(42201)` 包装；与 brief「否则 422」一致，若需统一 envelope 可再收敛。
- `_require_kb_read` 供后续 Task 4+ 文档鉴权复用。
- **下一刀**：Task 4 documents list + status。
