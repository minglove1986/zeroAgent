# Task 3 报告：chatSendQueue 纯函数

**完成时间（东八区）**：2026-07-30 14:48:53  
**作者**：赵振明  
**状态**：✅ 已完成

## 变更摘要

| 文件 | 操作 |
|------|------|
| `web/src/lib/chatSendQueue.ts` | 新建：队列纯函数 |
| `web/src/lib/chatSendQueue.test.ts` | 新建：Node 内置 test 单测 |

**未改动**：`web/src/app/chat/page.tsx`（留 Task 4）

## 实现要点

- `CHAT_SEND_QUEUE_MAX = 5`；上限仅统计 `status === "queued"`（`sending/sent/failed` 不占名额）。
- `enqueue`：满员返回 `{ ok: false, reason: "full" }`；成功追加 `{ localId, text: trim(text), status: "queued" }`。
- `dequeueForSend`：取最早 `queued`，标 `sending`；`rest` 为全量更新后的数组（含 sending 项）；无 queued 返回 `null`。
- `removeQueued`：仅移除匹配 `localId` 且 `status === "queued"` 的项。
- `markStatus` / `clearQueue`：不可变更新 / 返回 `[]`。

## 验证

| 项 | 命令 | 结果 |
|----|------|------|
| 单测 8/8 | `node --experimental-strip-types --test src/lib/chatSendQueue.test.ts`（web/） | ✅ PASS |
| 类型检查 | `npx tsc --noEmit`（web/） | ✅ PASS |

### 测试覆盖

1. `CHAT_SEND_QUEUE_MAX === 5`
2. enqueue 满 5 返回 `full`
3. sending 项不计入上限
4. dequeue 最早 queued → sending
5. 无 queued 时 dequeue 为 null
6. removeQueued 仅删 queued
7. markStatus 不可变更新
8. clearQueue 返回空数组

## 风险与后续

1. **Task 4** 集成时：`setSendQueue(d.rest)` 可直接用 dequeue 返回值；`head.text` 供 `sendText`。
2. **测试跑法**：web 无 vitest/jest；单测用 Node 22 `--experimental-strip-types`；测试文件 `@ts-nocheck` + `.ts` 扩展导入。
3. **空文本**：`enqueue` 会 trim 后入队；ChatPage 应在调用前拦截空串。

## Git

按约束：**未 commit**。
