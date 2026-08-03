# 系统对话连续发送队列设计

> 状态：已落地  

> 日期：2026-07-30  
> 作者：赵振明  
> 对齐：方案 A（前端 FIFO 队列 + 停止生成 + 发送作废 pending 卡）；库表 `message_cards.status` 已含 `cancelled`

## 1. 目标

1. 流式生成中仍可输入并发送：消息进入**本会话 FIFO 队列**，当前 SSE 结束后自动串行发出。  
2. 提供**停止生成**；停止后若队列非空，立即发送队首。  
3. 用户新发送（含队首真正发出）时，若存在未完成必填交互卡，**服务端作废**（`cancelled`），解除 42213。  
4. 每次发送动作完成后（入队或直发清空输入后），**焦点回到输入框**，无需再次点击即可继续输入。  

## 2. 非目标

- 服务端持久化消息队列 / 跨端同步排队。  
- 同会话并行多路 SSE。  
- 停止时服务端强杀 LiteLLM 生成（本期仅 Abort 客户端流）。  
- 刷新页面后恢复本地未发出队列（可接受丢失）。  

## 3. 已确认裁定

| 项 | 裁定 |
|---|---|
| 交互模型 | **C**：默认排队 + 可停止；不默认打断当前流 |
| 有 pending 卡时发新消息 | **作废卡片**后发送/入队（完整能力，非仅前端拦截） |
| 实现路径 | **方案 A**：前端队列 + `dismiss-card` / `supersede_pending_card` |
| 队列上限 | **5** |
| 停止后半截回复 | 保留气泡，标注「已停止」 |
| 焦点 | 发送/入队清空输入后 `textarea.focus()`；一轮流结束准备继续输入时亦聚焦 |

## 4. 前端队列状态机

单会话状态：`idle` | `streaming` | `stopping` | `draining`。

队列项：`{ localId, text, status: queued | sending | sent | failed }`。

### 4.1 发送入口

1. 用户提交非空文本 → 立即追加用户气泡；清空输入；**聚焦输入框**。  
2. 若存在本地 `pendingCard` → 先 `dismiss-card`（或依赖 send 的 `supersede_pending_card`）→ UI 卡灰显「已跳过」。  
3. 若当前为 `streaming` / `stopping` / `draining`：  
   - 队列未满 → `status=queued`，标签「排队中」；  
   - 已满 5 → 提示错误，撤回本条入队（或标 failed 并允许删除）。  
4. 若 `idle` → 直接进入 `streaming` 调用 `messages/send`（带 `supersede_pending_card: true`）。  

### 4.2 流结束 / 停止后续

- SSE 正常结束或失败结束 → 若队列非空：`draining` → 取队首 `sending` → send；否则 `idle` 并**聚焦输入框**。  
- 用户点「停止」→ `AbortController.abort()` → `stopping` → 当前 assistant 标「已停止」→ 同「流结束」出队逻辑。  
- 切会话 / 新对话 / 删当前会话：abort + 清空队列。  

### 4.3 焦点规则（强制）

| 时机 | 行为 |
|---|---|
| 用户点发送或 Enter 入队/直发后 | `requestAnimationFrame` / `setTimeout(0)` 后 `textareaRef.focus()` |
| 一轮 SSE 结束且回到可输入（含出队间隙） | 再次 focus，避免焦点留在「停止」按钮上 |
| 卡片提交成功后恢复可输入 | focus 输入框 |
| 输入框因校验禁用时 | 不抢焦点 |

实现注意：流式中频繁 `setState` 不应抢焦点；仅在「用户主动发送」与「进入可继续输入」两个边界聚焦。

## 5. 后端：卡片作废

库表 `message_cards.status` 已含 `cancelled`，**无需改表**。

### 5.1 `POST /api/v1/messages/dismiss-card`

请求：

```json
{
  "conversation_id": "conv_xxx",
  "card_id": "crd_xxx"
}
```

- `card_id` 省略：作废该会话下全部 `pending` 卡。  
- 校验会话归属当前用户。  
- 目标卡 `pending` → `cancelled`；`submitted_at=now`；`result={"dismissed":true,"reason":"user_supersede"}`。  
- 已是 `submitted` / `expired` / `cancelled`：跳过，整体仍 200。  
- 响应：`{ "dismissed_ids": ["..."] }`。  

### 5.2 `messages/send` 扩展

`MessageSend` 增加可选：

```json
{ "supersede_pending_card": true }
```

- 为 `true` 时：在落用户消息前原子将本会话 `pending` 卡标 `cancelled`，**不再返回 42213**。  
- 为 `false`/缺省：行为不变，仍有 pending 必填卡则 42213。  

独立 `dismiss-card` 保留，供「只取消不发送」与前端显式编排。

### 5.3 与 card-action

用户点卡片提交仍走原 `card-action`；与队列无关。作废后的卡不可再 submitted（按现有状态校验）。

## 6. SSE Abort

- `postSse(..., { signal?: AbortSignal })`：`fetch` 传入 signal。  
- ChatPage 持有 `abortRef`；streaming 时 UI 显示「停止」替代禁用发送。  
- 客户端 Abort 后服务端可能仍短暂生成：不推前端；下一轮以已提交 DB/短记忆为准。  

## 7. UI 要点

- 流式中：输入可编辑；主按钮为「停止」；仍可用 Enter 入队（或单独发送图标入队）。  
- 排队气泡：「排队中」；仅 `queued` 可删除出队。  
- 作废卡：灰显「已跳过」，隐藏提交区。  
- `streaming` 时禁用：切换模型、消息 retry、切会话（或切会话前先 abort+清队列——**推荐切会话前 abort+清队列并允许切换**）。  
  - 裁定：**允许切会话**，离开前 abort + 清空本会话队列。  
- 选模：`streaming` 时禁用，避免双流语义混乱。  

## 8. 边界表

| 场景 | 行为 |
|---|---|
| 流式中连发 3 条 | 1 条在飞，2 条排队；串行回复 |
| 停止后队列非空 | 立刻发队首 |
| 有卡 + 发新消息 | supersede/dismiss → 发送或入队 |
| 流式中途又出现 card | 本轮结束；出队前 supersede 该卡再发下一条 |
| 发送失败 | 该项 `failed`，不堵死后续；可重试 |
| 刷新 | 本地队列丢失；pending 以服务端为准 |
| 队列满 | 拒绝入队并提示 |

## 9. 文档与测试

- 更新 `docs/01-产品需求/API接口规范.md`：`dismiss-card`、`supersede_pending_card`、42213 说明。  
- 后端单测：dismiss 幂等；supersede+send；无卡 send 不变。  
- 前端：队列纯函数（入队/出队/满员/停止后续发）；focus 在发送后被调用（可测 mock）。  
- 手动：连发串行；停止后续发；有卡直接发送变「已跳过」；发送后无需点击即可继续键入。  

## 10. 风险

| 风险 | 应对 |
|---|---|
| Abort 后服务端仍写短记忆半截 | 可接受；压缩/截断兜底；后续可加 run_id 取消 |
| dismiss 与 card-action 竞态 | dismiss/supersede 用条件更新 `WHERE status='pending'` |
| 焦点被按钮抢走 | 停止/发送后显式 focus textarea |
| 作废卡导致技能上下文缺答 | 产品选择；新用户消息开启新意图，旧 ask_user 作废 |

## 11. 实现顺序建议

1. API：`dismiss-card` + `supersede_pending_card` + 单测  
2. `postSse` 支持 AbortSignal  
3. Chat 队列状态机 + 停止按钮 + 出队  
4. 焦点恢复 + 卡片「已跳过」UI  
5. API 文档与 CHECKPOINT  
