# 系统对话过程可见（阶段 + 合成思考）设计

> 状态：已实现  
> 日期：2026-07-27  
> 作者：赵振明  

## 1. 要解决什么

系统对话界面需要类似豆包的过程可见体验：用户在等待最终回答时，能看到 **对话阶段推进**，以及可折叠的 **思考过程**（合成人话叙述）。

现状：

- API 已声明可选 `tool_call` / `skill_call`，技能 FC 路径会 yield `tool_call`，但前端对话页未渲染过程区。
- Plan-Execute 主路径为 `graph.ainvoke` 整图返回后再吐 `content_delta`，无法边跑边报阶段。

## 2. 产品裁定（已确认）

| 项 | 裁定 |
|---|---|
| 形态 | **阶段胶囊 + 可折叠思考区**（方案 C） |
| 思考区内容 | **后端合成人话**（非模型原生 reasoning token、非原始 plan JSON） |
| 持久化 | **仅本轮流式可见**；不落库、历史加载不恢复 |
| 实现路线 | 轻量 SSE 过程事件 + 前端过程面板；Plan-Execute 改为可流式上报 |

## 3. 不做的事

- 不落库过程字段（`messages.meta` / 新表均不存）
- 不向用户展示工具 `arguments`、plan JSON、完整观测正文、密钥
- 不依赖上游模型原生 thinking/reasoning（本迭代不做；日后可另开规格）
- 不引入 Temporal / 外部可观测平台 / OpenIM
- 不改工作流「仅结果」进度策略（PRD 工作流进度推送范围外）
- 不做过程区复制/导出/分享；不加多租户

## 4. SSE 事件与载荷

在 `API接口规范.md` §10.1 增补（实现时同步文档）：

| event | 用途 | 载荷 |
|---|---|---|
| `stage` | 阶段胶囊 | `{ "id": "<stage_id>", "label": "<中文标签>", "status": "running" \| "done" \| "error" }` |
| `thought_delta` | 可折叠思考区叙述增量 | `{ "delta": "<合成人话片段>" }` |

### 4.1 阶段枚举

固定集合（可缺省跳过未经历阶段）：

| id | 默认 label |
|---|---|
| `understand` | 理解问题 |
| `plan` | 规划中 |
| `retrieve` | 检索知识库 |
| `skill` | 调用技能 |
| `respond` | 整理回答 |

闲聊直答可只走 `understand` + `respond`。

### 4.2 顺序约定

1. 进入阶段：`stage` 且 `status=running`，可穿插若干 `thought_delta`。
2. 离开阶段：同 `id` 再推 `status=done`（失败则 `error`）。
3. 最终答案 **仅** 使用 `content_delta`，与思考区隔离。
4. 保留现有 `tool_call` / `skill_call` / `citation` / `card` / `message_end` 语义；用户默认 UI 以 `stage` + `thought_delta` 为主，不展开工具参数。
5. `message_end` 后前端折叠过程区；过程数据仅留在本轮内存，下轮发送时丢弃旧轮过程态。

### 4.3 安全

`thought_delta` 只含合成人话；技能可用 **展示名**；禁止 plan JSON、原始 arguments、密钥、完整观测正文。

## 5. 后端组件与数据流

```
messages/send（及 card-action / retry 同源 SSE）
        │
        ▼
runtime stream_* 路径
        │  yield stage / thought_delta / content_delta / …
        ▼
process_narration（新建，极薄）
        │  stage_id → label；进入/完成/失败固定模板
        ▼
前端 ProcessPanel（内存态，不落库）
```

### 5.1 合成器

新建如 `src/app/modules/conversation/process_narration.py`：

- 输入：阶段 id、动作（enter/done/error）、可选上下文（技能展示名等）
- 输出：`stage` 载荷与/或一句 `thought_delta` 文案
- 单测断言：模板稳定；不含 JSON 结构特征与 `arguments` 字样滥用

### 5.2 路径覆盖

| 路径 | 行为 |
|---|---|
| Plan-Execute | 见 §5.3：边执行边推 |
| legacy 技能 FC | `understand` → 工具前 `skill` + 叙述；无工具则 `respond`；可继续 yield `tool_call`（UI 默认不依赖） |
| 闲聊 / 直答 | `understand` → `respond` + 短叙述 |
| 澄清卡 / ask_user | 出卡前将当前阶段标 `done`，`thought_delta` 如「需要你补充信息」；再 `card` + `message_end` |

过程事件 **不写入** 助手消息持久化字段。

### 5.3 Plan-Execute 流式边界

现状：`run_plan_execute` → `graph.ainvoke` → 一次性返回 → `_stream_plan_execute` 再吐答案。

本迭代：

1. `run_agent_turn` / `_stream_plan_execute` 改为 **异步迭代器**（或等价回调队列），按节点/步骤产出过程事件，最后产出答案与 citations / deferred_card。
2. 对内优先 `graph.astream(..., stream_mode="updates")`（或等价），由 runtime 映射：
   - planner 开始/结束 → `plan`
   - `rag_search` → `retrieve`
   - `execute_skill` / `call_agent` → `skill`（叙述用展示名）
   - respond / aggregate → `respond`
3. **不改** Planner/Execute 业务语义；不把观测全文推前端。

### 5.4 失败与降级

- 步骤失败：对应 `stage status=error` + 一句叙述，再按现有错误/拒展逻辑（含 D14）。
- Mock LLM：按事件序列断言即可。

## 6. 前端过程面板

挂载：`web/src/app/chat/page.tsx`（建议抽 `ProcessPanel`）。

### 6.1 结构

每轮助手回复 = **过程区（可选）** + **正文**（Markdown）+ 引用/卡片（现有）。

过程区：

1. 阶段胶囊行（仅渲染已出现的阶段；样式区分 running / done / error）
2. 可折叠「思考过程」：`thought_delta` 拼接的 **纯文本**（不做 Markdown）

### 6.2 交互

| 时机 | 行为 |
|---|---|
| 首个过程事件 | 挂载本轮过程区；折叠块默认 **展开** |
| 流式中 | 更新胶囊与叙述；随 stream 滚底 |
| `content_delta` | 正文在下方正常输出；过程区可仍展开 |
| `message_end` | 思考块 **自动收起** |
| 刷新 / 切会话 / 加载历史 | **不恢复**过程区 |
| 用户点击标题 | 可手动展开/收起（本轮内存仍在） |
| 新一轮发送 / 重试 / card-action | 新过程区挂新助手条；旧轮过程态丢弃（仅保留当前 busy 一轮） |

### 6.3 明确不做

- 默认不渲染 `tool_call` 原始参数
- 不改空态/侧栏主视觉；样式贴合现有 `msg-*`

## 7. 测试要点

1. 叙述合成器：固定文案；无 JSON/arguments/密钥样泄漏
2. Plan-Execute 流式：事件顺序含 stage/thought → content_delta → message_end；过程不入 `meta`
3. legacy FC：有工具时出现 `skill`；ask_user 出卡回归
4. 闲聊：至少 understand + respond
5. D14 / 错误：error 阶段或等价 + 现有拒展回归
6. 回归：上下文分栏、澄清卡、citation、card-action
7. 前端：累积与折叠；历史无过程区；思考纯文本 vs 正文 Markdown 分离

## 8. 验收（说人话）

- 走检索或技能的问题：能看到阶段推进 + 可折叠人话思考，再出正式回答
- 刷新后只剩回答，无上次思考过程
- 过程区无工具参数或 plan JSON
- 提问卡、RAG 无引用拒展等旧行为正常

## 9. 实现顺序（计划阶段细化）

1. `process_narration` + 单测
2. API 文档 §10.1 增补事件
3. Plan-Execute / `run_agent_turn` 流式出口 + `_stream_plan_execute` 对接
4. legacy FC / 闲聊路径补 stage/thought
5. 前端 `ProcessPanel` + SSE 处理
6. 回归测试 + 更新 `CHECKPOINT.md`

## 10. 与现有文档关系

- 对齐：`API接口规范.md` v0.7.4+（扩展 SSE，不破坏既有事件）
- 不冲突：PRD 工作流「进度仅结果」不在本规格范围；对话侧 API 已允许可选进度事件
- 白名单外史料不作依据
