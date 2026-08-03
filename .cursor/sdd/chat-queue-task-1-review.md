# Task 1 审查：dismiss-card + supersede_pending_card

**审查时间：** 2026-07-30 14:44:00（东八区）  
**审查范围：** working-tree-pre-task → working-tree-post-task（无 commit）  
**依据：** `chat-queue-task-1-brief.md`、`chat-queue-task-1-report.md`、`chat-queue-task-1-review-pkg.md`

---

## Spec Compliance

**结论：Compliant（Task 1 核心需求已满足）**

| 要求项 | 结论 |
|---|---|
| `cancel_pending_cards(db, *, conversation_id, card_id=None) -> list[str]` | ✅ 签名与 brief 一致；pending→cancelled、写入 result、按需 commit |
| `POST /api/v1/messages/dismiss-card` → `{ dismissed_ids }` | ✅ 已实现；本人或平台管理员；404/403 与 brief 一致 |
| `MessageSend.supersede_pending_card: bool = False` | ✅ 已加入 |
| `send_message`：有必填 pending 卡时，未 supersede 仍 42213；supersede 先作废再继续 | ✅ 与 brief 代码块一致 |
| `retry` 路径不支持 supersede | ✅ `retry_message` 仍仅 `has_pending_required_card` → 42213，无 supersede 分支 |
| 无 DB migration（复用 `cancelled`） | ✅ |
| 无前端改动 | ✅ |
| TDD：先红后绿 | ✅ 报告可信（2 FAIL → 实现后 4 PASS） |
| `tests/test_dismiss_card.py` 三用例 | ✅ 与 brief 步骤 1 对齐 |
| API 规范 §10：`dismiss-card`、`supersede_pending_card`、42213 说明 | ✅ 已更新（含 §10.1.1、v0.8.3） |
| 注释 `@author 赵振明` + 东八区时间 | ✅ 新增函数/类已补 |
| 全局约束（单租户、无服务端队列等） | ✅ 未引入违规能力 |

**范围说明：** brief 限定在 `has_pending_required_card` 附近增函数及 messages 路由改动；实现报告亦仅声称上述增量。但 review diff 中 **`runtime.py` / `messages.py` / API 规范** 含大量与 Task 1 无关的并行改动（路由解析、LLM Gateway、软删会话、§12 管理等）。这些**不改变** Task 1 接口合规结论，但属于交付物隔离问题（见 Important #1）。

---

## Strengths

1. **TDD 证据完整**：RED 阶段准确暴露「路由不存在 / supersede 未生效」；GREEN 覆盖既有 `test_send_blocked_when_pending_required_card`，回归面合理。
2. **与 brief 实现高度一致**：`cancel_pending_cards` 逻辑、42213 分支替换、`dismiss-card` 权限模型均按 spec 片段落地，无擅自改签名。
3. **幂等与语义清晰**：二次 `dismiss-card` 返回空数组有测试；`get_conversation` 的 `pending_cards` 仅查 `status=pending`，作废后列表为空的行为与测试断言一致。
4. **retry 约束遵守**：明确未向 retry 引入 supersede，与 brief「本期不改 retry」及 API 文档说明一致。
5. **dismiss 路径权限更严**：`dismiss-card` 校验会话归属，优于 send 路径（与 brief 样例一致；send 沿用改前行为，实现者在 self-review 中已说明）。

---

## Issues

### Critical

无。Task 1 规定的三条解锁路径（42213 保持 / supersede / dismiss-card）行为与测试、文档一致。

### Important

1. **交付 diff 与 Task 1 范围严重掺混**  
   review package 中 `runtime.py` 数百行变更（RouteResolver、stage 事件、memory/compress 调度、LLM gateway 等）、`messages.py` 的软删会话与 `_resolve_model_ids`、`API接口规范.md` 的 §12 整段，均**不在** Task 1 brief 内。实现报告仅列「新增 `cancel_pending_cards`」，与真实 diff 不符，增加 task-scoped 验收与后续 cherry-pick 难度。  
   **建议：** 提交前按 Task 拆分变更集，或至少在报告中如实列出并行任务边界。

2. **`cancel_pending_cards` 内部独立 `commit`**  
   supersede 路径：先 `cancel_pending_cards` commit，再 `send_message` 写 user Message 并再次 commit。若后者失败，卡片已作废但新消息未入库，会话处于「卡已 dismiss、无新轮次」中间态。brief 样例亦如此，属可接受权衡，但 Task 2 前端队列需知悉该边界。

### Minor

1. **`dismiss-card` 与 `result.reason` 语义**  
   dismiss 与 supersede 均写 `reason: "user_supersede"`（brief 样例同源）。功能无影响；若后续审计需区分来源，可改为 `user_dismiss` / `user_supersede`（非本期阻塞）。

2. **测试未断言 DB 层 cancelled 状态**  
   用例通过 `pending_cards == []` 间接验证，未查 `MessageCard.status` / `result` JSON。对 brief 给定用例已足够；加强断言可提升回归信度。

3. **`tests/test_dismiss_card.py` 中 `_parse_sse` 未使用**  
   复制 fixture 模式时遗留 dead code，可删。

4. **软删会话（并行改动）与 dismiss 不一致**  
   同 diff 新增 `get_conversation` 对 `status=deleted` 返回 404，但 `dismiss-card` 仍仅判 `conv is None`。非 Task 1 brief 要求，属并行改动的一致性问题。

---

## Assessment

**Task quality: Approved**

Task 1 功能门禁通过：`cancel_pending_cards`、`dismiss-card`、`supersede_pending_card` 与 42213/retry/文档/TDD 均符合 brief 与全局约束；4 项相关测试通过可信。

**附带条件（非阻塞本 Task 验收）：** 工作树 diff 掺入大量非 Task 1 变更，应在后续 commit/PR 前拆分或文档化，避免将 Task 1 与路由/Gateway/软删等改动混为一次交付。

---

## 审查清单（Task 1 专用）

| 检查项 | 结果 |
|---|---|
| 42213 未 supersede 时仍返回 | ✅ |
| supersede 后 send 200 且 pending 清空 | ✅ |
| dismiss-card 幂等 | ✅ |
| retry 无 supersede | ✅ |
| 无 migration | ✅ |
| API §10 同步 | ✅ |
| 单租户 / 无服务端队列 | ✅ |
