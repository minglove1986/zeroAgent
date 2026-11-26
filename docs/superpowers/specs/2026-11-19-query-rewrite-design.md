# 对话 Query Rewrite（上下文改写）设计

> 状态：实现中  
> 日期：2026-11-19  
> @author 赵振明

## 背景

Plan-Execute 的 Planner 与技能 ReAct **不注入多轮短记忆**，只吃本轮用户句。  
追问如「农历」「我是说，当前农历初几」在字面不自洽或依赖上文时，易误路由到 KB，或技能拿不到完整任务语义。

农历换算能力已补（`datetime_ops.action=lunar`）；本设计解决的是 **入口消歧**，不是把全历史灌进 Planner。

## 目标

1. 对依赖上文的本轮话做 **contextual query rewrite**，供 Intent / Planner / KB / 技能共用。  
2. 用户可见与短记忆仍保留 **原句**。  
3. **规则为主、漏斗为辅**；全链路最多改写 1 次；失败回退原句。

## 非目标

- 不向 Planner / skill_react 注入完整 20 轮历史。  
- 不做检索侧 HyDE / 多查询扩展。  
- 不改 L2 词表治理模型。  
- 不含「技能空答案兜底」（另项）。

## 方案

### 插入点与流程

入口仍是 `intent` 节点。`stream_mock_reply` **进图前已** `append_short_memory(user)`，故读短记忆必须 **`[:-1]`**。

```
原句
  → 历史 = short_memory[:-1]
  → L0 规则命中且有历史？
        是 → rewrite 一次 → 有效句跑漏斗
        否 → 原句跑漏斗
              → 若未改写过，且（低置信 / route_clarify / fallback chitchat）且有历史
                    → rewrite 一次 → 有效句重跑漏斗（不再第三次）
  → handoff / KB / 技能用有效句
  → 短记忆已写入的是原句（进图前）；assistant 落库照旧
```

`_stream_via_turn_graph` handoff 必须传 **`final_state["user_content"]`（有效句）**，禁止继续传闭包原始 `user_content`。

### 状态字段（TurnState）

| 字段 | 含义 |
|---|---|
| `user_content` | **有效问句** |
| `user_content_original` | 用户原句 |
| `rewrite` | `{applied, reason, original, rewritten, trigger}` |

### 门控

**L0 规则（主）**：有历史且命中——过短（≤4）、指代/追问词、保守省略句。

**漏斗辅触发（仅 L0 未改写时）**：`confidence < tau_low`，或 `intent == route_clarify`，或 `reason` 含 `fallback_chitchat`。

**禁止**：仅凭低置信替代 L0；全链路改写超过 1 次。

### LLM 改写

- 近邻最多 3 条（user/assistant），单条截断 200 字  
- 输出一行独立中文问句  
- `MOCK_EXTERNAL`：确定性模板，便于单测  
- 异常/空 → 回退原句

## 验收场景

1. 先答公历，再问「农历」→ L0 改写 → 时间技能/农历答，非无关 KB。  
2. 「今天农历初几」完整句 → 不改写。  
3. 改写失败 → 原句继续。  
4. handoff 到 Plan-Execute 的是有效句。
