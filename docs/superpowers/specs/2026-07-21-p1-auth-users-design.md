# P1 切片设计：账号与 Session（方案 A）

> 日期：2026-07-21 16:16:45  
> 状态：已确认（用户选 A）  
> 依据：PRD v0.7.4 D8/D23/D27；计划 Task 2–3

## 目标

可演示：创建用户 → 登录拿 Session → 受保护接口可识别 `user_id`。  
**不做**：OpenIM、`im_user_maps`、多租户。

## 技术选择（A）

| 项 | 决策 |
|---|---|
| 单测 DB | `sqlite+aiosqlite:///:memory:`（或临时文件），与生产 MySQL 方言差异可接受于 P1 |
| 生产/本地联调 | 仍用 MySQL（Compose），Alembic 迁移以 MySQL DDL 为准 |
| 鉴权 | Session Cookie，8h；密码 bcrypt |
| 超管 stub | 创建用户接口暂用依赖注入 stub（后续接真实 RBAC） |
| LLM | 本切片不用；密钥仅写入本地 `.env` 供后续 Task 7 |

## 接口

- `POST /api/v1/users`：创建用户（字段对齐库表）
- `POST /api/v1/auth/login`：成功 Set-Cookie；失败 `code=40101`
- `POST /api/v1/auth/logout`

## 验收

- `pytest tests/test_user_create.py tests/test_auth_login.py -q` 全绿  
- 无 `tenant_id`、无 OpenIM 代码  

## 非目标

KB、Agent、对话、卡片（后续 Task）。
