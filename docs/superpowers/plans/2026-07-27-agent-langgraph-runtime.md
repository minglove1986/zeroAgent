# Agent LangGraph 运行时（方案 B）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).  
> **规格：** `docs/superpowers/specs/2026-07-24-doc-understand-skill-design.md`（已批准，方案 B）

**Goal:** 用 LangChain→LiteLLM 调模型；落地 Plan-Execute 主图 + 技能 ReAct 小图 + 文档理解子图；有 Agent 的对话切到新运行时。

**Architecture:** `lc_chat` 统一 Chat；`doc_analyze` 子图挂工具 `kb_doc_analyze`；`skill_react` 仅暴露当前技能原子工具；`plan_execute` 主图 Planner→Execute→Aggregate；`runtime` 有 `agent_id` 时走主图（`AGENT_RUNTIME` flag 可回滚）。

**Tech Stack:** Python 3.11+、langgraph、langchain-core、langchain-openai、现有 FastAPI/SQLAlchemy、LiteLLM Proxy。

## Global Constraints

- 单租户；禁止 `tenant_id`
- LLM 只经 LiteLLM Proxy；**禁止**业务纯 httpx 打 chat completions（本刀新路径）
- Agent 不直调原子工具；原子工具仅技能 ReAct 内
- 检索仅 `published`；D14 须 citation
- 注释 `@author 赵振明` + 东八区实时
- 用户未要求则不 git commit
- TDD：先红后绿；Python：`$env:LOCALAPPDATA\Programs\Python\Python312\python.exe -m pytest ...`

## File map

| 路径 | 职责 |
|---|---|
| `pyproject.toml` | 加 langgraph / langchain-core / langchain-openai |
| `src/app/core/config.py` | `agent_runtime`、doc_analyze token 配置 |
| `src/app/modules/llm/lc_chat.py` | Chat 统一入口 |
| `src/app/modules/knowledge/doc_analyze_graph.py` | 文档 LangGraph 子图 |
| `src/app/modules/knowledge/doc_analyze.py` | `run_doc_analyze` |
| `src/app/modules/tool/registry.py` / `executor.py` | 注册 `kb_doc_analyze` |
| `src/app/modules/agent/graph/skill_react.py` | 技能 ReAct |
| `src/app/modules/agent/graph/plan_execute.py` | 主图 |
| `src/app/modules/agent/graph/build.py` | `build_agent_graph` |
| `src/app/modules/conversation/runtime.py` | 切换入口 |
| `src/app/modules/intent/rules.py` | L2 `doc_analyze`（无 Agent 路径） |
| `migrations/*_seed_skill_doc_understand.py` | 种子技能 |
| `tests/test_lc_chat.py` 等 | 各期单测 |

---

### Task 1（B0）：依赖 + `lc_chat`

**Files:** `pyproject.toml`、`src/app/core/config.py`、`src/app/modules/llm/lc_chat.py`、`tests/test_lc_chat.py`

- [ ] **Step 1:** 添加依赖并安装  
  `langgraph`, `langchain-core`, `langchain-openai`（锁定与 py3.12 兼容的近期稳定版）

```bash
cd D:\HermesWork\zeroAgent
# 用项目惯用方式安装 editable / pip install -e ".[dev]" 并确保新依赖进环境
```

- [ ] **Step 2:** RED — `tests/test_lc_chat.py`

```python
def test_get_chat_model_mock_returns_content(monkeypatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.modules.llm.lc_chat import get_chat_model
    import asyncio
    from langchain_core.messages import HumanMessage
    model = get_chat_model()
    msg = asyncio.get_event_loop().run_until_complete(
        model.ainvoke([HumanMessage(content="hi")])
    )
    assert msg.content  # mock 非空
    get_settings.cache_clear()

def test_get_chat_model_base_url_points_proxy(monkeypatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    # 仅断言工厂配置的 base_url 含 litellm 配置值（可不真实发请求）
    ...
```

- [ ] **Step 3:** 实现 `lc_chat.get_chat_model`  
  - Mock：返回固定 `AIMessage` 的简易 Runnable  
  - 真：`ChatOpenAI(base_url=..., api_key=..., model=...)`  
  - **本文件不得 httpx.post chat**

- [ ] **Step 4:** `pytest tests/test_lc_chat.py -v` → PASS

---

### Task 2（B1）：DocAnalyze 子图 + 工具

**Files:** `doc_analyze_graph.py`、`doc_analyze.py`、`registry.py`、`executor.py`、`config.py`、`rules.py`、`runtime.py`（无 Agent 的 `doc_analyze` 分支）、`tests/test_doc_analyze_graph.py`

- [ ] **Step 1:** RED — 图路由

```python
@pytest.mark.asyncio
async def test_doc_analyze_single_path(monkeypatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    # 短文档 → mode single 或 dump；answer 非空；citations 有 doc

@pytest.mark.asyncio
async def test_doc_analyze_map_reduce_when_over_budget(monkeypatch):
    # 人为很小 budget 或超长 chunks → stats.parts >= 2, mode=map_reduce

@pytest.mark.asyncio
async def test_doc_analyze_rejects_unpublished():
    # 409/ok=False
```

- [ ] **Step 2:** 实现 StateGraph：`load → budget → route → dump|single|map→reduce → cite`  
  LLM 节点只用 `get_chat_model()`。

- [ ] **Step 3:** 注册 `kb_doc_analyze`；`execute_builtin_tool_async` 调 `run_doc_analyze`。

- [ ] **Step 4:** L2 `doc_analyze` + runtime 无 Agent 时调用同一门面（直接展示 answer+citations）。

- [ ] **Step 5:** `pytest tests/test_doc_analyze_graph.py tests/test_kb_entity_filter.py -q` → PASS

---

### Task 3（B2）：Skill ReAct 小图

**Files:** `src/app/modules/agent/graph/skill_react.py`、`tests/test_skill_react_graph.py`  
可选：暂不改 runtime，先单测小图。

- [ ] **Step 1:** RED

```python
@pytest.mark.asyncio
async def test_skill_react_only_sees_bound_tools(db_with_skill):
    # skill A 只有 echo；调用时 tools 列表不含 kb_lookup
    # mock 模型若请求未绑定 tool → executor 拒绝

@pytest.mark.asyncio
async def test_skill_react_ask_user_defers_card():
    # 返回 deferred card 结构，与现网 ask_user 兼容
```

- [ ] **Step 2:** 实现 `run_skill_react(skill_id, instruction, ...)`：  
  `reason(bind_tools) → act → ...` 直至无 tool_calls 或 max_rounds。

- [ ] **Step 3:** `pytest tests/test_skill_react_graph.py -v` → PASS

---

### Task 4（B3）：Plan-Execute 主图 + runtime 切换

**Files:** `plan_execute.py`、`build.py`、`runtime.py`、`config.py`（`agent_runtime: langgraph|legacy`）、`tests/test_plan_execute_graph.py`

- [ ] **Step 1:** RED

```python
@pytest.mark.asyncio
async def test_plan_execute_rag_then_aggregate(monkeypatch):
    # Mock planner → [rag_search]；execute 调 run_kb_lookup；final_answer 非空

@pytest.mark.asyncio
async def test_plan_execute_skill_step_enters_react(monkeypatch):
    # plan step execute_skill → 进入 skill_react（可用 spy）

@pytest.mark.asyncio
async def test_runtime_langgraph_flag(monkeypatch, client):
    # AGENT_RUNTIME=langgraph 且有 agent+skills → 不走旧扁平 FC
```

- [ ] **Step 2:** 实现主图节点 `plan / execute / aggregate` + 条件边。  
  Planner：真模型 JSON；Mock 关键字规则（规格 §5.4）。

- [ ] **Step 3:** `build_agent_graph(db, agent_id)` 加载技能目录。

- [ ] **Step 4:** `stream_mock_reply`：`agent_id` 且 `agent_runtime=langgraph` → 流式打出 graph 的 answer/citations；`legacy` → 旧 `_stream_skill_fc`。

- [ ] **Step 5:** 相关 pytest → PASS

---

### Task 5（B4）：种子技能 + 端到端

**Files:** `migrations/0023_seed_skill_doc_understand.py`（版本号以 head+1 为准）、可选前端无改、`tests/test_doc_understand_e2e.py`

- [ ] **Step 1:** 迁移插入 `skill_doc_understand` + `skill_tools(kb_lookup, kb_doc_analyze)` + 合理 system_prompt。

- [ ] **Step 2:** RED/GREEN e2e（内存 DB）：Agent 绑该技能；用户「唐亮的全部信息」→ Mock planner 选文档理解技能 → analyze dump → answer 含多块线索。

- [ ] **Step 3:** `alembic upgrade head`（本机）+ pytest e2e → PASS

---

### Task 6（B5）：收尾

**Files:** `CHECKPOINT.md`、规格状态、必要时标记 `_stream_skill_fc` deprecated 注释

- [ ] 更新断点：B0–B5 完成项、flag 默认值、联调命令  
- [ ] 跑回归：`test_chunk_review`、`test_kb_lookup_search`、`test_lc_chat`、`test_doc_analyze*`、`test_plan_execute*`、`test_skill_react*`  
- [ ] 确认新路径无业务 httpx chat  

---

## Spec coverage

| 规格 | Task |
|---|---|
| lc_chat / 禁 HTTP | T1 |
| DocAnalyze + kb_doc_analyze | T2 |
| Skill ReAct 分层 | T3 |
| Plan-Execute + runtime | T4 |
| 种子技能联调 | T5 |
| 收尾 | T6 |

## 执行方式

计划就绪后请用户选：

1. **本会话按 Task 推进**  
2. **另开会话执行**  
