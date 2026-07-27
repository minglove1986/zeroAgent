# Agent LangGraph 运行时：Plan-Execute + ReAct + 文档理解（设计）

> **日期**：2026-07-27 08:58:44（东八区）  
> **状态**：已批准（2026-07-27；方案 B；实现计划见 `docs/superpowers/plans/2026-07-27-agent-langgraph-runtime.md`）  
> **范围裁定**：**方案 B**（用户确认）——主 Agent **Plan-and-Execute 大循环 + 技能内 ReAct 小循环** 与「文档理解」一并落地；LLM 经 **LangChain → LiteLLM Proxy**。  
> **权威对齐**：PRD 场景 4.2；D1/D18/D33；工具挂技能；Agent 不直调原子工具；单租户；D14 citation；Langfuse 自托管。

## 0. 现状缺口（本刀要补齐）

| PRD | 现网 | 本刀 |
|---|---|---|
| LangGraph | ❌ | ✅ 主图 + 文档子图 |
| Plan-Execute 大循环 | ❌ | ✅ Planner → 逐步 Execute → Aggregate |
| ReAct 小循环（技能内） | ❌（仅扁平 FC） | ✅ 每步选中技能后，仅该技能工具 ReAct |
| LangChain 调模型 | ❌ httpx | ✅ `lc_chat.get_chat_model()` |
| 整篇文档理解 | ❌ | ✅ 技能 + `kb_doc_analyze` → LangGraph 子图 |

## 1. 目标

1. **对话主路径**（有 `agent_id`）：走 LangGraph 主图，不再用「技能 tools 扁平合并」的 `_stream_skill_fc` 作为终态。  
2. **分层**：Agent 层只见「技能 / `rag_search` / `call_agent`」；原子工具仅在技能 ReAct 内。  
3. **文档理解**：技能 `skill_doc_understand` 挂 `kb_lookup` + `kb_doc_analyze`；后者为 LangGraph 子图（dump/summarize/critique + map-reduce）。  
4. **LLM**：统一 LangChain Chat → LiteLLM Proxy；禁止业务纯 HTTP 补全。

## 2. 非目标

- 外部 A2A；Agent 直调 HTTP/DB/文件原子工具  
- Temporal；完整 Langfuse 全量改造（本刀：图 trace 可先打日志，Langfuse 挂钩 P2）  
- 无 Agent 的漏斗捷径（请假卡 / 纯 kb_lookup 拼 snippet）本刀**保留兼容**，不强制迁图  
- `call_agent` 深度>2 / 环检测完善可 P1，P0 可 stub 禁调用或仅白名单直调  
- `workflow_call` 真执行可 P1（schema 可先占位）

## 3. 总体架构

```text
用户消息（SSE）
    ↓
runtime 有 agent_id？
    ├─ 否 → 现有意图漏斗捷径（兼容）
    └─ 是 → build_agent_graph(agent_id).ainvoke / astream
              │
              ▼
     ┌─ Planner（Plan-Execute 大循环）─┐
     │  产出 steps: [{skill|rag_search|call_agent|respond, ...}] │
     └──────────────┬──────────────────┘
                    ▼
     ┌─ Execute loop（逐步）───────────┐
     │  step=rag_search → 检索+citation │
     │  step=skill_X → Skill ReAct 小图  │
     │       （仅 skill_X 的原子 tools）   │
     │  step=call_agent → 内部互调（P0/P1）│
     │  step=respond → 结束计划提前答     │
     └──────────────┬──────────────────┘
                    ▼
     ┌─ Aggregator ───────────────────┐
     │  汇总 observation → 最终答案     │
     └────────────────────────────────┘

Skill ReAct 内若调 kb_doc_analyze：
     → DocAnalyze 子图（load→budget→dump|single|map-reduce→cite）
```

## 4. LLM：LangChain → LiteLLM Proxy

**模块**：`src/app/modules/llm/lc_chat.py`

- `get_chat_model(model=None) -> BaseChatModel`  
  - `ChatOpenAI(base_url=settings.litellm_proxy_url, api_key=settings.litellm_master_key, model=...)`  
- `MOCK_EXTERNAL` → Fake / 规则 mock model（单测不打网）  
- 流式 `astream`；工具 `bind_tools`  
- **禁止**新代码 `httpx` 打 `/v1/chat/completions`  
- 存量 `client.py`：P0 主图与文档子图不用；P1 runtime 全切后薄封装转调或删除补全 HTTP

依赖：`langgraph`, `langchain-core`, `langchain-openai`

## 5. 主图：Plan-and-Execute

### 5.1 AgentState（TypedDict）

```text
messages: list           # 对话消息（LangChain 或兼容 dict）
agent_id: str
user_id: str
plan: list[PlanStep]     # {id, kind, skill_id?, args?, status, observation?}
plan_cursor: int
citations: list
final_answer: str
error: str | None
usage: dict
```

`PlanStep.kind` ∈ `rag_search` | `execute_skill` | `call_agent` | `respond`

### 5.2 节点

| 节点 | 职责 |
|---|---|
| `plan` | LLM 根据用户问题 + **可用技能目录**（id/name/description）产出 JSON 计划（1～N 步）；简单问答可一步 `respond` 或单步 `execute_skill`/`rag_search` |
| `execute` | 执行 `plan[cursor]`；技能步进入 **Skill ReAct 子图**；rag 调现有 `run_kb_lookup`；完成后 cursor++ |
| `should_continue` | 条件边：还有未完成步骤 → execute；否则 → aggregate |
| `aggregate` | 汇总各步 observation + citations → `final_answer`（可再调一次 LLM 润色，**不得编造无 citation 的知识库事实**） |

### 5.3 Agent 层「工具」视图（给 Planner / 非原子）

Planner 只看到：

- 各绑定技能的 **技能级 function**（或统一 `execute_skill(skill_id, instruction)`）  
- `rag_search(query)`  
- `call_agent(target_agent_id, message)`（P0 可返回「未启用」）  

**看不到** `kb_doc_analyze` / `ask_user` 等原子工具名（避免破坏分层）。文档理解只能通过选中「文档理解」技能进入 ReAct 后再调原子工具。

### 5.4 计划质量护栏

- 最大步数：`agent_plan_max_steps`（默认 5）  
- Planner Mock：关键字「全部信息/总结/不合理」→ 单步 `execute_skill(skill_doc_understand)`；「查知识库/搜索下」→ `rag_search`；否则 `respond`  
- 计划非法 JSON → 降级单步 `respond` 或单步 rag（可配置）

## 6. 小图：技能内 ReAct

### 6.1 触发

`execute` 步 `kind=execute_skill` → `run_skill_react(skill_id, instruction, state)`

### 6.2 SkillReactState

```text
skill_id, instruction, messages, tool_results, citations, answer, round, max_rounds
```

### 6.3 循环

```text
START → reason（bind_tools(该技能 tool schemas)）
      → 有 tool_calls？
           ├─ 是 → act（executor）→ 回灌 → reason（直到无 tool 或达 max_rounds）
           └─ 否 → 文本作 observation → END
```

- `ask_user`：中断主图，SSE 提问卡（与现网一致）；恢复后续跑（沿用 card-action，P1 接好图 checkpoint 则更佳；P0 可保持「出卡结束本轮」）  
- `kb_lookup` / `kb_doc_analyze`：async 执行；citation 合并进 AgentState  
- `max_rounds`：沿用 `skill_fc_max_rounds`

### 6.4 与旧扁平 FC 差异

| 旧 | 新 |
|---|---|
| 所有技能 tools 合并给一次 FC | 先 Plan 选技能，再 **仅该技能** tools ReAct |
| Agent 变相直触原子工具 | 符合 PRD 分层 |

## 7. 文档理解（挂在技能上）

### 7.1 技能种子 `skill_doc_understand`

- tools：`kb_lookup`, `kb_doc_analyze`  
- prompt：整篇类调 analyze；局部用 lookup  

### 7.2 工具 `kb_doc_analyze` → DocAnalyze 子图

同前设计：`load → budget → route → dump|single|map-reduce → cite`  

- task：`dump|summarize|critique`  
- LLM：仅 `get_chat_model()`  
- 超长 summarize/critique：map-reduce；dump 超长：拼接截断  

### 7.3 意图辅助（无 Agent 或 Planner Mock）

漏斗 L2 `doc_analyze` 仍可用于无 Agent 路径；有 Agent 时优先主图，由 Planner/技能 prompt 引导。

## 8. runtime 切换

`stream_mock_reply`：

```text
if agent_id:
    async for event in stream_agent_graph(...):  # 新
        yield ...
    return
# else: 保留漏斗捷径
```

SSE：content_delta / citation / card / message_end 协议不变。  
Feature flag（可选）：`AGENT_RUNTIME=langgraph|legacy`，默认 langgraph，便于回滚。

## 9. 文件清单（拟）

| 路径 | 职责 |
|---|---|
| `pyproject.toml` | langgraph / langchain-core / langchain-openai |
| `src/app/modules/llm/lc_chat.py` | Chat 统一入口 |
| `src/app/modules/agent/graph/plan_execute.py` | 主图 |
| `src/app/modules/agent/graph/skill_react.py` | 技能 ReAct 小图 |
| `src/app/modules/agent/graph/build.py` | `build_agent_graph(agent_id)` |
| `src/app/modules/knowledge/doc_analyze_graph.py` | 文档子图 |
| `src/app/modules/knowledge/doc_analyze.py` | 门面 |
| `src/app/modules/tool/registry.py` + `executor.py` | `kb_doc_analyze` |
| `src/app/modules/conversation/runtime.py` | 切换入口 |
| `migrations/*_seed_skill_doc_understand.py` | 种子 |
| `tests/test_lc_chat.py` | |
| `tests/test_plan_execute_graph.py` | Planner/Execute/Aggregate |
| `tests/test_skill_react_graph.py` | 分层：不可见他技工具 |
| `tests/test_doc_analyze_graph.py` | map-reduce 路径 |

## 10. 分期（方案 B）

| 期 | 内容 | 验收要点 |
|---|---|---|
| **B0** | 依赖 + `lc_chat` + Mock | 无 httpx 补全；单测 mock 模型 |
| **B1** | DocAnalyze 子图 + `kb_doc_analyze` + L2 无 Agent 路径 | 唐亮全部信息/合同 critique/超长 map_reduce |
| **B2** | Skill ReAct 小图（替换扁平 FC 内核） | 仅当前技能 tools；ask_user 出卡 |
| **B3** | Plan-Execute 主图 + runtime 切换 | 计划多步；rag+技能组合；flag 可回滚 |
| **B4** | 种子技能文档理解 + Agent 绑定 + 联调 | 端到端 SSE |
| **B5** | 收尾：旧 `_stream_skill_fc` 弃用路径、CHECKPOINT、（可选）Langfuse | |

## 11. 验收总表

1. 有 Agent 对话走 LangGraph 主图（日志/stats 可证）  
2. Planner 产出合法 plan；Execute 逐步写 observation  
3. 技能 ReAct **不能**调用未绑定工具  
4. 文档理解：dump 覆盖多切块；critique 有 citation  
5. 超长文档 `mode=map_reduce`  
6. `MOCK_EXTERNAL` 全绿；真 Proxy 冒烟可选  
7. 无 Agent 漏斗捷径仍可用  
8. 新补全路径无业务纯 HTTP  

## 12. 风险

| 风险 | 对策 |
|---|---|
| 主图一次性过大 | 严格按 B0→B5；flag 回滚 legacy FC |
| Planner 胡规划 | max_steps + Mock 规则 + 非法降级 |
| ask_user 与图状态 | P0 出卡结束本轮；P1 checkpoint/Redis |
| Session 跨 await | load 节点拉齐数据快照进 state |
| 双 LLM 栈 | 主路径只 lc_chat；禁新 httpx 补全 |

## 13. 硬裁定（已定）

1. **方案 B**：Plan-Execute + ReAct + 文档理解同刀分期交付  
2. LangGraph 官方库；LangChain → LiteLLM Proxy  
3. Agent 不直调原子工具  
4. 文档分析工具产出可作最终片段；Aggregate 不得无中生有  
