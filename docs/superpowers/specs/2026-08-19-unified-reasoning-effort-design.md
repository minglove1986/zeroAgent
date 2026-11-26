# 统一思考参数与能力位（reasoning_effort）

> 状态：已实现  
> 日期：2026-08-19 16:22:38（东八区）  
> 作者：赵振明  
> 对齐：LiteLLM 统一 `reasoning_effort` / `reasoning_content`；模型治理 `llm_models`；员工端 `deep_think`  
> 会话裁定：方案 B；未知模型隐藏开关；不在业务代码维护厂商名单

## 1. 目标与非目标

### 1.1 目标

1. 业务请求 **只发** LiteLLM 统一参数 `reasoning_effort`：关=`none`，开=`medium`。  
2. **去掉** MiniMax 硬编码 `extra_body.thinking.type=adaptive|disabled`。  
3. 从 LiteLLM `/model/info` 解析 `supports_reasoning`，写入目录；未知/缺失视为 **不支持**。  
4. 员工端仅当当前会话模型 `supports_reasoning=true` 时显示「深度思考」。  
5. 保留已有流式透传：`reasoning_content` → `thought_delta`（`_LiteLLMChatOpenAI` 不动语义）。

### 1.2 非目标

- 前端暴露低/中/高档位（本期只要开/关）。  
- 管理端 PATCH 覆盖能力位（本期同步为真相；纠错改 LiteLLM `config.yaml` 的 `model_info`）。  
- 在 `deploy/litellm/config.yaml` 为每个模型手写厂商思考字段。  
- 改联网搜索、Planner 拓扑、人格注入。  
- 精确处理「常开推理模型关不掉」（如部分 reasoner）；仅文档说明。

## 2. 已确认裁定

| 项 | 裁定 |
|---|---|
| 请求参数 | 统一 `reasoning_effort`：关 `none` / 开 `medium` |
| 厂商映射 | 交给 LiteLLM；业务不写 `thinking.type` |
| 自定义模型（如 `agnes-2.5-flash`） | **不**在 yaml 写 `false`；未知默认不支持 |
| 需覆盖时 | 仅在 LiteLLM 该模型 `model_info.supports_reasoning` 标明 |
| 员工端未知模型 | **隐藏**「深度思考」，不展示无效开关 |
| 开思考档位 | 固定 `medium`，无 UI 档位 |
| 能力位来源 | 同步 `/model/info` → MySQL → Redis；不在业务硬编码名单 |
| `drop_params` | 保持 `true`（不支持参数被丢掉，避免 400） |

## 3. 架构与数据流

```text
员工端 深度思考开关
        │ 仅当当前模型 supports_reasoning=true 才渲染
        ▼
POST /messages  deep_think
        │
        ▼
runtime / get_chat_model
        │ 目录 supports_reasoning≠true → 强制按关处理
        ▼
LiteLLM Proxy
        │ reasoning_effort=none|medium
        │ 映射各厂原生字段；不支持则 drop
        ▼
厂商 API
        │
        ▼
流式 delta.reasoning_content
        │ _LiteLLMChatOpenAI 写回 additional_kwargs
        ▼
SSE thought_delta → 过程面板
```

同步：

```text
LiteLLM GET /model/info
  → 提取 supports_reasoning（仅显式 true 为真）
  → llm_models.supports_reasoning
  → Redis za:llm:models:v1
  → GET /llm-models/available 带回该字段
```

## 4. 请求侧（`get_chat_model`）

文件：`src/app/modules/llm/lc_chat.py`

| `enable_thinking` | 发给 LiteLLM |
|---|---|
| false（或目录不支持） | `extra_body.reasoning_effort = "none"` |
| true 且目录支持 | `extra_body.reasoning_effort = "medium"` |

约束：

- **禁止**再写 `thinking` / `thinking.type`。  
- `max_tokens` 维持现状：开思考 4096，否则 2048。  
- 构造前查 Redis 目录：当前 `model` 的 `supports_reasoning` 不是 true 时，**忽略**调用方的 true（防前端误传 / 绕过）。  
- 目录为空或该模型不在目录：仍按调用方布尔发 `none|medium`（靠 Proxy `drop_params`）。  
- 响应透传逻辑保持：`_delta_reasoning_from_openai_chunk` + `additional_kwargs.reasoning_content`。

## 5. 能力位同步

文件：`src/app/modules/llm/litellm_sync.py`

### 5.1 提取规则（只认显式真）

在 `model_info` 嵌套与顶层中按序读取，**仅**下列为 true：

- `supports_reasoning is True`（JSON `true`）  
- `supported_openai_params` 列表含 `reasoning_effort` 或 `reasoning`（大小写不敏感）

其余（缺字段、`false`、`null`、空列表）→ **0**。  
`agnes-2.5-flash` 一类自定义 OpenAI 兼容名通常无此字段 → 0。

### 5.2 表字段

`llm_models.supports_reasoning`：`TINYINT NOT NULL DEFAULT 0`（0/1）。

- 每次同步 **覆盖** 该列（与窗口字段相同，不沿用管理员手改；本期也无手改入口）。  
- 不因该字段把模型标为 `incomplete`；缺能力位不是残缺，只是不支持思考。  
- 迁移：`0042_llm_supports_reasoning`（revises `0041_user_id_card`；revision 须 ≤32 字符）。

### 5.3 缓存与 API

`build_catalog_payload`、管理端列表、员工端 `GET /llm-models/available` 均带 `supports_reasoning: bool`。

管理端列表只读展示（如「支持思考」列）；**不**加入 `LlmModelPatch`。

### 5.4 LiteLLM 配置

`deploy/litellm/config.yaml` **不必**为 agnes 补 `supports_reasoning: false`。

仅当自定义别名实际支持思考、且官方价目表对不上时，在该模型下写：

```yaml
model_info:
  supports_reasoning: true
```

## 6. 员工端

文件：`web/src/app/chat/page.tsx`

- `ModelOption` 增加 `supports_reasoning?: boolean`。  
- 「深度思考」按钮：当前选用模型（空=列表中系统默认或第一项）`supports_reasoning === true` 才渲染。  
- 切换到不支持的模型时：`setDeepThink(false)`，且本次及后续请求 `deep_think` 为 false。  
- 列表尚未返回时不展示开关（避免闪一下）。  
- Agent 会话同一套：能力位来自该会话可选列表，不按对话类型写死。

## 7. 后端防御

`POST /messages` 的 `deep_think=true` 仍可传到 runtime；**最终**以 `get_chat_model` 对照目录为准。  
不因此返回 400（避免旧前端报错）；静默降级为关思考。

## 8. 文档（实现时同步改）

- `docs/01-产品需求/API接口规范.md`：`/llm-models/available` 与管理端列表增加 `supports_reasoning`；版本记一笔。  
- `docs/01-产品需求/数据库表结构.md`：`llm_models` 增该列说明（现清单已有表名、正文可补短表）。  
- 不改 PRD 第十六章产品裁定（无新 D 条）。

## 9. 测试

| 测例 | 期望 |
|---|---|
| 提取：显式 true | 1 |
| 提取：缺字段 / false / agnes 形态 raw | 0 |
| 提取：`supported_openai_params` 含 `reasoning_effort` | 1 |
| `get_chat_model(enable_thinking=True)` | `reasoning_effort=medium`，**无** `thinking` 键 |
| `get_chat_model()` 默认 | `reasoning_effort=none`，**无** `thinking` 键 |
| 目录该模型为 false 时即使 enable_thinking=True | 仍发 `none` |
| 保留 MiniMax chunk → `reasoning_content` 透传 | 现有测例继续绿 |
| `GET /llm-models/available` | item 含布尔 `supports_reasoning` |
| 同步 upsert | 行上 `supports_reasoning` 随远端变化覆盖 |

## 10. 验收

- [ ] 选 MiniMax-M3（目录 true）：开关可见；开→过程区有模型思考；关→无思考增量且正文正常。  
- [ ] 选 `agnes-2.5-flash`（目录 false/缺）：开关不可见；发消息不带思考参数（或仅 `none` 被 drop）。  
- [ ] 选 DeepSeek（目录 true）：开关可见；开思考走统一参数，不 400。  
- [ ] 从不支持切到支持：开关出现；从支持切到不支持：开关消失且状态关闭。  
- [ ] 管理端同步后列表能看出谁支持思考。  
- [ ] 相关单测绿。

## 11. 风险

| 风险 | 应对 |
|---|---|
| 当前 LiteLLM 版本未把 `none` 映射成 MiniMax `thinking.disabled`，关开关后 M3 仍思考 | 实现后用 M3 实测关开关；若失败再升 Proxy 或仅对该失败补配置，**不**恢复业务硬编码为默认方案 |
| `/model/info` 对官方模型也不带 `supports_reasoning` | 同时认 `supported_openai_params`；仍全 false 时在 yaml 给真正需要的模型标 true |
| `deepseek-reasoner` 等关不掉思考 | 开关可显示；关了过程区仍可能有思考。本期不引入 `supports_none_reasoning_effort` |
| 价目表滞后，新模型误判 | 未知当不支持（安全侧）；真支持则 yaml 标 true 后重新同步 |
| `extra_body` 与 ChatOpenAI 一等 `reasoning_effort` 重复 | 只走 `extra_body`，避免双写 |

## 12. 实现后

- 更新 `docs/superpowers/CHECKPOINT.md`  
- 计划文件：确认本规格后再写 `docs/superpowers/plans/2026-08-19-unified-reasoning-effort.md`
