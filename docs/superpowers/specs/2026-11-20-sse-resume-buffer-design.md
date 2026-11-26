# SSE 断链续播（服务端缓冲）设计预留

> 状态：**预留 / 后期实现（未排期）**  
> 日期：2026-11-20  
> 裁定：方案 **A — 服务端缓冲续播**（非软续写、非整轮重试）  
> @author 赵振明

## 背景（现状）

- 前端 `postSse`（`fetch` + `ReadableStream`），**无**自动重连。
- 助手正文在 `message_end` 才落库；断网半截仅存在于浏览器。
- 「↻ 重试」= 基于上一 user **整轮重生成**，保留旧 assistant；**不是**从偏移续播。
- `turn_checkpointer` 只管 Turn 图节点，**不管** token/SSE 偏移。

## 目标（后期）

客户网络抖动导致 SSE 中断后：

1. 后端**可继续生成**（或至少已生成部分可回放）。
2. 前端重连后按 **字节/事件偏移** 只拉取未收到的后半段，界面上接在已显示半截之后。
3. 用户感知为「接着显示」，而非整段重来。

## 非目标（本期 / 预留阶段）

- 不实现代码、不改 API、不改表结构。
- 不做「软续写」（再问模型接着写）。
- 不替代现有整轮 `retry`（仍保留为产品能力）。

## 方案 A 骨架（实现时再细化）

### 核心思路

```
send 开启 turn_stream_id
  → 后端边生成边 append 事件到 Redis 缓冲（带 seq）
  → SSE 向客户端推送；客户端本地记 last_seq
客户端断联
  → 后端生成/缓冲不立刻取消（TTL / 完成条件）
重连 GET/POST resume?stream_id=&after_seq=
  → 从缓冲回放 after_seq 之后的事件
缓冲过期或无 stream → 回落提示「请重试」
```

### 待决问题（开工前必须拍板）

1. **生命周期**：客户端断开后后端是否继续烧 LLM？最长跑多久、谁付费？
2. **缓冲键**：`stream_id` 与 `conversation_id` / user 绑定与鉴权。
3. **与落库时机**：续播完成后才 `persist_assistant`，还是增量草稿？
4. **Plan-Execute / 工具调用中断**：卡在 tool / card 时能否续播。
5. **前端触发**：自动重连 vs 显式「继续」按钮；与「停止」如何区分。

### 风险

- 断联后继续生成 → 成本与闲置浪费。
- Redis 缓冲体积与 TTL；多实例下必须共享存储。
- 与现有「停止 = Abort」语义冲突，需明确「断网 ≠ 用户停止」。

## 关联代码（只读锚点）

| 位置 | 说明 |
|---|---|
| `web/src/lib/sse.ts` | `postSse`，无重连 |
| `web/src/app/chat/page.tsx` | `sendText` / `retryMessage` / `onStop` |
| `src/app/api/v1/messages.py` | `StreamingResponse` SSE |
| `src/app/modules/conversation/runtime.py` | 生成与落库 |

## 下一步（排期时）

1. 补全本 spec（生命周期 + API 契约 + 表/Redis 键）。
2. `writing-plans` 出 Task 计划。
3. 测试：断流 → resume → 正文连续；Abort 不误触发续播。
