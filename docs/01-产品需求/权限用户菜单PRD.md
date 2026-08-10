# 权限·用户·菜单管理 PRD（Org-Auth PRD）

> 版本 **v1.0.4** | 2026-08-10
>
> **定位**：本文件是 `PRD.md` 第二章「用户角色与权限模型」+ 第十二章 12.1.2「管理端菜单」的**专项细化与实现方案**，与 `PRD.md`、`知识库PRD.md` 并列；冲突时以**主 PRD 第二章 / 第十六章**为准。  
> **白名单**：已列入 `docs/05-开发指南/文档白名单与废止清单.md`（v1.0.3+，含本版）。  
> **交付口径（2026-08-10 裁定 9A′+6A′）**：§6.8–6.12、§9 深化 UI **保留为本期规格**，但按 Task **分期交付**；验收以「实现状态表 + 当前 Task」为准，**禁止**将全文一次扫完当作已上线。
>
> **适用范围（对齐现仓路径）**：
> - 后端：`src/app/core/actor.py`、`src/app/api/v1/auth.py`、`users.py`、`roles.py`、`menus.py`、`departments.py`、`me.py`；模型 `src/app/models/user.py` / `department.py` / `role.py` / `menu.py`
> - 前端：`admin-web/src/app/(admin)/**`（业务页）、`admin-web/src/app/(admin)/layout.tsx`（持久壳）、`admin-web/src/components/AppNav.tsx`、`web/src/app/profile/**`；登录/403 在 `(admin)` 外
> - 数据：MySQL `users` / `departments` / `user_departments` / `roles` / `user_roles` / `menus` / `role_menu_permissions` / `role_data_scopes`（**无**独立 `role_permissions` 表；`user_sessions` 表为 **M2**）
>
> **字段/角色码（强制对齐现码）**：显示名用 `name`（不用 `display_name`）；主角色用 `role`（不用 `primary_role`）；部门管理员码为 **`department_admin`**（不用 `dept_admin`）。
>
> **回溯基础**：主 PRD v0.8.1 第二章与 12.1.2 / D48；2026-08-10 与现码对齐裁定（见文首「裁定纪要」与 §十七）。

### 裁定纪要（2026-08-10）

| # | 结论 |
|---|---|
| 1 | 角色码统一 `department_admin` |
| 2 | 字段统一 `name` / `role` |
| 3 | v1.0 Session = **Starlette SessionMiddleware**；Redis/DB 会话审计 → **M2** |
| 4 | 平台管理员：可重置密码、换部门；**换角色 / 角色菜单·数据范围仅超管** |
| 5 | v1.0 **坚持菜单树**（种子须补 `parent_code`；现扁平种子视为待迁移） |
| 6 | §6.8–6.12、§9 重 UI **保留本期规格**，Task 分期交付（6A′） |
| 7 | 部门管理员本部门用户只读 → **M1.5**（非 M1 阻塞） |
| 8 | `terminated` **超管可恢复** → `active`（清 `deleted_at`） |
| 9 | 对齐本文后进白名单（9A′） |
| 10 | 文首维护「实现状态」表 |
| 11 | **管理端持久壳（对齐主 PRD D48）**：业务页禁止再包侧栏；菜单 path 必有 `(admin)` 页或占位；壳内 404 |

### 实现状态（相对 v1.0.4 规格，2026-08-10）

| 能力 | 状态 | 说明 |
|---|---|---|
| 用户/角色/部门/菜单表 + 迁移种子 | **已有** | `0031` + `0032_menu_tree_parents` 补树形 `parent_code` |
| 用户/角色/部门 CRUD API | **已有（M1）** | 创建写 `extra_roles`；部门不存在 → 422；组织 API `require_menu` |
| 启停 | **已有** | `PATCH /api/v1/users/{id}/status` |
| 重置密码 / 换部门 / 换角色 | **已有（M1）** | 平台可重置密码+换部门；换角色仅超管；自助改密清 Session |
| `load_actor` + Redis Actor 缓存 | **已有（M1）** | `resolve_actor` 接通；`get_actor` 优先 `request.state.actor`；生产无 Session 空身份 |
| `require_menu` / 菜单按角色过滤 | **已有（M1）** | `permissions.require_menu`；`/menus` `/menus/tree` 按 Actor 过滤 |
| 动态侧栏（读 `/menus`） | **已有（M1）** | `AppNav` 拉 `/api/v1/menus/tree?app=admin`；分组折叠+整栏收窄 |
| 管理端持久壳（D48） | **已有** | `(admin)/layout` 挂壳；页内无 `AdminLayout`；`[...slug]`/`not-found` 壳内 404；prompts 等占位 |
| 菜单树种子 + 树编辑 UI | **部分** | 树形种子已补；角色菜单树勾选 UI 仍为现有列表+Modal |
| §9 详情/向导/快捷键等 | **未接** | 规格保留，分期；现为列表+Modal |
| 组织域审计 22 类 | **部分（M1 最小集）** | login/logout、user.* 关键、`role.menu.put`、`department.create` → `config_audit_logs` |
| Redis/`user_sessions` 会话库 | **部分（M2 第一刀）** | `user_sessions` + `last_login_at`；登录写入；列表/注销全部；`resolve_actor` 吊销校验；改密/重置/停用/离职踢人 |
| 部门管理员本部门用户只读 | **已有（M1.5）** | 用户列表/详情按主+兼职过滤；部门列表同范围只读（`viewer.read_only`）；写仍 403；种子 `0033`/`0034` |
| 离职恢复 | **已有（M1）** | `POST /api/v1/users/{id}/restore`（仅超管） |

### 交付分期（本期规格 ≠ 一次验收）

| 波次 | 内容 | 验收焦点 |
|---|---|---|
| **M1** | `get_actor`↔`load_actor`；`require_menu`；menus 过滤；动态侧栏；用户契约修洞；平台重置密码/换部门；超管换角色/菜单；菜单树种子；列表+Modal 可用；审计最小集 | US-AU-01/02/03/05；实现状态表中 M1 项转「已有」 |
| **M1.5** | 部门管理员本部门用户只读；数据范围在组织列表的首个消费者 | US-AU-04 |
| **M2** | Redis/DB 会话审计与踢人；§6.8–6.12 性能/演练落地；§9 详情/向导/预览等深化；Prometheus 全套 | 非 M1 阻塞 |
| **已排除出工程** | SSO/MFA/LDAP/角色继承/字段级权限（见 §1.2 / §12.2） | — |

---

## 文档版本

| 版本 | 日期 | 主要变更 |
|---|---|---|
| v1.0.4 | 2026-08-10 | §9.0 管理端持久壳与新建页规范（对齐主 PRD D48）；裁定 11；实现状态补壳项 |
| v1.0.3 | 2026-08-10 | 与现码对齐裁定；角色码/字段/Session/权限边界；实现状态表；9A′+6A′ 分期交付；terminated 可恢复；进白名单 |
| v1.0.2 | 2026-08-06 | §9 admin-web 页面深化（9.4–9.18） |
| v1.0.1 | 2026-08-06 | §6 权限校验链路深化（6.6–6.12） |
| v1.0.0 | 2026-08-06 | 初版 |

---

## 一、范围与术语

### 1.1 范围（In Scope）

| 项 | 包含 |
|---|---|
| 用户管理 | 账号 CRUD / 启停 / 重置密码 / 多部门归属 / 离职转岗 |
| 角色管理 | 内置 6 类角色 + 自定义角色；菜单权限 + 数据范围 |
| 菜单管理 | 顶级菜单 / 二级菜单 / 三级菜单 / 角色菜单权限分配 |
| 组织（部门）管理 | 树形部门 / 主部门 / 兼职部门 / 部门启停 |
| 权限校验 | Actor 注入 / 中间件链 / 双端一致 / 即时生效 |
| 会话管理 | v1.0：Starlette Session（8h，HttpOnly Cookie，多端不限制）；Redis/DB 会话审计为 M2 |
| 审计 | 登录 / 密码修改 / 用户变更 / 角色变更 / 权限变更；写入 `config_audit_logs`（沿用主 PRD 7.3） |
| admin-web | 组织权限模块：M1 列表+Modal 必达；§9 深化按 Task 分期 |

### 1.2 不在本文件范围（Out of Scope）

- ❌ 第三方登录 / SSO / OAuth（首期自建账号，延后）
- ❌ 密码复杂度策略升级（首期极简，沿用主 PRD 3.2）
- ❌ 密码找回 / 邮箱验证（v1.1 评估）
- ❌ MFA / 二次认证（首期不做，沿用主 PRD 3.2）
- ❌ 域账号 / LDAP 同步（v1.1+）
- ❌ 工号自助绑定（无 IM，沿用主 PRD 13.1 D8）
- ❌ admin-web 主题切换、视觉规范（沿用主 PRD 12.1.4）
- ❌ 知识库 / Agent / 工作流 / 记忆白名单等业务模块的权限（各子 PRD 自管）

### 1.3 术语

| 术语 | 含义 |
|---|---|
| Actor | 当前请求的身份上下文（user_id / department_id / role / is_platform_admin），注入到请求生命周期 |
| RBAC | Role-Based Access Control，基于角色的访问控制 |
| 数据权限 | 决定 Actor 能访问哪些**数据行**（如本部门 / 全公司 / 自建） |
| 菜单权限 | 决定 Actor 能看到哪些**菜单项 / 路由** |
| 功能权限 | 决定 Actor 能调用哪些**操作**（如 `kb.create` / `user.delete`） |
| 数据范围 | 数据权限的具体范围（all / department / self / custom） |
| 会话（Session） | v1.0 为 Starlette 签名 Cookie Session；标识当前登录；非 Redis `sid` |
| 即时生效 | 角色 / 权限变更后，**已登录用户**的下一请求立即生效，无需重新登录 |

---

## 二、角色模型（沿用主 PRD §2.1 + 细化）

### 2.1 六类角色定义（沿用主 PRD）

| 角色代码 | 名称 | 典型用户 | 核心能力 |
|---|---|---|---|
| `employee` | 普通员工 | 全员 | 对话 / 查看自己历史 |
| `expert` | 业务专家 | HR/财务/IT/法务 | 上传编辑授权 KB / 创建工作流 / 领域技能 |
| `agent_dev` | Agent 开发者 | IT/业务骨干 | 编排工作流 / 配置 Agent 与技能 |
| `department_admin` | 部门管理员 | 部门 IT/BP | 本部门用量与告警 / 用户只读 / 对话脱敏只读 |
| `platform_admin` | 平台管理员 | IT 管理员 | 用户/权限/审计/计费 / 创建 Agent / 记忆白名单 / L2 关键词 |
| `super_admin` | 超级管理员 | CTO/IT 总监 | 全部 + 系统配置 |

### 2.2 角色可配置边界

| 决策 | 内容 |
|---|---|
| **可创建自定义角色** | ✅（沿用主 PRD 2.2） |
| **可删除内置角色** | ❌ 内置 6 类不可删，可停用 |
| **可修改内置角色权限** | 🟡 仅 `super_admin` 可改；其他角色可见只读 |
| **可绑定用户到自定义角色** | ✅（多个角色可叠加） |
| **角色层级** | ❌ 不引入角色继承（避免隐式权限） |

### 2.3 多角色叠加规则

- 一个用户可拥有**多个角色**（如 `expert` + `department_admin`）；
- 权限合并：**并集**（与 KB 权限一致）；
- 菜单显示：取所有角色的菜单并集；
- 数据范围：取所有角色范围的**最宽**（如 `all` 覆盖 `department`）。

### 2.4 主部门与兼职部门

- 一个用户有**唯一主部门**（`user_departments.is_primary=true`）；
- 0~N 个兼职部门；
- 主部门用于：成本分摊（沿用主 PRD 2.2）、部门管理员授权范围、对话权限范围。

---

## 三、用户管理

### 3.1 用户生命周期

```
创建（status=active） → 登录 → 使用 → 停用（status=disabled）
                          ↓                    ↕ 启用
                       重置密码 / 改部门·角色
                          ↓
                 离职（status=terminated，写 deleted_at）
                          ↓
            超管恢复 → active（清 deleted_at）（裁定 8）
```

| 状态 | 进入条件 | 离开条件 |
|---|---|---|
| `active` | 管理员创建 / 启用 / **超管从 terminated 恢复** | 管理员停用 / 标记离职 |
| `disabled` | 管理员停用 | 管理员启用 / 标记离职 |
| `terminated` | 超管标记离职 | **仅超管恢复** → `active` |

- 停用后**无法登录**，但历史数据保留（沿用主 PRD 3.3.4 / 13.5）；
- 离职后所有数据**保留原归属**（沿用主 PRD 13.5），供审计可查；恢复后须重新评估角色/部门（默认保持原值，超管可再改）。
- **禁止**：创建用户时若部门 ID 不存在则自动建部门（须 422）。

### 3.2 数据模型

#### `users` 表（对齐现码）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str(32) PK | `usr_<uuid16>` |
| username | str(64) unique | 登录凭证（不可改） |
| password_hash | str(255) | bcrypt 哈希 |
| name | str(100) | 显示名（主 PRD「姓名」） |
| employee_no | str(64) unique | 工号 |
| phone | str(32) | |
| email | str(255) | |
| position | str(100) | |
| hire_date | date | 入职日期 |
| main_department_id | str(32) | 主部门（与 `user_departments.is_primary` 一致） |
| role | str(32) | 主角色 code |
| status | str(20) | `active` / `disabled` / `terminated` |
| deleted_at | datetime? | 离职时写入；恢复时清空 |
| created_at / updated_at | datetime | |

> `last_login_at` / `created_by`：**M2 可选列**；v1.0 不强制。主部门唯一性靠应用层保证（每用户一条 `is_primary=true`）；部分唯一索引可后续补。

#### `user_departments` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| user_id | str(32) FK | |
| department_id | str(32) FK | |
| is_primary | bool | 主部门标记（应用层保证每用户至多 1 条 true） |
| joined_at | datetime | |

唯一约束：`uk_user_dept (user_id, department_id)`。

#### 会话存储（v1.0 / M2）

| 波次 | 方案 |
|---|---|
| **v1.0 / M1** | Starlette `SessionMiddleware`（签名 Cookie）；改密 / 重置密码 / 停用 / 恢复后须 **`request.session.clear()`** 并失效 Actor 缓存 |
| **M2** | 可选 Redis Session 索引 + `user_sessions` 表，支持会话列表 / 注销全部 |

### 3.3 API 接口

| Method | Path | 角色 | 说明 |
|---|---|---|---|
| POST | `/api/v1/auth/login` | 公开 | 用户名 + 密码；写入 Starlette Session |
| POST | `/api/v1/auth/logout` | 登录用户 | `session.clear()` |
| GET | `/api/v1/auth/me` | 登录用户 | 当前用户摘要（M1 起逐步含 menus / extra_roles） |
| GET | `/api/v1/users` | `platform_admin` / `super_admin`（M1.5 起含本部门只读的 `department_admin`） | 分页 + 筛选 |
| POST | `/api/v1/users` | `platform_admin` / `super_admin` | 创建；须写 `user_roles`（含 `extra_roles`）；部门不存在 → 422 |
| GET | `/api/v1/users/{user_id}` | 管理员或本人 | 详情 |
| PUT | `/api/v1/users/{user_id}` | `platform_admin` / `super_admin` | 编辑（不可改 username / employee_no） |
| PATCH | `/api/v1/users/{user_id}/status` | `platform_admin` / `super_admin` | 启停：`active` / `disabled`（**现行路径**；勿再拆 enable/disable） |
| DELETE | `/api/v1/users/{user_id}` | `super_admin` | 标记 `terminated` + `deleted_at` |
| POST | `/api/v1/users/{user_id}/restore` | `super_admin` | 恢复：`terminated` → `active`，清 `deleted_at`（裁定 8；待实现） |
| POST | `/api/v1/users/{user_id}/reset-password` | `platform_admin` / `super_admin` | 重置密码；成功后清目标用户 Session + Actor（裁定 4） |
| PUT | `/api/v1/users/{user_id}/departments` | `platform_admin` / `super_admin` | 全量替换部门（裁定 4） |
| PUT | `/api/v1/users/{user_id}/roles` | **仅 `super_admin`** | 全量替换主角色 + 附加角色（裁定 4） |
| POST | `/api/v1/users/me/password` | 本人 | 改密；成功后清当前 Session |

### 3.4 管理后台页面（`/organization/users`）

> M1：**列表 + 新建/编辑 Modal** 必达。§9.5–9.7 详情/向导为同规格分期项，不阻塞 M1 验收。

#### 列表页

| 列 | 字段 |
|---|---|
| 用户名 | `username` |
| 显示名 | `name` |
| 工号 | `employee_no` |
| 主部门 | 主部门名 + 兼职部门数 |
| 角色 | 主角色徽标 + 附加角色 |
| 状态 | `active` / `disabled` / `terminated`（颜色徽标） |
| 最近登录 | `last_login_at`（有则显示；M2） |
| 操作 | 查看 / 编辑 / 重置密码 / 启停 /（超管）离职·恢复 |

- 筛选：状态、角色、部门、姓名 / 工号模糊搜索；
- 排序：创建时间 / 最近登录 / 用户名；
- 分页：20 / 50 / 100；
- 顶部操作：「新建用户」（仅超管 / 平台管理员）；
- 批量操作：批量启停（v1.1）。

#### 详情页 `/organization/users/[user_id]`

- 基本信息 / 部门归属 / 角色列表 / 会话历史 / 操作日志（来自 audit）。

#### 编辑抽屉

- 字段：`name` / phone / email / position / hire_date；
- 不可编辑：username / employee_no / password_hash（只能重置）；
- 主部门 + 兼职部门：树形多选 + 「主部门」单选标记；
- 角色：多选（含内置 + 自定义）。

### 3.5 Web 员工端入口（`/profile`）

- M1：查看资料（只读）+ 修改密码（接 `POST /api/v1/users/me/password`，成功清 Session）；
- M2+：自助改手机号/邮箱/显示名；登录历史随会话审计。

---

## 四、角色管理

### 4.1 内置 vs 自定义角色

| 类别 | 可创建 | 可删除 | 可改权限 |
|---|---|---|---|
| 内置 6 类 | ❌ | ❌（可停用） | 🟡 仅 `super_admin` |
| 自定义 | ✅（仅 `super_admin`） | ✅ | ✅（仅 `super_admin`） |

### 4.2 数据模型

#### `roles` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| code | str(32) PK | `employee` / `expert` / `agent_dev` / `department_admin` / `platform_admin` / `super_admin` / 自定义 code |
| name | str(64) | 显示名（可改） |
| description | str(255) | |
| is_builtin | bool | 内置不可删标志 |
| is_active | bool | 停用后用户仍持有但权限失效 |
| data_scope_default | str(16) | 默认数据范围：`all` / `department` / `self` |
| created_by | str(32) | |
| created_at | datetime | |

#### `user_roles` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| user_id | str(32) FK | |
| role_code | str(32) FK | |
| granted_by | str(32) | 授权人 |
| granted_at | datetime | |

唯一约束：`uk_user_role (user_id, role_code)`。

#### `role_menu_permissions` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| role_code | str(32) | |
| menu_code | str(64) | 菜单标识 |
| can_view | bool | 可见 |
| can_edit | bool | 可操作 |

> v1.0 简化为 "菜单可见性"，可编辑由"有可见性且是超管/平台管理员"叠加判断。

#### `role_data_scopes` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| role_code | str(32) | |
| scope_type | str(16) | `all` / `department` / `self` / `custom_departments` |
| scope_departments_json | text | 当 `custom_departments` 时填具体部门列表 |

### 4.3 权限粒度

| 粒度 | 维度 | 用途 |
|---|---|---|
| **菜单权限** | 哪些菜单可见 | 前端路由隐藏 + 后端路由守卫 |
| **数据范围** | 哪些数据行可访问 | 查询时 WHERE 注入 |
| **功能权限**（v1.1） | 哪些 action 可调用 | API 网关级校验 |

### 4.4 API 接口

| Method | Path | 角色 | 说明 |
|---|---|---|---|
| GET | `/api/v1/roles` | `platform_admin` / `super_admin` | 角色列表 |
| POST | `/api/v1/roles` | `super_admin` | 创建自定义角色 |
| GET | `/api/v1/roles/{code}` | `platform_admin` / `super_admin` | 角色详情 |
| PUT | `/api/v1/roles/{code}` | `super_admin` | 编辑（内置仅改 name/description） |
| DELETE | `/api/v1/roles/{code}` | `super_admin` | 删除自定义（不可删内置） |
| GET | `/api/v1/roles/{code}/menus` | `platform_admin` / `super_admin` | 角色菜单权限 |
| PUT | `/api/v1/roles/{code}/menus` | **仅 `super_admin`** | 全量替换菜单权限（裁定 4） |
| GET | `/api/v1/roles/{code}/data-scopes` | `platform_admin` / `super_admin` | 角色数据范围 |
| PUT | `/api/v1/roles/{code}/data-scopes` | **仅 `super_admin`** | 全量替换数据范围（裁定 4） |

### 4.5 管理后台页面（`/organization/roles`）

#### 角色列表

| 列 | 字段 |
|---|---|
| 角色编码 | `code`（内置徽标 + 自定义徽标） |
| 角色名 | `name` |
| 描述 | `description` 截断 |
| 用户数 | 该角色下的用户数 |
| 默认数据范围 | `data_scope_default` |
| 状态 | `active` / 停用 |
| 操作 | 查看 / 编辑 / 启停 / 删除 |

#### 角色权限编辑抽屉

- **菜单权限 Tab**：
  - 树形菜单列表（来自 `menus` 表）；
  - 复选框勾选可见；
  - 实时预览"该角色登录后看到的菜单结构"（右侧缩略图）；
- **数据范围 Tab**：
  - 单选：`all` / `department` / `self` / `custom_departments`；
  - `custom_departments` 时显示部门树多选；
- **用户 Tab**（只读）：列出该角色下的用户；
- 保存：写审计 `role.update` / `role.menu.put` / `role.data_scope.put`。

---

## 五、菜单管理

> **裁定 5**：v1.0 坚持菜单树。当前迁移种子多为 `parent_code=null` 扁平数据，**M1 须补树形种子**并让侧栏/角色菜单编辑消费树。前端为 Next.js App Router（非 Vue Router）；§5.4 伪代码仅示意逻辑。

### 5.1 菜单结构

admin-web 与 web（员工端）**共享一套菜单定义**，按角色过滤：

```
┌─ 顶级菜单（type=top）
│  ├─ 一级菜单（type=group）   ← 顶级菜单下的展开项
│  │  ├─ 二级菜单（type=menu）
│  │  └─ 二级菜单（type=menu）
│  └─ 一级菜单
└─ 顶级菜单
```

| 菜单元素 | 字段 | 说明 |
|---|---|---|
| 顶级菜单 | `code` / `name` / `icon` / `sort` / `app`（admin-web / web / both） | 左侧一级 |
| 一级菜单 | 同上 + `parent_code` | 顶级下的展开分组 |
| 二级菜单 | 同上 + `parent_code` + `path`（路由） | 实际可点击页 |
| 三级菜单 | （v1.1） | 详情页 Tab |

### 5.2 数据模型

#### `menus` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| code | str(64) PK | 菜单唯一标识（如 `knowledge` / `org.users`） |
| name | str(64) | 显示名（中文） |
| icon | str(64) | Ant Design Icon 名 |
| path | str(255) | 路由路径（顶级为 `/`） |
| parent_code | str(64)? | 父菜单 code |
| sort | int | 同级排序 |
| app | str(16) | `admin` / `web` / `both` |
| is_visible | bool | 全局是否可见（与角色权限独立） |
| is_builtin | bool | 内置菜单不可删 |
| created_at | datetime | |

### 5.3 菜单权限分配流程

```
menus（菜单定义）
   ↓ 全量
role_menu_permissions（角色 → 菜单可见性）
   ↓ 按用户角色合并
用户登录后 → 加载可见菜单树
```

- 角色有 `menus: ['knowledge', 'org.users', 'overview']`；
- 多个角色取**并集**；
- 全局 `is_visible=false` 的菜单对所有角色不可见。

### 5.4 路由守卫

#### 前端

```ts
// 路由 meta 标注菜单 code
const routes = [
  { path: '/knowledge', meta: { menuCode: 'knowledge' }, component: KBList },
];

// 守卫：未授权 → 跳 403
router.beforeEach((to, _, next) => {
  const menuCode = to.meta.menuCode;
  if (menuCode && !actor.menus.includes(menuCode)) {
    next('/403');
  } else {
    next();
  }
});
```

#### 后端

```python
# FastAPI Depends 注入
@router.get("/api/v1/users")
async def list_users(actor: Actor = Depends(require_menu("org.users"))):
    ...
```

- 后端兜底，不依赖前端隐藏；
- 前端隐藏只为体验，**安全边界在后端**（沿用主 PRD 12.1.1 安全硬约束）。

### 5.5 菜单变更即时生效

- 角色菜单变更 → 写审计 `role.menu.put`；
- 清 Redis 缓存 `actor:m:{user_id}`（用户菜单缓存）；
- 用户下一请求自动重载菜单；
- 已打开页面刷新后失效菜单立即隐藏。

### 5.6 admin-web 菜单结构（v1.0）

| 顶级 | 一级 | 二级 | code |
|---|---|---|---|
| 总览 | 控制台概览 | — | `overview` |
| 智能体 | Agent 管理 | — | `agents` |
| 智能体 | 模型与服务商 | — | `models` |
| 智能体 | Prompt 模板 | — | `prompts` |
| **知识与编排** | **知识库** | — | `knowledge` |
| 知识与编排 | 工作流 | — | `workflows` |
| 知识与编排 | 知识图谱 | — | `kg` |
| **系统治理** | 记忆抽取白名单 | — | `system.memory-fields` |
| 系统治理 | L2 关键词规则 | — | `system.l2-keywords` |
| 系统治理 | 系统人格 | — | `system.persona` |
| 系统治理 | 敏感词 | — | `system.sensitive-words`（规划） |
| **组织权限** | **用户管理** | — | `org.users` |
| 组织权限 | 角色权限 | — | `org.roles` |
| 组织权限 | 部门管理 | — | `org.departments` |
| **运维审计** | 用量成本 | — | `operations.usage` |
| 运维审计 | 通知告警 | — | `operations.alerts` |
| 运维审计 | 配置审计 | — | `operations.audit` |

> 知识库模块的 5 大二级入口详见 `知识库PRD.md §13.3.2`（KB 管理 / 文档管理 / 权限与可见性 / 分类管理 / 审计与缓存）。

### 5.7 web（员工端）菜单结构（v1.0）

| 顶级 | 二级 | code |
|---|---|---|
| 系统对话 | — | `chat` |
| 个人中心 | 资料 | `profile` |
| 个人中心 | 修改密码 | `profile.password` |

---

## 六、权限校验链路

> **实现状态**：`Actor` / `load_actor` / Redis 缓存代码已有，但请求入口 `get_actor` **尚未调用** `load_actor`；`require_menu` **未实现**。M1 首要任务是接通主链路。  
> **§6.8–6.12**：保留为本期规格（裁定 6 / 6A′），按 Task 分期落地，**不作为 M1 一次性验收项**。

### 6.1 Actor 数据模型

```python
@dataclass
class Actor:
    user_id: str
    username: str
    role: str                      # 主角色 code
    extra_roles: list[str]         # 附加角色
    department_id: str | None      # 主部门
    extra_department_ids: list[str]
    data_scope: str                # all / department / self / custom
    scope_departments: list[str]
    menus: list[str]               # 可见菜单 code 列表
    is_platform_admin: bool
    is_super_admin: bool
```

注入位置：
- `src/app/core/actor.py` 定义；
- FastAPI Depends 通过 `get_actor(request)` 注入；
- Request context（`request.state.actor`）。

### 6.2 中间件链（请求生命周期）

```
HTTP Request
   ↓
[1] Session 中间件（auth.py）
   ↓ 解析 Cookie → user_id
[2] Actor 注入中间件
   ↓ 加载用户 / 角色 / 部门 / 菜单 → request.state.actor
[3] 路由守卫（FastAPI Depends）
   ↓ require_menu(menu_code) / require_role(role_code)
[4] 业务处理器
   ↓ 使用 actor.data_scope 注入数据过滤
   ↓
HTTP Response
```

### 6.3 双端一致性

| 维度 | 前端 | 后端 |
|---|---|---|
| 入口隐藏 | 菜单 / 按钮不渲染 | — |
| 路由守卫 | `beforeEach` 跳 403 | — |
| API 校验 | — | `Depends(require_menu)` / `Depends(require_role)` |
| 数据范围 | 不可见 | WHERE 子句注入 actor 范围 |

**规则**：前端隐藏只为体验，**后端校验为安全边界**。

### 6.4 即时生效（Redis 缓存）

```
用户登录 → Actor 序列化 → Redis SET actor:m:{user_id} TTL 30min
请求时 → 命中缓存直接用；未命中重新加载
权限变更 → DEL actor:m:{user_id}（精准失效）
```

- TTL 30 分钟兜底（即使没主动失效，最多 30 分钟自动重载）；
- 主动失效场景：角色变更、菜单权限变更、停用用户、修改部门。

### 6.5 数据范围注入

```python
# 查询示例
async def list_documents(db, actor):
    if actor.data_scope == "all":
        return await db.execute(select(Document))
    elif actor.data_scope == "department":
        return await db.execute(
            select(Document).where(Document.kb_id.in_(
                kb_ids_in_departments(actor.department_id)
            ))
        )
    elif actor.data_scope == "self":
        return await db.execute(
            select(Document).where(Document.created_by == actor.user_id)
        )
```

### 6.6 完整 Actor 加载代码契约

#### 6.6.1 数据类定义（src/app/core/actor.py）

```python
from dataclasses import dataclass, field, asdict
from typing import Literal
import json

DataScope = Literal["all", "department", "self", "custom"]

@dataclass(frozen=True)
class Actor:
    user_id: str
    username: str
    display_name: str                      # 缓存字段；来源 User.name
    role: str                              # 主角色 code（User.role）
    extra_roles: tuple[str, ...]           # 附加角色（不可变）
    department_id: str | None              # 主部门
    extra_department_ids: tuple[str, ...]
    data_scope: DataScope
    scope_departments: tuple[str, ...]     # 当 data_scope='custom' 时填具体部门
    menus: tuple[str, ...]                 # 可见菜单 code 列表
    is_platform_admin: bool
    is_super_admin: bool
    session_id: str                        # 与 Starlette session 关联的标识（可为 session 内随机 nonce）
    loaded_at: int                         # 加载时间戳（ms）

    def to_cache_dict(self) -> dict:
        """转 Redis 可序列化 dict。"""
        return asdict(self)

    @classmethod
    def from_cache_dict(cls, d: dict) -> "Actor":
        """从 Redis 反序列化；缺失字段降级为默认值。"""
        return cls(
            user_id=d["user_id"],
            username=d["username"],
            display_name=d.get("display_name") or d.get("name") or "",
            role=d["role"],
            extra_roles=tuple(d.get("extra_roles") or ()),
            department_id=d.get("department_id"),
            extra_department_ids=tuple(d.get("extra_department_ids") or ()),
            data_scope=d.get("data_scope", "self"),
            scope_departments=tuple(d.get("scope_departments") or ()),
            menus=tuple(d.get("menus") or ()),
            is_platform_admin=bool(d.get("is_platform_admin")),
            is_super_admin=bool(d.get("is_super_admin")),
            session_id=d.get("session_id", ""),
            loaded_at=int(d.get("loaded_at") or 0),
        )

    def has_role(self, role_code: str) -> bool:
        return role_code == self.role or role_code in self.extra_roles

    def has_menu(self, menu_code: str) -> bool:
        return menu_code in self.menus or self.is_super_admin

    def in_department(self, dept_id: str) -> bool:
        if self.data_scope == "all":
            return True
        if self.data_scope == "self":
            return False
        if self.data_scope == "department":
            return dept_id == self.department_id or dept_id in self.extra_department_ids
        if self.data_scope == "custom":
            return dept_id in self.scope_departments
        return False
```

#### 6.6.2 Actor 加载流程

```python
# src/app/core/actor.py
async def load_actor(user_id: str, session_id: str) -> Actor:
    """按优先级加载 Actor：Redis 缓存 → DB 重建 → Redis 回写。"""
    cached = await redis_get(f"actor:m:{user_id}")
    if cached and cached.get("session_id") == session_id:
        metric_inc("actor_cache_hit_total", result="hit")
        return Actor.from_cache_dict(cached)

    metric_inc("actor_cache_hit_total", result="miss")
    actor = await _rebuild_actor_from_db(user_id, session_id)
    await redis_set(f"actor:m:{user_id}", actor.to_cache_dict(), ttl=1800)
    return actor


async def _rebuild_actor_from_db(user_id: str, session_id: str) -> Actor:
    """DB 重建 Actor（含数据范围、菜单权限并集）。"""
    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        raise ActorInactiveError()

    # 1. 加载所有角色（含主角色 + user_roles 附加）
    roles = await db.execute(
        select(Role).join(UserRole, UserRole.role_code == Role.code)
        .where(UserRole.user_id == user_id, Role.is_active.is_(True))
    )
    role_rows = roles.scalars().all()

    # 2. 主部门 + 兼职部门
    depts = await db.execute(
        select(UserDepartment).where(UserDepartment.user_id == user_id)
    )
    dept_rows = depts.scalars().all()
    primary_dept = next((d for d in dept_rows if d.is_primary), None)

    # 3. 菜单权限并集
    role_codes = [r.code for r in role_rows]
    menus = await _load_menus_union(role_codes)
    is_super = "super_admin" in role_codes
    is_platform = "super_admin" in role_codes or "platform_admin" in role_codes

    # 4. 数据范围取所有角色最宽
    data_scope = _resolve_data_scope(role_rows)

    return Actor(
        user_id=user.id,
        username=user.username,
        display_name=user.name,
        role=user.role,
        extra_roles=tuple(rc for rc in role_codes if rc != user.role),
        department_id=primary_dept.department_id if primary_dept else None,
        extra_department_ids=tuple(
            d.department_id for d in dept_rows if not d.is_primary
        ),
        data_scope=data_scope,
        scope_departments=_resolve_scope_departments(role_rows, user),
        menus=menus,
        is_platform_admin=is_platform,
        is_super_admin=is_super,
        session_id=session_id,
        loaded_at=int(time.time() * 1000),
    )
```

### 6.7 Redis 缓存 Key 体系

| Key | 类型 | TTL | 内容 | 失效场景 |
|---|---|---|---|---|
| `za:actor:m:{user_id}` | JSON | 30 min ± 抖动 | Actor 完整快照（**现码 Key**） | 角色变更 / 菜单变更 / 用户停用 / 重置密码 |
| `za:actor:menu:{user_id}` | set | 30 min | 可选：菜单 code 列表（可并入 Actor） | 角色菜单权限变更 |
| `za:actor:perm:{user_id}` | hash | 30 min | 功能权限映射（**v1.1+**） | 角色权限变更 |
| `session:*` | — | — | **M2**：Redis Session 索引；v1.0 不使用 |

**Redis Key 命名规范**：现码前缀 `za:`；`{namespace}:{type}:{id}`；避免散落。

**Key 体积控制**：
- `actor:m:{user_id}` 单条 ≤ 2KB（Actor 字段有限）；
- `session:s:{session_id}` 单条 ≤ 0.5KB；
- 不缓存大对象（如文档列表），避免 Redis 膨胀。

### 6.8 缓存防护（击穿 / 雪崩 / 热点）

> **分期**：规格保留；落地排在 Actor 主链路接通之后的独立 Task，不阻塞 M1 功能验收。

#### 6.8.1 击穿防护（单个 Key 失效瞬间并发重建）

```python
# 单飞锁（single-flight）：同一 user_id 只允许一个重建任务
_flight_locks: dict[str, asyncio.Lock] = {}

async def load_actor(user_id: str, session_id: str) -> Actor:
    cached = await redis_get(f"actor:m:{user_id}")
    if cached:
        return Actor.from_cache_dict(cached)

    lock = _flight_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        # 双重检查：获取锁后再查一次缓存
        cached = await redis_get(f"actor:m:{user_id}")
        if cached:
            return Actor.from_cache_dict(cached)
        actor = await _rebuild_actor_from_db(user_id, session_id)
        await redis_set(f"actor:m:{user_id}", actor.to_cache_dict(), ttl=1800)
        return actor
```

#### 6.8.2 雪崩防护（大量 Key 同时失效）

- **过期时间打散**：每个 Actor 缓存 TTL 在 1800s ± 300s 随机抖动；
- **预热**：详见 §6.9；
- **降级**：Redis 不可用时走 DB 直接重建（性能下降但功能可用）；
- **熔断**：连续 N 次 DB 重建失败 → 短路返回 503，不打挂数据库。

#### 6.8.3 热点防护（超管等高频角色）

- 超管 Actor 缓存**永不过期**（手动失效），Redis 写入次数降到最低；
- 平台管理员同理 TTL 延长至 2 小时；
- 普通用户 TTL 30 分钟。

#### 6.8.4 Redis 故障兜底

```python
class RedisActorCache:
    async def get(self, user_id: str) -> dict | None:
        try:
            return await redis_get(f"actor:m:{user_id}")
        except RedisError:
            metric_inc("actor_cache_redis_error_total")
            return None  # 降级：返回 None 走 DB 重建

    async def set(self, user_id: str, actor_dict: dict):
        try:
            await redis_set(f"actor:m:{user_id}", actor_dict, ttl=1800)
        except RedisError:
            # 写失败不阻断流程（下次请求再重试）
            metric_inc("actor_cache_redis_set_fail_total")
```

### 6.9 缓存预热策略

> **分期（M2）**。M1 仅要求：登录成功或首次受保护请求时写入 Actor 缓存；权限变更时 `DEL za:actor:m:{user_id}`。

| 时机 | 范围 | 实施 |
|---|---|---|
| **登录成功后（M1）** | 当前用户 | 写入 Actor 缓存 |
| **权限变更后（M1）** | 受影响用户 | 批量 `DEL za:actor:m:{user_id}` |
| **应用启动（M2）** | 活跃用户 Top N | 可选预热 |
| **定时任务（M2）** | 活跃用户 Top N | 可选 Celery beat |

### 6.10 中间件 / 依赖注入（完整生命周期）

> v1.0 对齐现码：使用 **Starlette SessionMiddleware**。下列为**目标伪代码**（可用 Depends 代替独立 middleware 文件）。生产环境**禁止**未登录回落 `usr_system`。

```python
# 目标：Session → load_actor → request.state.actor → Depends 路由守卫
async def inject_actor(request: Request, call_next):
    request_id = generate_request_id()
    user_id = request.session.get("user_id")
    if not user_id:
        # 公开路由白名单外 → 401；禁止默认 usr_system
        return JSONResponse(401, fail(40101, "未登录"))

    session_id = request.session.get("session_nonce") or user_id
    try:
        actor = await load_actor(user_id, session_id)
    except ActorInactiveError:
        request.session.clear()
        return JSONResponse(401, fail(40101, "账号已停用"))

    request.state.actor = actor
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
```

**FastAPI Depends 路由守卫**：

```python
# src/app/core/permissions.py
from fastapi import Depends, Request, HTTPException

def require_menu(menu_code: str):
    """路由级菜单权限守卫。"""
    async def _check(request: Request) -> Actor:
        actor: Actor = request.state.actor
        if not actor.has_menu(menu_code):
            metric_inc("permission_check_total", result="deny")
            raise HTTPException(403, fail(40301, f"无菜单权限: {menu_code}"))
        metric_inc("permission_check_total", result="pass")
        return actor
    return _check


def require_role(*role_codes: str):
    """角色守卫：满足任一角色即通过。"""
    async def _check(request: Request) -> Actor:
        actor: Actor = request.state.actor
        if not any(actor.has_role(rc) for rc in role_codes):
            raise HTTPException(403, fail(40302, f"需角色: {role_codes}"))
        return actor
    return _check


# 业务路由使用示例
@router.get("/api/v1/users", dependencies=[Depends(require_menu("org.users"))])
async def list_users(request: Request, db = Depends(get_db)):
    actor: Actor = request.state.actor
    # 数据范围过滤
    if actor.data_scope == "department":
        stmt = select(User).join(UserDepartment).where(
            UserDepartment.department_id == actor.department_id
        )
    elif actor.data_scope == "self":
        stmt = select(User).where(User.id == actor.user_id)
    else:
        stmt = select(User)
    return await db.execute(stmt)
```

### 6.11 路由守卫与功能权限

| 守卫层级 | 用途 | 实现 |
|---|---|---|
| **菜单级** | 路由是否可达 | `require_menu(menu_code)` |
| **角色级** | 是否需要特定角色 | `require_role(role_codes)` |
| **资源级** | 单资源归属检查 | 业务处理器内显式 |
| **数据范围** | 行级过滤 | `actor.data_scope` 注入 WHERE |

**资源级守卫示例**：

```python
@router.get("/api/v1/users/{user_id}")
async def get_user(user_id: str, request: Request, db = Depends(get_db)):
    actor: Actor = request.state.actor
    # 自己可看自己；管理员可看本部门；超管可看全部
    if user_id == actor.user_id:
        return await db.get(User, user_id)
    if actor.is_super_admin or actor.is_platform_admin:
        return await db.get(User, user_id)
    if actor.in_department(target_user.department_id):
        return await db.get(User, user_id)
    raise HTTPException(403, fail(40303, "数据范围超出"))
```

### 6.12 性能基准与故障演练

> **分期（M2）**：规格目标如下；M1 不强制 Locust/演练清单一次过完。

#### 6.12.1 性能基准（Locust 脚本目标）

| 场景 | 目标 P95 |
|---|---|
| 登录（含 Actor 首次加载 + 缓存写入） | < 500ms |
| 已登录用户访问菜单内接口（缓存命中） | < 50ms（含业务 5ms） |
| 1000 并发登录 | 无错误 |
| Redis 故障 → DB 兜底 | P95 < 200ms |

#### 6.12.2 故障演练清单

| 演练 | 步骤 | 验收 |
|---|---|---|
| Redis 完全挂 | 停 Redis → 所有接口降级到 DB | 接口 200，DB 未打挂 |
| Redis 网络抖动 | 注入 50ms 延迟 | 单飞锁生效，不重复重建 |
| 大量用户同时登录 | 1000 并发 | 登录成功率 ≥ 99.9% |
| 用户角色变更后旧缓存未失效 | 主动 DEL + 被动 TTL | 最长 30 分钟生效，主动失效 < 1s |
| 单 user_id 缓存击穿 | 模拟 key 过期 + 100 并发 | DB 只查一次 |
| Session 过期但 Actor 缓存仍在 | 模拟时间流逝 | Session 中间件拦截，Actor 不被使用 |

---

## 七、组织（部门）管理

### 7.1 部门模型

```
根部门
├── 人事部（HR）
│   ├── 人事一部
│   └── 人事二部
├── 财务部
├── IT 部
│   ├── 应用开发组
│   └── 运维组
└── ...
```

- 树形结构，深度不限；
- 每个用户恰好 1 个主部门 + 0~N 个兼职部门；
- 部门可启用 / 停用（停用后用户仍可见但新文档不能再挂该部门）。

### 7.2 数据模型

#### `departments` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str(32) PK | `dept_<uuid16>` |
| name | str(64) | |
| code | str(32) unique | 部门编码（如 `HR-1`） |
| parent_id | str(32)? | 父部门 |
| sort | int | 同级排序 |
| is_active | bool | 启用 / 停用 |
| leader_user_id | str(32)? | 部门负责人 |
| created_at | datetime | |
| deleted_at | datetime? | 软删 |

### 7.3 API 接口

| Method | Path | 角色 | 说明 |
|---|---|---|---|
| GET | `/api/v1/departments` | 登录用户 | 部门树（按权限过滤） |
| POST | `/api/v1/departments` | `platform_admin` / `super_admin` | 创建 |
| PUT | `/api/v1/departments/{id}` | `platform_admin` / `super_admin` | 编辑 |
| DELETE | `/api/v1/departments/{id}` | `super_admin` | 软删（仅无用户归属时可删） |
| POST | `/api/v1/departments/{id}/enable` | `platform_admin` / `super_admin` | 启用 |
| POST | `/api/v1/departments/{id}/disable` | `platform_admin` / `super_admin` | 停用 |
| PUT | `/api/v1/departments/{id}/leader` | `platform_admin` / `super_admin` | 设置负责人 |

### 7.4 管理后台页面（`/organization/departments`）

- 左侧树 + 右侧详情布局；
- 详情字段：name / code / parent / sort / leader / status；
- 操作：新增子部门 / 编辑 / 启停 / 设置负责人；
- 软删保护：有用户归属 → 禁止删除（提示先迁移用户）。

---

## 八、API 接口契约（汇总）

### 8.1 错误码扩展

| Code | 含义 |
|---|---|
| 40101 | 未登录 / Session 过期 |
| 40301 | 无菜单权限 |
| 40302 | 无角色权限 |
| 40303 | 数据范围超出 |
| 40901 | 用户名冲突 |
| 40902 | 工号冲突 |
| 40903 | 部门有用户归属，禁止删除 |
| 42201 | 参数校验失败 |

### 8.2 完整接口清单

| 域 | 接口 |
|---|---|
| 认证 | `/api/v1/auth/login` / `/logout` / `/me` |
| 用户 | 详见 §3.3 |
| 角色 | 详见 §4.4 |
| 菜单 | `/api/v1/menus`（GET，按 actor 过滤） |
| 部门 | 详见 §7.3 |

---

## 九、管理后台页面（admin-web）

> **交付口径（6A′）**：本章为**本期完整 UI 规格**，按 Task 分期实现。  
> - **M1 必达**：三模块列表 + 新建/编辑 Modal + 角色菜单树勾选（可先简版）+ 二次确认（启停/离职/重置/删角色）。  
> - **分期**：详情多 Tab、新建向导、菜单预览缩略图、键盘快捷键、移动端细化等 → 不阻塞 M1 验收。  
> - 现码已有列表+Modal，以实现状态表为准持续更新。  
> - **壳层工程**：对齐主 PRD **§12.1.1 工程硬约束 / D48**；细则见本节 **§9.0**。

### 9.0 持久壳与新建页强制规范（Agent 必读）

管理端是**经典后台布局**（左菜单 + 顶栏 + 内容区）。**侧栏与顶栏固定在壳上**，路由切换只替换主内容。

| 项 | 强制要求 |
|---|---|
| 壳挂载点 | **仅** `admin-web/src/app/(admin)/layout.tsx` → `AdminLayout` → `AppNav` |
| 业务页位置 | `admin-web/src/app/(admin)/<路由>/page.tsx` |
| 禁止 | 在 `page.tsx` 内再包 `AdminLayout`、再写一套侧栏/顶栏、拍平丢弃菜单树分组 |
| 顶栏标题 | `useAdminPageTitle("页面标题")`（来自 `@/components/AdminTitle`） |
| 壳外页面 | `/login`、`/403`、根 `/` 跳转 → **不得**放进 `(admin)` |
| 菜单与路由 | `menus.path` / 种子 path **必须**有对应页面；规划中也要占位页（无假保存） |
| 缺页行为 | 未知路径走 `(admin)/[...slug]` 或 `(admin)/not-found`，**保留侧栏**；禁止根级整页 404 |
| 侧栏交互 | 读 `/api/v1/menus/tree?app=admin`；分组折叠；整栏收窄；当前路由分组展开 |

**新建组织/管理页最小模板（示意）**：

```tsx
"use client";
import { useAdminPageTitle } from "@/components/AdminTitle";

export default function ExamplePage() {
  useAdminPageTitle("示例页");
  return <div>{/* 仅主内容 */}</div>;
}
```

**反例（禁止）**：`return <AdminLayout title="...">...</AdminLayout>` —— 会导致每次点菜单整壳重挂，看起来像整页刷新。

### 9.1 模块入口

左侧菜单顶级「**组织权限**」下挂 3 个二级模块：

```
组织权限
├── 1. 用户管理                (/organization/users)
│   ├── 用户列表
│   ├── 新建用户
│   ├── 用户详情
│   └── 我的资料（个人中心入口）
│
├── 2. 角色权限                (/organization/roles)
│   ├── 角色列表
│   ├── 新建自定义角色（仅超管）
│   ├── 角色详情
│   │   ├── 菜单权限 [Tab]
│   │   ├── 数据范围 [Tab]
│   │   └── 用户列表 [Tab]
│   └── 内置角色只读视图
│
└── 3. 部门管理                (/organization/departments)
    ├── 部门树
    ├── 部门详情
    └── 部门归属用户
```

### 9.2 角色视图差异

| 角色 | 用户管理 | 角色权限 | 部门管理 |
|---|---|---|---|
| `super_admin` | 全权（含换角色、离职、恢复） | 全权（含创建自定义 / 菜单 / 数据范围） | 全权（含删除） |
| `platform_admin` | CRUD + 启停 + **重置密码** + **换部门**；**不可换角色** | **只读**（不可改菜单/数据范围） | CRUD + 启停（不可删） |
| `department_admin` | 本部门只读（**M1.5**） | ❌ 无权 | 本部门只读（可选，随 M1.5） |
| 其他 | 仅「我的资料」 | ❌ | ❌ |

### 9.3 通用交互规范

- **壳层**：遵循 §9.0 / 主 PRD D48；点左侧菜单不得导致侧栏/顶栏消失或整页白屏 404；
- 新建 / 编辑用户 / 角色 / 部门 → 抽屉式表单（沿用 `知识库PRD.md §13.12` 状态规范）；
- 删除 / 启停 / 重置密码 → 二次确认 Modal；
- 操作完成后 Toast + 局部刷新；
- 列表行支持键盘快捷键（j/k 上下、Enter 进入详情）。

### 9.4 用户管理列表页（`/organization/users`）

#### 9.4.1 顶部信息条

```
┌─────────────────────────────────────────────────────────────────┐
│ 用户总数 248  │  活跃 215  │  停用 18  │  离职 15   [+ 新建用户] │
└─────────────────────────────────────────────────────────────────┘
```

- 4 个数值卡（点击切换状态筛选）；
- 「+ 新建用户」按钮（仅 `platform_admin` / `super_admin` 可见）。

#### 9.4.2 列表列设计

| 列 | 字段 | 说明 |
|---|---|---|
| 用户名 | `username` | 等宽字体；hover 显示完整 |
| 显示名 | `name` | |
| 工号 | `employee_no` | 等宽字体 |
| 主部门 | 主部门名 | 兼职部门数徽标："+2" |
| 角色 | 主角色徽标 + 附加角色数 | hover 显示全部角色 |
| 状态 | `status` | 三色徽标：active=绿 / disabled=橙 / terminated=灰 |
| 最近登录 | `last_login_at` | 相对值 + hover ISO |
| 操作 | — | 查看 / 编辑 / 重置密码 / 启停 |

#### 9.4.3 筛选 / 搜索 / 排序

- 搜索框：username / name / employee_no 模糊匹配（300ms debounce）；
- 状态筛选：active / disabled / terminated（多选，默认 active + disabled）；
- 角色筛选：6 内置 + 自定义（多选）；
- 部门筛选：树形单选 + 「含子部门」开关；
- 排序：创建时间倒序（默认）/ 最近登录 / 用户名；
- 分页：20 / 50 / 100。

#### 9.4.4 行操作菜单

- 行 hover → 右侧浮现"⋯"按钮 → 下拉菜单：
  - 查看详情
  - 编辑（仅 `platform_admin` / `super_admin`）
  - 重置密码（仅 `platform_admin` / `super_admin`，二次确认）
  - 启用 / 停用（按当前状态切换，二次确认）
  - 标记离职（仅 `super_admin`，二次确认；可通过 restore 恢复）
  - 恢复账号（仅 `super_admin`，对 `terminated`）

#### 9.4.5 批量操作（v1.1）

- 顶部 Checkbox 多选 → 浮出操作条："批量启停 / 批量转移部门 / 批量重置密码"；
- 仅 `super_admin` / `platform_admin` 可见。

### 9.5 用户详情页（`/organization/users/[user_id]`）

#### 9.5.1 顶部 Header

- 头像占位（首字母）+ 显示名 + 用户名 + 工号 + 状态徽标；
- 右上角：编辑 / 重置密码 / 启停 / 标记离职（按权限）；
- 关联信息卡片：所属部门（主 + 兼职）/ 角色列表 / 最近登录 IP。

#### 9.5.2 五 Tab 布局

```
[基本信息] [部门与角色] [会话历史] [操作日志]
```

| Tab | 内容 |
|---|---|
| 基本信息 | 用户名 / 显示名 / 工号 / 手机号 / 邮箱 / 职位 / 入职日期 / 创建人 / 创建时间 |
| 部门与角色 | 主部门 + 兼职部门列表；角色列表（主 + 附加），含授权人 / 授权时间 |
| 会话历史 | 最近 10 次登录：时间 / IP / User-Agent / 设备；「注销全部会话」按钮 |
| 操作日志 | 来自 `config_audit_logs` 中与 user/auth/role/department 相关的事件，按时间倒序（详情 Tab 可分期） |

### 9.6 用户编辑抽屉（新增 / 编辑）

#### 9.6.1 字段表单

| 字段 | 输入控件 | 校验 |
|---|---|---|
| 用户名 * | Input | 4-32 位字母数字下划线；不可重复（编辑时只读） |
| 显示名 *（`name`） | Input | 1-100 字 |
| 工号 * | Input | 唯一（编辑时只读） |
| 手机号 * | Input | 11 位数字 |
| 邮箱 * | Input | 标准邮箱格式 |
| 职位 | Input | |
| 入职日期 | DatePicker | |
| 主部门 * | TreeSelect（单选） | 必须；唯一 |
| 兼职部门 | TreeSelect（多选） | 不可含主部门 |
| 主角色 * | Select | 6 内置 + 自定义；至少 1 个 |
| 附加角色 | Select（多选） | 不可含主角色 |
| 初始密码 | InputPassword | 新建时必填；6+ 位（沿用主 PRD 3.2 极简） |

#### 9.6.2 主部门唯一性提示

- 选择主部门时业务校验：每用户仅一个主部门；替换须二次确认。
- 提示："该用户已是其他部门主部门，是否替换？"。

#### 9.6.3 保存按钮

- 「保存」→ 客户端校验 → 提交 → 成功 Toast + 关闭抽屉 + 列表局部刷新；
- 「保存并继续编辑」→ 保留抽屉 + 顶部"已保存"标识；
- 「取消」→ 未保存提示确认。

### 9.7 新建用户向导（`/organization/users/new`）

#### 9.7.1 分步表单（4 步）

```
[1 基本信息] → [2 部门归属] → [3 角色分配] → [4 初始密码]
```

- 步骤条（Steps 组件）顶部固定；
- 每步底部：「上一步」「保存草稿」「下一步」；
- 草稿保存：localStorage（v1.0）/ DB 草稿表（v1.1）。

#### 9.7.2 第 4 步初始密码策略

- 选项 1：手动输入（管理员指定）；
- 选项 2：自动生成（系统生成 8 位随机密码，显示一次 + 强制首次登录修改）；
- 选项 3：发送邮件（v1.1，依赖通知通道）。

### 9.8 角色管理列表页（`/organization/roles`）

#### 9.8.1 顶部信息条

```
┌─────────────────────────────────────────────────────────────────┐
│ 角色总数 12  │  内置 6  │  自定义 6   [+ 新建自定义角色]      │
└─────────────────────────────────────────────────────────────────┘
```

- 「+ 新建自定义角色」按钮（仅 `super_admin` 可见）。

#### 9.8.2 列表列设计

| 列 | 字段 | 说明 |
|---|---|---|
| 角色编码 | `code` | 内置徽标（"内置"）/ 自定义徽标（"自定义"） |
| 角色名 | `name` | 可点击进入详情 |
| 描述 | `description` | 截断 60 字 |
| 用户数 | 该角色下的活跃用户数 | 点击进入用户列表 |
| 默认数据范围 | `data_scope_default` | 徽标 all / department / self / custom |
| 状态 | `is_active` | 停用徽标（灰） |
| 操作 | — | 查看 / 编辑 / 启停 / 删除 |

#### 9.8.3 内置 vs 自定义行差异

- 内置角色：删除按钮置灰（hover 提示"内置角色不可删除"），编辑按钮仅 `super_admin` 可见；
- 自定义角色：全部操作可用；
- 「启停」区别：停用内置角色不影响超管，但其他用户的该角色权限失效。

### 9.9 角色详情页（`/organization/roles/[code]`）

#### 9.9.1 顶部 Header

- 角色编码 + 徽标（内置 / 自定义）+ 状态；
- 用户数 / 创建人 / 创建时间；
- 右上角：编辑 / 启停 / 删除。

#### 9.9.2 四 Tab 布局

```
[基本信息] [菜单权限] [数据范围] [用户列表]
```

| Tab | 内容 |
|---|---|
| 基本信息 | code / name / description / is_active / data_scope_default |
| 菜单权限 | 菜单树可视化（绿=可见 / 灰=不可见）；右侧"预览菜单结构" |
| 数据范围 | 单选 + 部门树（custom 时） |
| 用户列表 | 持有该角色的用户清单 + 授权人 / 授权时间 |

### 9.10 角色权限编辑（菜单权限 Tab）

#### 9.10.1 菜单树编辑器

```
顶级菜单
├── ☑ 总览                    [预览]
├── ☑ 智能体
│   ├── ☑ Agent 管理
│   ├── ☑ 模型与服务商
│   └── ☑ Prompt 模板
├── ☑ 知识与编排
│   ├── ☑ 知识库
│   ├── ☑ 工作流
│   └── ☐ 知识图谱（未勾选）
├── ☑ 组织权限
│   ├── ☑ 用户管理
│   ├── ☑ 角色权限
│   └── ☑ 部门管理
├── ☐ 系统治理（未勾选）
└── ☑ 运维审计
    ├── ☑ 用量成本
    ├── ☑ 通知告警
    └── ☑ 配置审计
```

- 树形复选框：父节点勾选 → 子节点全部勾选；半选状态显示；
- 右侧实时预览"该角色登录后的左侧菜单结构"（缩略菜单图）。

#### 9.10.2 保存逻辑

- 「保存」→ 二次确认（提示"将影响 N 个在线用户"）→ 提交；
- 后端：`PUT /api/v1/roles/{code}/menus`；
- 写审计 `role.menu.put`；
- 主动失效：受影响用户 `DEL actor:m:{user_id}` + 异步重建。

### 9.11 数据范围编辑（数据范围 Tab）

#### 9.11.1 单选 + 部门树

```
数据范围
○ all（全部数据）
○ department（本部门及兼职部门）
○ self（仅自己创建）
● custom（自定义部门）  ← 默认
   ┌─────────────────────┐
   │ ☑ 人事部              │
   │ ☑ 财务部              │
   │ ☐ IT 部               │
   │ ☐ ...                 │
   └─────────────────────┘
```

- 选中 `custom` → 显示部门树多选；
- 默认 `self`（避免创建时权限过大，沿用 AU-05 决策）；
- 保存后写 `role.data_scope.put`。

### 9.12 新建自定义角色向导（`/organization/roles/new`）

#### 9.12.1 三步表单

```
[1 基本信息] → [2 菜单权限] → [3 数据范围]
```

- 步骤 1：code（小写字母数字下划线，32 位内）/ name / description；
- 步骤 2：菜单树勾选（默认全不勾选）；
- 步骤 3：数据范围单选（默认 `self`）。

### 9.13 部门管理页（`/organization/departments`）

#### 9.13.1 布局：左树 + 右详情

```
┌──────────────┬────────────────────────────────────────┐
│ 部门树        │  部门详情 [Tab]                          │
│              │  ── 基本信息 ── 部门归属用户               │
│ ▼ 集团        │  名称 │ 编码 │ 父部门 │ 排序 │ 负责人     │
│   ▼ 人事部    │  ...                                   │
│     · 一部   │                                        │
│     · 二部   │  [编辑] [启停] [设置负责人] [+ 新增子部门] │
│   ▶ 财务部    │                                        │
│   ▶ IT 部    │                                        │
└──────────────┴────────────────────────────────────────┘
```

#### 9.13.2 部门详情字段

| 字段 | 说明 |
|---|---|
| 名称 | 可编辑 |
| 编码 | 全局唯一；不可改（业务标识） |
| 父部门 | TreeSelect（不可选自己或子部门，防环） |
| 排序 | 数字 |
| 负责人 | SelectUser（单选） |
| 状态 | active / disabled |

#### 9.13.3 删除保护

- 有用户归属 → 删除按钮置灰 + Tooltip"该部门有 N 个用户，请先迁移"；
- 无用户归属 → 「删除」二次确认 + 软删（保留数据，可恢复 v1.1）。

### 9.14 我的资料页（`/profile`，员工端入口）

#### 9.14.1 功能

- 显示：头像 / 显示名 / 工号 / 手机号 / 邮箱 / 职位 / 入职日期 / 主部门 / 角色；
- 可编辑：手机号 / 邮箱 / 显示名（其他字段仅管理员可改）；
- 「修改密码」按钮 → 弹抽屉：旧密码 + 新密码 + 确认密码 → 提交。

#### 9.14.2 修改密码抽屉

| 字段 | 校验 |
|---|---|
| 旧密码 * | 必须正确 |
| 新密码 * | 6+ 位（沿用主 PRD 3.2） |
| 确认密码 * | 与新密码一致 |
| 强度提示 | 文字 + 颜色条 |

- 成功后 Toast + 强制重新登录（清 Redis session）；
- 失败 3 次后 30 分钟内禁止重试（防爆破，v1.1）。

### 9.15 二次确认触发清单

| 操作 | 触发场景 | 确认文案 |
|---|---|---|
| 删除用户 | 标记离职 | "标记离职后无法登录，历史数据保留；超管可恢复。确认？" |
| 恢复用户 | terminated → active | "确认恢复 [username]？将恢复为可登录状态。" |
| 启用 / 停用 | 状态切换 | "确认停用 [username]？停用后无法登录。" |
| 重置密码 | 重置 | "确认重置密码？新密码将显示一次，强制首次登录修改。" |
| 删除自定义角色 | 删除 | "确认删除角色 [code]？持有该角色的用户将失去相关权限。" |
| 启停角色 | 状态切换 | "确认停用角色 [code]？该角色下的用户权限将立即失效。" |
| 替换主部门 | 编辑用户 | "该用户已是 [dept] 的主部门，确认替换为 [new_dept]？" |
| 角色菜单变更 | 保存 | "将影响 N 个在线用户，下次请求生效（< 1s）。确认？" |
| 删除部门 | 软删 | "确认删除部门 [name]？历史数据保留，部门将不可用。" |
| 角色数据范围变更 | 保存 | "将影响 N 个用户的数据访问范围。确认？" |
| 会话注销 | 注销全部 | "确认注销该用户全部会话（共 N 个）？将强制重新登录。" |

### 9.16 状态机与操作联动

#### 9.16.1 用户状态机

```
[新建] ──→ active ⟷ disabled
              │
              ↓
           terminated ──(仅超管 restore)──→ active
```

| 当前状态 | 可执行操作 |
|---|---|
| `active` | 停用 / 标记离职（超管） |
| `disabled` | 启用 / 标记离职（超管） |
| `terminated` | 查看；**超管可恢复**（裁定 8） |

#### 9.16.2 角色状态机

```
[新建] ──→ active ──→ disabled ──→ active
                          │
                          ↓
                       [删除]（仅自定义）
```

| 当前状态 | 可执行操作 |
|---|---|
| `active` | 停用 / 删除（自定义） |
| `disabled` | 启用 / 删除（自定义） |
| 内置角色任何状态 | 不可删除 |

#### 9.16.3 部门状态机

```
[新建] ──→ active ──→ disabled ──→ active
                          │
                          ↓
                       [软删]
```

| 当前状态 | 可执行操作 |
|---|---|
| `active` | 停用 / 删除（无用户时） |
| `disabled` | 启用 / 删除（无用户时） |
| 软删 | （仅恢复 v1.1） |

### 9.17 状态展示规范（与知识库 PRD §13.12 对齐）

#### 9.17.1 用户状态

| 状态 | 图标 | 颜色 | 文案 |
|---|---|---|---|
| `active` | ● | 绿色 | "活跃" |
| `disabled` | ◐ | 橙色 | "已停用" |
| `terminated` | ○ | 灰色 | "已离职" |

#### 9.17.2 角色状态

| 状态 | 图标 | 颜色 | 文案 |
|---|---|---|---|
| `active` | ● | 绿色 | "启用" |
| `disabled` | ◐ | 橙色 | "停用" |
| `builtin` | 🔒 | 蓝色 | "内置" |

#### 9.17.3 通用规范

- 加载中：骨架屏（行高 56px × 10 行）；
- 空状态："暂无用户 / 角色 / 部门" + CTA；
- Toast：成功 3s 自动消失；失败 5s + 「重试」；
- Modal：危险操作二次确认（详见 §9.15）。

### 9.18 移动端与可访问性

#### 9.18.1 响应式断点（沿用知识库 PRD §13.14）

| 断点 | 行为 |
|---|---|
| ≥1280px | 完整桌面布局 |
| 1024–1279px | Sidebar 折叠至 72px |
| <1024px | Sidebar 抽屉化；表格次要列进入详情 |

#### 9.18.2 用户管理表格移动端

- 固定列：用户名 + 操作列；
- 横滑：中间列（部门 / 角色 / 状态）；
- 操作菜单：hover 变 click。

#### 9.18.3 可访问性

- 全交互键盘可达；
- 焦点环可见；
- 状态用"图标 + 文案 + 颜色"三重表达；
- 颜色对比度 ≥ 4.5:1。

---

## 十、可观测性

### 10.1 Prometheus 指标

| 指标 | 类型 | Labels |
|---|---|---|
| `auth_login_total` | counter | `result`(`success`/`fail`) |
| `auth_session_active` | gauge | `app`(`admin`/`web`) |
| `actor_cache_hit_total` | counter | `result`(`hit`/`miss`) |
| `actor_load_duration_seconds` | histogram | — |
| `permission_check_total` | counter | `result`(`pass`/`deny`) |
| `permission_check_duration_seconds` | histogram | — |

### 10.2 审计事件（沿用主 PRD 7.3）

> 写入现有 **`config_audit_logs`**（经 `app.modules.audit.service.record`），**不要**使用 `kb_audit_events`。M1 先落最小集（login/logout、user.* 关键、role.menu.put、department.*）；其余按清单补齐。

| action | 触发点 |
|---|---|
| `auth.login` | 登录成功 |
| `auth.login_fail` | 登录失败（带 reason） |
| `auth.logout` | 主动注销 |
| `user.create` | 新建用户 |
| `user.update` | 编辑用户 |
| `user.delete` | 标记离职 |
| `user.restore` | 超管恢复离职账号 |
| `user.enable` / `user.disable` | 启停（经 `PATCH .../status`） |
| `user.reset_password` | 重置密码 |
| `user.role.put` | 角色变更 |
| `user.department.put` | 部门变更 |
| `role.create` / `role.update` / `role.delete` | 角色 CRUD |
| `role.menu.put` | 角色菜单权限变更 |
| `role.data_scope.put` | 角色数据范围变更 |
| `menu.update` | 菜单定义变更（v1.1） |
| `department.create` / `update` / `delete` / `enable` / `disable` | 部门 CRUD + 启停 |

### 10.3 失败登录监控

- 同一 IP 5 分钟内连续 5 次失败 → 写入告警事件（沿用主 PRD 7.4）；
- 不引入锁定策略（沿用主 PRD 3.2 极简登录），仅监控不阻断。

---

## 十一、非功能指标

| 指标 | 目标 |
|---|---|
| 登录 P95 | < 500ms |
| Actor 注入 P95（缓存命中） | < 5ms |
| Actor 注入 P95（DB 查询） | < 50ms |
| 权限校验 P95 | < 1ms |
| 用户列表 P95（1000 用户级） | < 300ms |
| Session 有效期 | 8 小时（沿用主 PRD 3.2） |
| 多端登录 | 不限制（沿用主 PRD 3.2） |
| 审计保留 | 90 天（与对话留存一致） |

---

## 十二、范围与不做事项

### 12.1 本期规格（v1.0，按波次交付）

**M1 必达**

- 接通 `get_actor` → `load_actor`；组织 API `require_menu`；menus 按角色过滤；动态侧栏；
- 用户 CRUD / `PATCH status` / 平台可重置密码与换部门；超管换角色 / 离职 / **恢复**；
- 创建用户写 `extra_roles`；部门不存在 → 422（禁止自动建部门）；
- 角色：自定义 CRUD + 菜单树权限 + 数据范围（写仅超管）；
- 菜单**树形种子** + 角色菜单即时生效（清 Actor 缓存）；
- 部门树 CRUD + 软删保护；
- admin-web：三模块列表 + Modal + 菜单勾选；
- 审计最小集（写入 `config_audit_logs`）。

**本期规格、分期交付（不阻塞 M1）**

- §6.8–6.12 缓存防护 / 预热 / Locust / 故障演练；
- §9 详情多 Tab、向导、预览、快捷键、移动端细化；
- 审计事件补齐至完整清单；Prometheus 全套。

**M1.5**

- 部门管理员本部门用户只读（US-AU-04）。

### 12.2 不做（明确排除）

- ❌ SSO / OAuth / 第三方登录；
- ❌ 密码复杂度升级 / 密码找回 / MFA；
- ❌ 域账号 / LDAP 同步；
- ❌ 角色层级继承；
- ❌ 字段级权限（仅做行级）；
- ❌ 用户组（基于标签的动态分组，v1.3+）；
- ❌ 操作签名 / 二次密码确认（高风险操作走主 PRD 已有审批流）；
- ❌ admin-web 主题 / 视觉规范细节（沿用主 PRD 12.1.4）；
- ❌ v1.0 Redis/`user_sessions` 会话库（→ M2）。

---

## 十三、验收标准（节选）

### 13.1 功能验收

| 场景 | 波次 | 验收 |
|---|---|---|
| US-AU-01 | M1 | 超管创建用户，分配主部门 + 角色，登录后看到对应菜单 |
| US-AU-02 | M1 | 修改角色菜单后，已登录用户下一请求菜单立即生效（< 1s） |
| US-AU-03 | M1 | 停用用户后登录 401；Session 失效 |
| US-AU-04 | **M1.5** | 部门管理员仅看到本部门用户列表 |
| US-AU-05 | M1 | 内置角色无「删除」；自定义角色删除仅超管 |
| US-AU-06 | M1.5+ | 数据范围 `department` 查不到其他部门组织数据 |
| US-AU-07 | 随计费 | 主部门变更后成本分摊按新主部门 |
| US-AU-08 | M1 | 超管可将 `terminated` 恢复为 `active` |
| US-AU-09 | M1 | 平台可重置密码与换部门，不可 `PUT roles` / 改角色菜单 |

### 13.2 非功能验收

- **M1**：权限校验不显著拖慢业务接口；Actor 缓存可命中；审计最小集可查。
- **M2**：§6.12 Locust/演练目标；缓存命中率看板；失败登录监控。

### 13.3 兼容性

- 旧 Session 三字段兼容：缓存 miss 时 DB 重建 Actor；
- 角色菜单变更后下一请求生效（不必重登）。

---

## 十四、实施路线图

### M1（主链路 + 契约）

- [x] 表结构迁移 0031 + 内置角色种子（菜单树种子待补）；
- [ ] `get_actor` 接通 `load_actor`；未登录 401；
- [ ] `require_menu` + menus 过滤 + 动态侧栏；
- [ ] 用户契约修洞（extra_roles / 禁自动建部门 / 清 Session）；
- [ ] 权限边界裁定 4；`POST .../restore`；
- [ ] 菜单树种子；角色菜单勾选可用；
- [ ] 审计最小集；更新文首实现状态表。

### M1.5

- [x] 部门管理员本部门用户只读；组织列表数据范围过滤（用户列表）。
- [x] 部门列表本部门只读（可选项收尾）；`org.departments` 菜单种子。

### M2

- [x] 第一刀：`user_sessions` + 列表/注销全部 + 吊销校验 + `last_login_at`（2026-08-10）
- [ ] Redis/DB 会话深化、§6.8–6.12、§9 深化 UI、Prometheus、失败登录监控

### M3（可选）

- 用户组；字段级权限；角色继承；自助改资料/头像。

---

## 十五、风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 角色菜单变更导致已登录用户突然少菜单 | 变更前 Toast；主动 DEL Actor | TTL 兜底自动重载 |
| 误标离职 | 仅超管 + 二次确认；**支持 restore** | 超管恢复 |
| 部门软删误操作 | 删除前二次确认 + 用户数提示 | 软删保留数据 |
| 自定义角色权限过大 | 默认 `data_scope=self` | 超管可改 |
| 文档规格过厚导致一次扫完 | 实现状态表 + Task 分期（6A′） | 按波次验收 |
| 密码泄露 | bcrypt + 改密/重置清 Session | 立即重置并失效会话 |

---

## 十六、变更对照表（与现码，2026-08-10）

| 主题 | 现码 | 本规格目标 |
|---|---|---|
| 字段命名 | `name` / `role` / `department_admin` | **保持**；文档已对齐 |
| Session | Starlette SessionMiddleware | v1.0 保持；Redis 会话 M2 |
| Actor | `load_actor` 有，`get_actor` 未接 | M1 接通 |
| 菜单 | 表+扁平种子；侧栏静态 | 树种子 + 过滤 + 动态侧栏 + 持久壳（D48） |
| 用户 API | CRUD/status 有；契约空洞 | 修洞 + restore + 裁定 4 权限 |
| 审计 | 配置审计有；组织域无 | `config_audit_logs` 扩展 |
| admin-web | 页内包壳 / 缺页整页 404 | `(admin)/layout` 持久壳；占位页；壳内 404 |
| 实现状态 | — | 文首状态表持续维护 |

---

## 十七、决策确认记录

| # | 决策点 | 拍板结论 | 备注 |
|---|---|---|---|
| AU-01 | 角色继承层级 | **不做**，仅并集 | 避免隐式权限 |
| AU-02 | 字段级权限 | **不做**，仅行级 | v1.0 简化 |
| AU-03 | 自定义角色创建 / 菜单·数据范围写入 | **仅 `super_admin`** | 高敏；平台只读角色 |
| AU-04 | 内置角色修改权限 | **仅 `super_admin`** | 避免破坏通用基线 |
| AU-05 | 数据范围默认值（自定义角色） | **`self`** | 创建时强制 |
| AU-06 | 用户名 / 工号修改 | **不可改** | 避免身份漂移 |
| AU-07 | Actor 缓存 TTL | **30 分钟** + 主动失效 | Key：`za:actor:m:{id}` |
| AU-08 | 失败登录监控 | 5 分钟 5 次告警，**不锁定** | M2 落地 |
| AU-09 | 用户状态可逆性 | `active ↔ disabled`；`terminated` **超管可恢复** | 2026-08-10 修订 |
| AU-10 | 主部门唯一性 | 应用层每用户一条 `is_primary=true` | 部分唯一索引可选后补 |
| AU-11 | admin-web 顶级菜单 | 沿用主 PRD 12.1.2 | 不开新顶级 |
| AU-12 | 与主 PRD 关系 | 主 PRD 第二章优先 | 子文档细化 |
| AU-13 | Session 方案 | v1.0 Starlette；Redis/DB 会话 **M2** | 2026-08-10 |
| AU-14 | 平台 vs 超管写权限 | 平台：重置密码+换部门；超管：换角色/菜单/数据范围/离职恢复 | 裁定 4 |
| AU-15 | 菜单形态 | v1.0 **菜单树**（补种子） | 裁定 5 |
| AU-16 | 重规格交付 | §6.8–6.12 / §9 深化 **分期**，不一次验收 | 9A′+6A′ |
| AU-17 | 部门管理员只读列表 | **M1.5** | 裁定 7 |
| AU-18 | 显示名字段 | API/库表用 `name` | 裁定 2 |
| AU-19 | 管理端壳与新建页 | **持久壳 / 禁页内包菜单 / path 必有页 / 壳内 404** | 主 PRD D48；§9.0 |

---

## 附：参考与依赖

| 文档 | 关联章节 |
|---|---|
| `PRD.md` 第二章 用户角色与权限模型 | §2 §3 §4 §5 |
| `PRD.md` 3.1 / 3.2 账号体系 / 登录策略 | §3 §6 |
| `PRD.md` 3.3.4 用户停用数据处理 | §3.1 |
| `PRD.md` 3.4 多端登录 | §3 §6 |
| `PRD.md` 12.1.1 独立管理后台（安全硬约束） | §6 §9 |
| `PRD.md` 12.1.2 管理端菜单与首期范围 | §5 §9 |
| `PRD.md` 13.5 用户离职/转岗数据处理 | §3.1 |
| `PRD.md` 7.3 审计范围 | §10.2 |
| `PRD.md` 13.1 用户身份与对话准入 | §3 |
| `API接口规范.md` | §8 |
| `数据库表结构.md` | §3.2 §4.2 §7.2 |
| `知识库PRD.md` §13.3.2 模块入口 | §9.1 |
| `docs/05-开发指南/安全与禁止清单.md` | §6 §10 |

@author 赵振明  
@date 2026-08-10 09:20:09