# Final Review: 系统对话连续发送队列（Tasks 1–5）

**Verdict: Approve with nits**

**Reviewer:** Senior Code Reviewer（只读整特性）  
**时间:** 2026-07-30 15:06:16（东八区）  
**范围:** 仅 final pkg 所列 chat-queue 特性文件；未重跑全量套件（采信 controller：`test_dismiss_card` 3 passed、`chatSendQueue` 8/8、`tsc --noEmit` PASS）

---

## Strengths

1. **规格对齐扎实**：FIFO 上限 5、Abort 停止、半截「已停止」、`supersede_pending_card` 解除 42213、切会话 `sessionGen`+abort+清队列、选模/消息 retry 在 `busy` 时禁用，均能在代码中对上规格 §4–§8。
2. **前后端职责清晰**：后端只做卡片条件作废 + API；前端纯函数队列 + ChatPage 状态机；未引入服务端持久队列 / 并行 SSE / 强杀 LLM（符合非目标）。
3. **并发与切会话防护到位**：`sendQueueRef` / `streamPhaseRef` / `pendingCardRef` / `sessionGenRef` 避免闭包陈旧与跨会话泵队列；`settleAfterStream` 对 gen 失配直接 return。
4. **失败不堵队 + 可运维 UX**：失败标 `failed` 仍可出队后续；Fix round 补齐「取消排队 / 重试」与规格 §7–§8 一致。
5. **测试与文档有落地**：`cancel_pending_cards` + dismiss 幂等 + supersede；队列纯函数 8 测；API 规范 §10 / 42213 / dismiss-card 已同步；CHECKPOINT 已收口。

---

## Issues

### Critical

无。

### Important

1. **`ensureConversation` 与切会话竞态可能污染 `conversationId`**
   - **文件:** `web/src/app/chat/page.tsx`（`ensureConversation` + `sendText`）
   - **问题:** `sendText` 在 `await ensureConversation()` 之后用 `sessionGen` 早退，但 `ensureConversation` 内部已 `persistConversationId(cid)`。用户在「首条发送建会话」过程中点新对话/切会话时，空会话可能被写回已废弃的 `conv_*`，后续输入落到错误会话。
   - **建议:** `ensureConversation` 返回前校验 gen（或传入 `gen`）；若 gen 已变则不要 `persistConversationId`，必要时软删/忽略刚创建的空会话。

2. **`messages/send` 仍无会话归属校验，`supersede` 放大作废面**
   - **文件:** `src/app/api/v1/messages.py`（`send_message` vs `dismiss_card`）
   - **问题:** `dismiss-card` 校验 `conv.user_id`；`send_message` 仅 `conv is None` 即继续，且 `supersede_pending_card=true` 可作废该会话全部 pending 卡。归属缺口为既有问题，但本特性使「猜到 conversation_id 即可 cancel 卡」成本更低。
   - **建议:** 与 dismiss 对齐：非本人且非平台管理员 → 403；属 follow-up，不阻塞本特性功能验收，但上线前建议补。

### Minor

1. **`enqueue` 对空白串仍可入队**（Task3 台账）：`text.trim()` 后可为空；页面 `onSubmit` 有 `!text` 守卫，纯函数层仍脆。可加 `if (!text.trim())` 拒绝。
2. **出队间隙未 `focusComposer`**（Task4 台账 / 规格 §4.3「含出队间隙」）：`settleAfterStream` 仅在回 `idle` 时聚焦；`draining` 续发前不聚焦。可选增强。
3. **`sendQueue` 长期累积 `sent`/`failed`**：会话内从不裁剪已完成项，长会话数组膨胀；可在 `markStatus(...sent)` 后剔除或定期压缩。
4. **`cancel_pending_cards` 为读改写非单条 `UPDATE ... WHERE status='pending'`**：与规格风险表一致，竞态窗口可接受；生产可改为条件更新更稳。
5. **作废与落用户消息非同一事务**：`cancel_pending_cards` 先 `commit`，再插入 Message；取消成功但后续失败时卡已 cancelled、无新消息——可恢复，但非原子。
6. **独立 `dismiss-card` 无「只取消不发送」UI**：API 保留符合规格；产品若需要显式跳过卡入口，后续补。
7. **CHECKPOINT / 日志写「dismiss 单测 4 passed」**：现行 `tests/test_dismiss_card.py` 仅 3 用例；controller 证据亦为 3。文档漂移，应改为 3。
8. **浏览器 E2E 仍缺**（Task4 台账）：连发串行 / 停止续发 / 出卡后 supersede / 焦点，需人工硬刷新联调。
9. **Prior ledger**：dirty tree / sse `formatApiErrorText` 并行改动属过程噪声；本评审未将其升格为缺陷。

---

## Plan alignment

| 计划 Task | 规格项 | 结论 |
|---|---|---|
| Task 1 | `cancel_pending_cards` / `dismiss-card` / `supersede` / API 文档 / 单测 | ✅ 对齐；retry 不 supersede ✅ |
| Task 2 | `postSse` + `AbortSignal` | ✅ |
| Task 3 | `chatSendQueue` 上限 5 + 纯函数测 | ✅（空白入队为 nit） |
| Task 4 | 状态机 / 停止 / 排队 UI / 已跳过 / 焦点 / 切会话 / 删队 / 重试 | ✅ 主路径对齐；出队间隙焦点为 nit |
| Task 5 | CHECKPOINT + 规格「已落地」 | ✅（测数笔误为 nit） |

全局约束（单租户、无迁移、无服务端队列、端口约定文档侧）未见违反。

---

## Evidence (trusted, not re-run)

- `pytest tests/test_dismiss_card.py` → 3 passed  
- `chatSendQueue.test.ts` → 8/8  
- `web` `tsc --noEmit` → PASS  

---

## Verdict

**Approve with nits**

核心连续发送队列能力可验收合入（在完成人工联调清单的前提下）。无 Critical。两条 Important（建会话竞态写回 conversationId；send 归属与 supersede）建议在合并生产前跟进，但不否定 Tasks 1–5 相对规格/计划的完成度。Minor 可记入下一轮清理，不必挡本特性收口。
