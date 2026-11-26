# 记忆抽取「真正 Skill」落地规格（补丁）

> **日期**：2026-08-20 16:46:14（东八区）  
> **状态**：已确认（1A/2A/3A/4A/5A/6/7）  
> **作者**：赵振明  
> **前置**：`2026-08-20-memory-extract-skill-design.md`

## 裁定汇总

| # | 裁定 |
|---|---|
| 1A | 系统种子 Skill：`skill_memory_extract` |
| 2A | 仅绑定系统对话 Agent：`agent_system` |
| 3A | 被动：调度强制执行工具实现；显式：可走 FC 调同一工具 |
| 4A | 唯一工具：`extract_user_memories` |
| 5A | Celery Worker 执行 Skill 工具实现（不阻塞 SSE） |
| 6 | 技能列表可见；`origin=system` **禁止删除**，仅 `status=disabled/published` 停用/启用 |
| 7 | 系统配置开关 `memory_extract_enabled`（环境变量 + Redis 可覆盖） |

## 门禁（同时满足才抽取）

1. `memory_extract_enabled == true`  
2. Skill `status == published`（非 disabled）  
3. `allow_memory_write`（系统对话默认 true）  
4. 调度未 skip（纠正/纯 KB 等）

## 数据

- `skills.origin` / `skills.seed_code`  
- 种子行 + `skill_tools(extract_user_memories)`  
- `agents` 行 `agent_system` + `agent_skills` 绑定  
- Agent：`can_modify_memory=1`，`memory_access=all`

## API

- `GET /skills`：返回 `origin` / `seed_code` / `tool_ids`  
- `PATCH /skills/{id}`：改 status（published|disabled）；系统种子允许改 description/system_prompt？**本期仅允许改 status**  
- `DELETE /skills/{id}`：系统种子 → **403**  
- `GET/PUT /api/v1/system/memory-extract-settings`：读写全局开关  

## 运行时

- 工具注册表 + `execute_builtin_tool_async`  
- `skill_react` 将该工具列入异步工具  
- `schedule_memory_extract` / Celery → `run_memory_extract_skill`（内部再校验门禁）  
