# 用户身份证字段 + 管理端详情四 Tab（方案 3）

> 状态：已实现（迁移 `0041` + API + 管理端详情四 Tab；测 8 passed）  
> 日期：2026-08-11 15:21:57（东八区）  
> 作者：赵振明  
> 依据：`权限用户菜单PRD` §3.2 / §9.5–9.6；会话裁定：字段方案 A、展示明文、选填唯一、详情四 Tab 全做
> 计划：`docs/superpowers/plans/2026-08-11-user-id-card-detail-tabs.md`

## 1. 目标与非目标

### 1.1 目标

1. `users` 增加选填字段 `id_card`（有值则唯一）；管理端列表/表单/详情明文展示。
2. 管理端补齐用户详情页 `/organization/users/[user_id]`，含 PRD §9.5 顶栏 + 四个 Tab：**基本信息 / 部门与角色 / 会话历史 / 操作日志**。
3. 顺带收紧手机号校验（大陆 11 位）；列表展示手机、身份证。

### 1.2 非目标

- 身份证加密落库、列表/API 脱敏、性别/生日派生列。
- 员工端自助改手机/身份证（M2+）。
- 新建用户四步向导页（继续用列表抽屉新建）。
- 扩大多租户、外部 A2A、OpenIM 等范围。

## 2. 数据模型

### 2.1 列定义

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id_card` | `VARCHAR(18)` NULL | 非空唯一索引 | 中国大陆 18 位身份证；空串入库前转 `NULL` |

迁移：`0041_user_id_card`（加列 + 唯一索引；不回填历史）。

### 2.2 校验

- **身份证**：可选。有值时：`^[0-9]{17}[0-9Xx]$`，末位统一存大写 `X`。重复 → 与工号/用户名冲突同风格（现行用户域 `fail` 码，实现时对齐已有唯一冲突响应，禁止另造一套）。
- **手机**：创建/更新时 `^1[3-9]\d{9}$`。历史不合规数据可读；保存时再拦。

## 3. API

### 3.1 用户 Schema / CRUD

- `UserCreate` / `UserUpdate` / `UserOut` 增加 `id_card: str | None`。
- `GET /api/v1/users`、`GET /api/v1/users/{user_id}`、创建、更新均读写该字段。
- 权限与数据范围规则不变。

### 3.2 详情聚合（增强 GET 用户）

`GET /api/v1/users/{user_id}` 在现有字段上增加：

```json
{
  "departments": [{ "id": "...", "name": "...", "is_primary": true }],
  "roles": [{ "code": "...", "name": "...", "is_primary": true }],
  "id_card": null,
  "created_by": "..."
}
```

- `departments`：主部门 + 兼职，来自 `user_departments` + `departments`。
- `roles`：主角色（`users.role`）+ `user_roles` 附加角色；`name` 取角色表展示名，缺失则回退 code。
- **列表** `GET /users`：返回 `id_card`，**不**填充 `departments`/`roles`（缺省 `[]` 或不序列化，前后端约定一致即可）。
- **详情** `GET /users/{id}`：必须填充 `departments`/`roles`。

### 3.3 会话 Tab（复用）

- `GET /api/v1/users/{user_id}/sessions?limit=10`
- `POST /api/v1/users/{user_id}/sessions/revoke-all`
- 协议不改；管理端消费即可。

### 3.4 操作日志 Tab（新增）

`GET /api/v1/users/{user_id}/audit-logs?page=1&page_size=20`

- 鉴权：与 `GET /users/{id}` 相同（能看该用户详情即可看其审计列表）。
- 过滤：`resource_id = user_id` **或** `actor_id = user_id`。
- action 前缀白名单（实现前扫现码固化，测试钉死）：至少 `user.`、`auth.`；若用户部门/角色变更写入为 `user.departments.*` / `user.roles.*` 则一并纳入；**不要**扫全表无前缀过滤。
- 返回项：`id, created_at, actor_id, actor_role, action, summary, result, client_ip, resource_type, resource_id`。
- 本期 **不做** 行内 diff 弹层（现有 `/audit-logs/{id}` 资源白名单过窄）；Tab 以 summary 列表为准。

## 4. 管理端 UI

### 4.1 列表 `/organization/users`

- 列增加：手机、身份证（空显示「—」）。
- 操作增加「查看」→ `/organization/users/{id}`。
- 新建/编辑抽屉：身份证选填；手机 11 位校验文案。

### 4.2 详情 `/organization/users/[user_id]`

路径：`admin-web/src/app/(admin)/organization/users/[user_id]/page.tsx`（D48：页内禁止再包 `AdminLayout`）。

**顶栏**

- 返回列表；头像占位（显示名首字）；显示名 / `@username` / 工号 / 状态 Tag。
- 按钮：编辑、重置密码、启停、标记离职（按角色显隐，逻辑对齐列表页）。

**Tab**

| Tab | 内容 |
|---|---|
| 基本信息 | Descriptions：手机、邮箱、身份证、职位、入职、创建人/时间、最后登录/IP |
| 部门与角色 | 主部门高亮 + 兼职；主角色 + 附加角色 |
| 会话历史 | 表：时间 / IP / User-Agent；「注销全部会话」二次确认 |
| 操作日志 | 表：时间 / 操作者 / action / summary / 结果 / IP；分页 |

**编辑**：详情页内嵌编辑抽屉（优先），保存成功刷新详情；少跳回列表。

**404**：用户不存在时壳内提示 + 回列表链接。

## 5. 测试要点

1. 创建/更新：合法 `id_card`、空、非法格式、重复冲突。
2. `GET` 详情含 `departments` / `roles` / `id_card`。
3. `GET .../audit-logs` 仅返回与该用户相关记录；无权限 403。
4. 会话列表与 revoke-all 回归（已有测可复用/补管理端契约）。
5. 管理端：列表列与详情四 Tab 冒烟（手工或现有前端测约定）。

## 6. 风险与应对

| 风险 | 应对 |
|---|---|
| 明文身份证合规敏感 | 仅管理端鉴权可见；后续可开脱敏/加密专项 |
| 审计 action 命名不齐导致日志 Tab 空 | 实现前扫 `record(` 用户域 action；白名单与种子测对齐 |
| GET 详情变重 | 列表不带 departments/roles；仅详情聚合 |
| Docker API 未热更 | 迁移 + `docker cp` / 重启 `zeroagent-api`（端口仍固定 8000） |

## 7. 验收清单

- [ ] 迁移 `0041` 已升；库有 `id_card`
- [ ] 管理端可建/改身份证；重复被拒
- [ ] 列表可见手机、身份证；可点「查看」进详情
- [ ] 详情四 Tab 均有数据或空态；会话可注销全部
- [ ] 操作日志可见该用户相关审计（至少 user/auth 类）
- [ ] CHECKPOINT 已更新

## 8. 裁定摘要

| 项 | 裁定 |
|---|---|
| 字段范围 | 仅 `id_card`（手机已有，加强校验与展示） |
| 必填/唯一 | 选填；有值唯一 |
| 展示 | 管理端明文 |
| 详情 | 方案 3：顶栏 + 四 Tab 全做 |
