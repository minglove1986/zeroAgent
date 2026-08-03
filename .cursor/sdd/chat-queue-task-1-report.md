# Task 1 报告：dismiss-card + supersede_pending_card

**状态：** DONE  
**时间：** 2026-07-30 14:43:04（东八区）  
**Commits：** none（按用户要求跳过）

---

## 1. 任务摘要

后端解锁 42213：支持作废 pending `message_cards`（`status=cancelled`，无迁移），并在 `POST /messages/send` 增加 `supersede_pending_card`。  
`retry` 路径保持原样（不支持 supersede）。

---

## 2. TDD 证据

### RED（实现前）

命令：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_dismiss_card.py -v --tb=short
```

结果：

| 用例 | 结果 | 原因 |
|---|---|---|
| `test_send_blocked_without_supersede` | PASSED | 现有 42213 行为 |
| `test_supersede_allows_send_and_cancels_card` | FAILED | `assert 422 == 200`（字段未生效） |
| `test_dismiss_card_idempotent` | FAILED | `assert 404 == 200`（路由不存在） |

### GREEN（实现后）

命令：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_dismiss_card.py tests/test_message_sse.py::test_send_blocked_when_pending_required_card -v --tb=short
```

结果：**4 passed**（约 4.31s）

| 用例 | 结果 |
|---|---|
| `test_send_blocked_without_supersede` | PASSED |
| `test_supersede_allows_send_and_cancels_card` | PASSED |
| `test_dismiss_card_idempotent` | PASSED |
| `test_send_blocked_when_pending_required_card` | PASSED |

---

## 3. 变更文件

| 文件 | 变更 |
|---|---|
| `tests/test_dismiss_card.py` | **新建**：3 个异步用例 + client fixture |
| `src/app/modules/conversation/runtime.py` | 新增 `cancel_pending_cards` |
| `src/app/api/v1/messages.py` | `MessageSend.supersede_pending_card`；`DismissCardBody`；`POST /messages/dismiss-card`；send 42213 分支支持 supersede；**retry 未改** |
| `docs/01-产品需求/API接口规范.md` | §10 表增加 dismiss-card；send 字段与 42213 说明；§10.1.1；版本 v0.8.3 |

---

## 4. 接口签名（与计划一致）

```python
async def cancel_pending_cards(
    db, *, conversation_id: str, card_id: str | None = None
) -> list[str]

# POST /api/v1/messages/dismiss-card → { dismissed_ids: string[] }
# MessageSend.supersede_pending_card: bool = False
```

---

## 5. Self-review

| 检查项 | 结论 |
|---|---|
| TDD：先红后绿 | 是 |
| 签名与 brief 一致 | 是 |
| retry 无 supersede | 是（仍仅 42213） |
| 无 DB migration | 是（`cancelled` 已支持） |
| 无前端改动 | 是 |
| 未 git commit | 是 |
| 权限：dismiss 本人或平台管理员 | 是 |
| 幂等：二次 dismiss 返回 `[]` | 是（测试覆盖） |

### 已知非阻塞点

1. `cancel_pending_cards` 作废该会话全部 `pending`（含非必填）；与 brief 一致。`has_pending_required_card` 仍只拦 `required=1`。
2. 测试日志中有 Celery `extract_memories` / `_extract_async` RuntimeWarning（既有问题，非本任务引入；用例仍通过）。
3. `send_message` 在 supersede 前未额外做会话归属校验（与改前 send 行为一致；dismiss 路径有校验）。

---

## 6. 下一步（非本 Task）

前端发送队列 / 停止 / 作废卡 UI；按计划 Task 2+ 继续。
