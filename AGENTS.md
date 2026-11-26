# zeroAgent — AI Agent 开发入口

> 本仓库面向 **AI Agent 全量实现**。人类与 Agent 均须遵守本文档。


## 会话断点（防上下文中断）

**每次实质推进后必须更新** `docs/superpowers/CHECKPOINT.md`：

1. 覆盖写顶部「当前断点」
2. 底部「断点日志」**追加**一条（保留历史）
3. 禁止写入密钥明文
4. 每次新增web接口后，必须更新 `docs/01-产品需求/API接口规范.md`

新开上下文时：**先读 CHECKPOINT，再动手**。

## 唯一真相（按优先级）

1. `docs/superpowers/CHECKPOINT.md`（**仅**用于「做到哪了 / 下一步」，不覆盖产品裁定）
2. `docs/01-产品需求/PRD.md` **第十六章（D1–D48）**
3. `docs/01-产品需求/API接口规范.md`（v0.7.4+）
4. `docs/01-产品需求/数据库表结构.md`（v0.7.4+）
5. `docs/03-技术选型/技术选型.md`（v0.5+）
6. `docs/03-技术选型/MySQL与OSS适配.md`（**仅 v0.3+**）
7. `docs/02-架构设计/总体架构.md`（v0.5+）
8. `docs/01-产品需求/权限用户菜单PRD.md`（**v1.0.4+**；组织权限；冲突以主 PRD 第二章/第十六章为准；按实现状态与 M1/M1.5/M2 分期；管理端新建页遵守 §9.0 / 主 PRD D48）
9. `docs/05-开发指南/文档白名单与废止清单.md`
10. `docs/superpowers/plans/` 当前实现计划
11. `docs/adr/002-monorepo-web-backend.md`
12. 用户提出不符合架构、现实逻辑、需要和用户确认并提出意见后执行，不要一味顺着用户
13. 当完成需求后，编写接口文档，进行冒烟测试、用例测试和真实API调用测试

**禁止作为实现依据**：

- PRD「附录 A」
- `docs/superpowers/specs/2026-07-21-prd-closure-design.md`（史料，文首已声明）
- 任何写「OpenIM 主入口 / file-callback / OSS 事件入库」且未标废止的旧段落

## 开发拓扑（本地）

| 组件 | 方式 |
|---|---|
| MySQL/Redis/RabbitMQ/Milvus/Neo4j/Langfuse/LiteLLM | `deploy/docker-compose.yml` |
| OpenIM | **不接入** |
| LLM / OSS | 线上（经 LiteLLM / OSS SDK） |
| **后端** | `src/app` + Celery · 端口 **8000**（**固定**，禁止随意改端口；占用先清进程） |
| **前端** | 本仓 **`web/`**（Next.js）· 端口 **3000** · `/api` 代理到后端 `8000` |
| 对话入口 | Web 系统对话（SSE + 交互卡片） |

详见 `docs/05-开发指南/环境与密钥.md`。

## 硬约束（违反即错误）

- **单租户**：禁止 `tenant_id`
- Agent **不绑**一等 `tool_ids`；工具挂在技能上
- 工作流仅技能 `workflow_call`；提问卡经技能 **`ask_user`**（D33）
- 内部 `call_agent`：白名单、深度≤2、禁环；**无外部 A2A**
- KB 权限 **并集**；RAG 路径强制 citation
- LLM **只经 LiteLLM Proxy**
- **不做 OpenIM**；文件 **Web 上传 → OSS → Celery**
- Web 对话须支持 **交互卡片** + `card-action`
- 人工确认 / 高风险：**仅 Web `/approvals`**
- 告警：站内通知 + Webhook
- Langfuse **仅自托管**
- **管理端持久壳（D48）**：页只放 `admin-web/src/app/(admin)/**`；禁止页内再包 `AdminLayout`；菜单 path 必有页/占位；未知路径壳内 404（详见主 PRD §12.1.1、`权限用户菜单PRD` §9.0）

## 实现节奏

按 `docs/superpowers/plans/` **Task** 逐个：测试 → 实现 → 验收。  
禁止无计划地「按 PRD 一次性全量实现」。

## 代码约定

- 后端：Python 3.11+、FastAPI、类型注解、异步优先
- 注释：`@author 赵振明`；时间用东八区实时
- 密钥：仅环境变量；禁止硬编码
- 提交：仅在用户明确要求时 commit
