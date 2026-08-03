# Task 4 报告：ChatPage 队列状态机 + 停止 + supersede + 焦点

**完成时间（东八区）**：2026-07-30 14:55:09  
**作者**：赵振明  
**状态**：✅ 已完成

## 变更摘要

| 文件 | 操作 |
|------|------|
| `web/src/app/chat/page.tsx` | 队列状态机、Abort 停止、supersede、焦点恢复、UI |
| `web/src/app/globals.css` | `.chat-queue-tag` / `.chat-card-skipped` / `.chat-stopped-hint` / `.send-btn-stop` |

**未 commit**（按约束）。

## 实现要点

1. **状态**：`streamPhase`（`idle|streaming|stopping|draining`）+ `sendQueue`；`busy = streamPhase !== "idle"`。
2. **发送**：`messages/send` 始终带 `supersede_pending_card: true`；`AbortController` 经 `postSse(..., { signal })`。
3. **入队**：流式中 Enter/提交走 `enqueue`（上限 5，仅计 `queued`）；用户气泡标「排队中」。
4. **停止**：主按钮切「停止」→ `abort`；`AbortError` 保留半截助手并标「已停止」，**不** toast；`settleAfterStream` 出队续发。
5. **卡片**：有 pending 时仍可输入；发送/出队前本地灰显「已跳过」；隐藏提交区。
6. **焦点**：入队/直发清空后、`idle` 回落、切会话/新对话、卡片提交 settle 后 `focusComposer()`。
7. **切会话**：`resetStreamSession()`（`sessionGenRef++` + abort + `clearQueue`），允许流式中切换；`streaming` 禁用选模与 retry。

## 手动清单（自检）

| # | 场景 | 结论 |
|---|------|------|
| 1 | 流式中连发 3 条 → 串行 | ✅ 代码路径具备（入队 + settle 出队） |
| 2 | 停止 → 队首立刻发；焦点输入框 | ✅ |
| 3 | 出卡后直接发字 → 已跳过 + 新回合 | ✅ supersede + 本地 skipped |
| 4 | 发送后无需点击即可键入 | ✅ focusComposer |
| 5 | 队列满 5 提示 | ✅ |

> 未做浏览器实机联调；逻辑与设计对齐，待人工点验。

## 验证

| 项 | 命令 | 结果 |
|----|------|------|
| 类型检查 | `cd web; npx tsc --noEmit` | ✅ PASS（exit 0） |

## 风险 / 关注点

1. **仅客户端 Abort**：服务端/LiteLLM 可能短暂继续生成；半截短记忆可接受（设计已裁定）。
2. **刷新丢队列**：本地 FIFO 不持久化。
3. **出队与出卡竞态**：出队前本地 skip + send supersede；依赖服务端条件更新 `pending→cancelled`。
4. **sessionGen**：切会话 abort 后旧流 `finally` 不再泵队列，避免串会话。

## Git

按约束：**未 commit**。

## Fix round

**时间（东八区）**：2026-07-30 15:01:28  
**作者**：赵振明  
**针对**：Task 4 review — 排队可删（§7）+ 失败可重试（§8）

### 变更

| 文件 | 改动 |
|------|------|
| `web/src/app/chat/page.tsx` | 引入 `removeQueued`；新增 `onRemoveQueued` / `onRetryFailedQueue`；排队气泡「取消」、失败气泡「重试」 |
| `web/src/app/globals.css` | `.chat-queue-action` / `.is-retry` 样式 |

### 行为

1. **取消排队**：仅 `queueStatus===queued` 显示「取消」→ `removeQueued` 更新 `sendQueue`，并从消息流移除对应乐观用户气泡。
2. **失败重试**：`failed` 显示「重试」→ `markStatus(..., "queued")` 同步气泡为「排队中」；若 `idle` 则立即 `dequeueForSend` 泵送；若仍在流式则保持 queued，由后续 `settleAfterStream` 出队。失败项不堵后续队列（原 settle 逻辑已跳过非 queued）。

### 验证

| 项 | 结果 |
|----|------|
| `cd web; npx tsc --noEmit` | ✅ PASS（exit 0） |
| Grep `removeQueued` 使用 | ✅ `page.tsx` import + `onRemoveQueued` |
| 失败重试 UI | ✅ `aria-label="重试发送"` + `onRetryFailedQueue` |

> 浏览器 E2E / 实机点验：未做（由 controller 记入手动清单）。

按约束：**未 commit**。

## Final-fix

**ʱ�䣨��������**��2026-07-30 15:09:37  
**����**��������  
**���**��final chat-queue review �� ensureConversation ��̬ + messages/send ����Ȩ

### ���

| �ļ� | �Ķ� |
|------|------|
| web/src/app/chat/page.tsx | ensureConversation(gen)��persist ǰ�� sessionGenRef.current !== gen ���� AbortError����д conversationId/storage��sendText ���� gen |
| src/app/api/v1/messages.py | send_message ���� dismiss_card���������ҷ�ƽ̨����Ա �� 403/40301���� supersede/cancel ֮ǰ |
| 	ests/test_dismiss_card.py | ���� 	est_send_forbidden_before_supersede_for_stranger |
| docs/superpowers/CHECKPOINT.md | ��ʷ��dismiss 4 passed������Ϊ 3������ final-fix ��Ϊ 4 passed |

### ��֤

| �� | ��� |
|----|------|
| pytest tests/test_dismiss_card.py -q | ? 4 passed��7.13s��1 warning �޹أ� |
| cd web; npx tsc --noEmit | ? PASS��exit 0�� |

��Լ����**δ commit**��
