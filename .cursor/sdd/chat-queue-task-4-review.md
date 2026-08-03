# Task 4 代码审查（Fix round 复审）：ChatPage 发送队列状态机

**审查时间（东八区）**：2026-07-30 15:05:00  
**审查范围**：`web/src/app/chat/page.tsx`、`web/src/app/globals.css`（对照设计 §4–§8 + brief + report Fix round）  
**方式**：只读核对源码 / report；未改仓库业务代码  
**前次结论**：With fixes（§7 删队、§8 失败重试为 Important 缺口）

---

## Verdict

**Approved**

Fix round 已闭合前次两项 Important 缺口（排队取消、失败重试）；核心状态机与 brief 对齐。浏览器实机 E2E 仍缺，按 controller 裁定记为 Minor 文档项，**不阻塞** Approved。

---

## Spec Compliance

| 需求点 | 结论 | 证据 |
|--------|------|------|
| idle 直发 / 非 idle 入队 FIFO | ✅ | `onSubmit`：`canDirect` → `sendText`；否则 `enqueue` |
| 队列上限 5（仅计 queued） | ✅ | `queuedCount >= CHAT_SEND_QUEUE_MAX` + `enqueue` 二次校验 |
| `supersede_pending_card: true` | ✅ | `sendText` → `postSse` body |
| AbortSignal 停止 | ✅ | `AbortController` + `postSse(..., { signal })`；`onStop` abort |
| AbortError →「已停止」且不 toast，随后出队 | ✅ | `isAbortError` → `markLastAssistantStopped`；`finally` → `settleAfterStream` |
| 流结束 / 停止后出队串行 | ✅ | `settleAfterStream` + `dequeueForSend` + 递归 `sendText` |
| pendingCard 不再硬拦 compose | ✅ | `onSubmit` 无 `if (pendingCard) return`；textarea 仅 `disabled={loading}` |
| 有卡发送 → 本地「已跳过」+ supersede | ✅ | `skipLocalPendingCard` + 卡片 UI `chat-card-skipped` |
| 切会话 / 新对话 abort + 清队列 | ✅ | `resetStreamSession`（`sessionGenRef++` / abort / `clearQueue`） |
| streaming 禁选模 / retry；允许切会话 | ✅ | `onSelectModel` / `retryMessage` 看 idle；`selectConversation` 先 reset |
| 焦点：发送/入队后 + idle 回落 | ✅ | `focusComposer`：入队/直发、`settle` idle、`onStop`、切会话/新对话、`onRemoveQueued` |
| 样式三类 + 停止按钮 + 队列操作 | ✅ | `.chat-queue-tag` / `.chat-card-skipped` / `.chat-stopped-hint` / `.send-btn-stop` / `.chat-queue-action` |
| **排队项可删除出队（§7）** | ✅ | `removeQueued` import；`onRemoveQueued`；queued 气泡「取消」按钮（`aria-label="取消排队"`） |
| **发送失败可重试（§8）** | ✅ | `onRetryFailedQueue`；failed 气泡「重试」；idle 立即泵送 / 流式中等待 `settleAfterStream`；`dequeueForSend` 仅取 `queued`，failed 不堵队 |
| 出队间隙再次 focus（§4.3） | ⚠️ 部分 | 仅在完全 `idle` 时 focus；drain 间隙未再 focus（Minor） |
| 浏览器手测清单 | ⚠️ Minor | 报告 Fix round 自承未实机联调；仅有 `tsc --noEmit` PASS |

**总体规格符合度**：设计 §4–§8 与 brief Step 1–9 逻辑路径已覆盖；§7/§8 经 Fix round 闭合。手测证据为文档缺口，非功能缺口。

---

## Issues

### Critical（必须修）

无。

### Important（应当修）

无（前次两项已修复，见 Fix round 核对）。

**Fix round 核对摘要**

| 前次 Important | Fix round 行为 | 结论 |
|----------------|----------------|------|
| 排队不可删 | `onRemoveQueued` → `removeQueued` + 移除乐观 user 气泡 + `focusComposer` | ✅ |
| failed 不可重试 | `onRetryFailedQueue` → `markStatus(...,"queued")` + UI 同步；idle 时 `dequeueForSend` + `sendText` | ✅ |

### Minor（可选 / 文档）

1. **浏览器实机 E2E 未执行**  
   - 报告 Fix round 明确「未做浏览器 E2E / 实机点验」。  
   - **影响**：连发串行、停止后续发、取消/重试交互等仍依赖代码审 + `tsc`；合入前建议人工按 brief Step 9 五条勾选一次。  
   - **裁定**：不阻塞 Approved。

2. **出队间隙未再 `focusComposer`（§4.3 字面）**  
   - `settleAfterStream` drain 续发时不 focus，仅最终 idle 时 focus。  
   - `onStop` / 取消排队已 focus；主痛点已覆盖。可选在 deq 分支 `sendText` 前补一次。

3. **流式中主按钮仅为「停止」，无独立入队图标**  
   - 设计允许 Enter 入队；现行为可接受。

4. **命名**：brief `pumpQueue` 落地为 `settleAfterStream`——行为等价，文档可统一称谓。

---

## 专项核对（Fix round 新增）

| # | 核查项 | 结果 |
|---|--------|------|
| 1 | `removeQueued` import 且 `onRemoveQueued` 调用 | ✅ |
| 2 | queued UI「取消」仅 `queueStatus==="queued"` | ✅ |
| 3 | 取消后同步移除对应乐观 user 气泡 | ✅ `filter` by `queueLocalId` + `queueStatus==="queued"` |
| 4 | failed UI「重试」+ `onRetryFailedQueue` | ✅ `aria-label="重试发送"` |
| 5 | 重试 idle → 立即出队发送；busy → 保持 queued 等 settle | ✅ |
| 6 | failed 不堵后续队列 | ✅ `dequeueForSend` 只取 `status==="queued"` |
| 7 | CSS `.chat-queue-action` / `.is-retry` | ✅ `globals.css` |
| 8 | TypeScript | ✅ `npx tsc --noEmit` exit 0（复审查 2026-07-30） |

---

## Assessment

**Ready to merge?** **Approved**

**Reasoning：** Task 4 主路径（FIFO、Abort 停止并续发、supersede、sessionGen 防串会话、焦点、pending 解耦）实现质量高且与设计一致。前次 Important 缺口 §7（排队取消）与 §8（失败重试）已在 Fix round 以 `onRemoveQueued` / `onRetryFailedQueue` 及对应 UI 闭合；`tsc` 通过。浏览器实机清单仍为 Minor 文档项，建议合入前或合入后尽快人工点验 brief Step 9，但不影响本次 Approved 裁定。
