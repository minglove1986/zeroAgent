# Agent kb_ids 落库与检索过滤设计

@author 赵振明
@date 2026-07-22 14:48:54

## 范围（已批准 · 方案 A）

1. 关联表 `agent_kbs` 持久化 Agent ↔ KB  
2. 创建 Agent 写入 `kb_ids`；列表/详情回读；`PUT` 全量替换绑定  
3. `run_kb_lookup` / RAG 按 Agent 绑定过滤（未绑定回落全库）  

## 不做（另排期）

- `kg_ids` 落库  
- KB 权限并集（D13）进检索  
- Hybrid  

## 数据

表 `agent_kbs`：

| 列 | 类型 |
|---|---|
| id | int PK AI |
| agent_id | varchar(32) |
| kb_id | varchar(32) |

迁移：`0017_agent_kbs`（revises `0016_document_chunks`）

## API

- `POST /agents`：校验每个 `kb_id` 存在，否则 422；写入 `AgentKb`  
- `GET /agents` / 单条：附带 `kb_ids`  
- `PUT /agents/{agent_id}/kbs`：body `{ "kb_ids": [...] }` 全量替换（先删后插；校验存在）  

## 检索

`resolve_kb_ids_for_agent(db, agent_id: str | None) -> list[str]`：

- `agent_id` 有绑定行 → 仅这些 id  
- 无绑定行或 `agent_id is None` → `list_all_kb_ids`（兼容）  
- 工具参数 `kb_ids` 与结果求交；交空 → 空 citations  

接线：`run_kb_lookup(..., agent_id=)`；runtime FC / RAG 传入当前 `agent_id`。

## 测试

- 创建带 kb_ids → DB 有行、GET 回显  
- 非法 kb_id → 422  
- PUT 替换  
- 绑定 Agent 只搜到绑定库 chunks；未绑定仍可搜全库  

## 验收

1. 创建 Agent 的 `kb_ids` 重启后仍在  
2. 双 KB 场景下，绑定 A 的 Agent 检索不到仅属 B 的内容  
3. 既有无 Agent / 未绑定路径行为不回归  
