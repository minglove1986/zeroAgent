# 对话关键节点 turn_trace DEBUG 日志设计

> 日期：2026-09-08  
> 状态：已实现  
> 关联：Turn Main Graph + Plan-Execute；不含 Skill ReAct 轮次细节  
> @author 赵振明  
> @date 2026-09-08 13:53:27

## 1. 目标

每次用户对话在后台可用 `DEBUG` 日志串起执行路径与步骤，便于判断「走了哪条路、做了哪些步」。  
不改 SSE / 前端；不落库；不增加管理端 UI。

## 2. 已确认裁定

| 项 | 裁定 |
|---|---|
| 粒度 | **A**：关键节点一行摘要 |
| 级别 | **B**：`logger.debug`（需把相关 logger 调到 DEBUG 才可见） |
| 覆盖 | **B**：Turn 主图 + Plan-Execute；**不含** Skill ReAct 内 reason/act 轮次 |
| 实现 | **方案 2**：统一 `turn_trace` 助手，固定前缀，散点调用 |
| 隐私 | 不打用户全文；observation / answer 截断约 80 字；禁止密钥 |

## 3. 模块

新增：`src/app/modules/conversation/turn_trace.py`

职责：

- `trace(node: str, event: str, *, conv: str | None = None, user: str | None = None, **fields) -> None`
- 输出单行：`turn_trace conv=… user=… node=… event=… k=v …`
- 值做简单清洗：空格→`_`；过长截断；`None` 省略
- logger 名：`app.modules.conversation.turn_trace`（便于只开这一路 DEBUG）

可选：`clip(text, n=80)` 供调用方截断 observation。

## 4. 埋点清单

### 4.1 Turn（`turn_graph` / `runtime`）

| 位置 | node | event | 关键字段 |
|---|---|---|---|
| `stream_turn` 入口 | `turn` | `start` | `conv`, `user`, `agent`, `thinking` |
| intent 完成后（stream updates） | `intent` | `done` | `kind`, `handler`, `reason`, `confidence`, `layer` |
| handoff 分支 | `turn` | `handoff` | `dispatch`, `effective_agent` |
| 图内直接出答（非 handoff） | `turn` | `inline_answer` | `has_card`, `answer_len` |
| runtime `message_end` / 错误收尾 | `runtime` | `end` | `path`, `status` |

### 4.2 Plan-Execute（`plan_execute`）

| 位置 | node | event | 关键字段 |
|---|---|---|---|
| `stream_plan_execute` 入口 | `plan_execute` | `start` | `agent`, `allow_web`, `exclude_web_skill`, `max_steps` |
| `_node_plan` 结束 | `plan` | `done` | `steps`, `kinds`（逗号拼接） |
| `_node_execute` 每步结束 | `execute` | `step` | `cursor`, `kind`, `skill`, `status`, `obs`（截断） |
| 联网 Policy（`_execute_skill_step`） | `web_search_policy` | `decide` | `skill`, `decision` |
| `_should_continue` | `execute` | `route` | `next`=`execute`\|`aggregate`, `why` |
| `_node_aggregate` 结束 | `aggregate` | `done` | `ok`, `answer_len`, `cite_n` |

`why` 取值约定：`deferred_card` | `final_answer` | `cursor_end` | `max_steps` | `continue`。

## 5. 非目标

- 不改 Skill ReAct 内部轮次日志（后续可加）
- 不把日志推到 SSE / thought_delta
- 不新增环境变量开关（级别靠 logging 配置）
- 不记录完整 plan JSON / 完整 LLM 报文

## 6. 如何查看（Docker 镜像部署）

1. `deploy/.env` 设 `LOG_LEVEL=DEBUG`（示例文件默认已是 DEBUG）
2. **必须重建并滚动 API 镜像**（CMD 含 `--log-level ${LOG_LEVEL}`，仅重启旧镜像不够）：

```powershell
cd D:\HermesWork\zeroAgent
.\scripts\deploy-update.cmd
# 或只更 API：.\scripts\deploy-update.ps1 -SkipFrontends
```

3. 发一轮员工端对话后，跟 API 容器日志：

```powershell
# 实时跟随（推荐）
docker logs -f --tail 200 zeroagent-api 2>&1 | Select-String turn_trace

# 最近一段时间
docker logs --since 10m zeroagent-api 2>&1 | Select-String turn_trace

# 按会话串一轮（把 conv_xxx 换成实际 id）
docker logs --since 30m zeroagent-api 2>&1 | Select-String "turn_trace.*conv=conv_xxx"
```

Linux / Git Bash：

```bash
docker logs -f --tail 200 zeroagent-api 2>&1 | grep turn_trace
```

按同一行里的 `conv=` 即可串起 Turn → Plan-Execute 路径。  
容器名以 `deploy/docker-compose.yml` 的 `container_name: zeroagent-api` 为准。

## 7. 测试

- 单测 `turn_trace`：格式含前缀 `turn_trace`、截断、省略空字段
- 可选：`caplog` 断言 `plan`/`execute` 在 mock 路径会打出对应 event（不强制全图集成）

## 8. 风险与应对

| 风险 | 应对 |
|---|---|
| DEBUG 默认不可见，误以为没打 | 规格与 CHECKPOINT 写明开启方式 |
| 高频对话日志量 | 仅关键节点、一行、截断；不含 ReAct 轮次 |
| 误打用户隐私 | 禁止 user_content 全文；obs/answer 截断 |
