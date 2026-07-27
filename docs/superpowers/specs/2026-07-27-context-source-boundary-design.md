# 对话上下文分栏注入（来源边界）设计

> 状态：已实现  

> 日期：2026-07-27  
> 作者：赵振明  

## 1. 要解决什么

两件事叠在一起：

1. **新路径丢了记忆**：Plan-Execute（`AGENT_RUNTIME=langgraph`）里把 `memory_access` 丢掉了，长期记忆/偏好白积累。
2. **上下文糊成一锅**：登录身份、记忆、聊天记录、知识库检索结果没有分栏，模型容易把资料里的第三人当成「当前用户」（例如把简历里的「尹庆为」当称呼）。

PRD 15.7 已规定：记忆在**每次对话请求开始时**注入 System Prompt。本设计对齐该决策，并补上「分栏 + 来源边界」。

## 2. 不做的事

- 不改记忆抽取/提升逻辑（Celery、向量摘要等）
- 不做输出事后校验扫人名
- 不引入多租户、外部画像服务
- 不把「别叫某某」写成一长串症状补丁

## 3. 方案概要

每轮进模型前，组装**带标签的上下文块**（可空则省略该块）：

| 块 | 来源 | 模型应如何用 |
|---|---|---|
| 当前用户身份 | `users` 表（`name`、`username` 等） | 唯一代表「你」；无姓名则写「姓名未提供」 |
| 用户记忆 | `user_memories`，受 Agent `memory_access` 过滤 | 偏好/事实/摘要，可用于称呼与语气 |
| 本会话短记忆 | Redis 短期记忆 | 对话上下文；其中出现的人名≠换用户 |
| 检索/技能观察 | RAG、技能返回、citation | **第三人/文档资料**，禁止当成当前用户身份 |

另附**一条通用边界规则**（替换现有 `_RESPOND_SYSTEM` / `_IDENTITY_GUARD` 里的症状文案）：

- 称呼与「你是谁」只认「身份块 + 记忆块」
- 短记忆与检索块里的人名、经历、合同当事人，一律当第三方或文档内容
- 用户追问「你为什么叫我 XX / 资料从哪来」时，说明可能来自会话或检索混淆，并澄清不确定其身份（除非记忆/身份块已写明）

## 4. 组件与数据流

```
stream_mock_reply / _stream_plan_execute
        │
        ▼
build_turn_context_blocks(...)   ← 新建（conversation 或 memory 模块）
        │  读 identity / memory / short / boundary 文本
        ▼
run_plan_execute / respond / aggregate / legacy LLM
        │
        ▼  （若本轮有 RAG）
观察结果写入 messages 时，前缀标注「【知识库检索·第三人资料】」
```

### 4.1 `build_turn_context_blocks`

输入：`db`、`user_id`、`conversation_id`、`memory_access`  
输出：结构化 dict 或已拼好的 system 段列表，例如：

```text
【当前用户身份】
姓名：张三
账号：zhangsan

【用户记忆】
## 偏好
- reply_style: 简洁
## 事实
- ...

【本会话上下文】
（短记忆摘要或近几轮，沿用现有 load_short_memory）

【来源边界】
（固定规则短文，见 §3）
```

`memory_access=none` 时跳过记忆块；短记忆仍可注入（会话连续性）。身份块始终尽量注入（查不到用户则「身份未知」）。

### 4.2 接入点

| 路径 | 改动 |
|---|---|
| `_stream_plan_execute` | **禁止** `_ = memory_access`；调用 `build_turn_context_blocks`，传入 `run_agent_turn` / 图状态 |
| `plan_execute` 的 plan / respond / aggregate | System 使用身份+记忆+边界；用户句与短记忆分 role；技能/RAG 观察带「第三人资料」前缀 |
| legacy `_stream_skill_fc` / 闲聊 LLM | 复用同一 `build_turn_context_blocks`，删掉或收窄 `_IDENTITY_GUARD` 为边界规则一段 |
| 记忆写入 | 本迭代仅保证：抽取逻辑不把「检索到的第三人姓名」自动写成「用户叫 XX」（若现有抽取已只看用户原话，则不动；若测出误写再加闸） |

### 4.3 登录身份字段

以 `users.name` 为准；可选附带 `username`、`position`。  
**禁止**从知识库或短记忆推断姓名填入身份块。

## 5. 错误与降级

- 用户行不存在：身份块写「姓名未提供」，照常对话
- Redis 短记忆空：省略或空块
- `memory_access=none`：不注入记忆块，边界规则仍在
- Mock LLM：仍按现有规则返回，单测断言「组装出的 system 含记忆/身份标签」即可

## 6. 测试要点

1. Plan-Execute 路径在 `memory_access=all` 且库内有 preference 时，传给模型的 system **包含**该 preference 文案  
2. `memory_access=none` 时 system **不含**用户记忆块  
3. 身份块含 `users.name`，不因短记忆里出现「尹庆为」而改成尹庆为  
4. RAG 观察字符串带第三人资料标注（单元测拼接函数即可）  
5. 澄清卡/元追问热修回归仍通过  

## 7. 验收（说人话）

- 新开对话说「你好」：用登录名或中性称呼，不拿简历里的人当你  
- 有偏好记忆时：回复风格能体现（例如偏好简洁则不啰嗦）——至少 system 里看得见记忆  
- 追问资料来源：不当查库卡；能说明可能是会话/检索混淆  

## 8. 实现顺序（计划阶段细化）

1. 抽 `build_turn_context_blocks` + 单测  
2. 接通 Plan-Execute（修掉丢弃 `memory_access`）  
3. 接通 legacy，统一边界文案  
4. RAG/技能观察加前缀  
5. 更新 CHECKPOINT  
