# 权限·用户·菜单 实施计划（Org-Auth Impl Plan）

> 版本 v1.0.0 | 2026-08-07
>
> 基于 `权限用户菜单PRD.md` v1.0.2 + 代码探查结果 + 用户决策（**增量修改 + 保留增强 + 直接 TDD**）。
>
> **策略**：在现有代码上增量；保留 `auth.py` / `users.py` / `departments.py` 现有接口；新增 `roles.py` / `menus.py` / `data_scopes.py` 等；扩展 `actor.py` 与 `User` / `Department` 表字段；Alembic 迁移；Redis 缓存；admin-web 与 web 双端页面。

---

## 实施任务清单（11 块）

| # | 任务 | 范围 | 状态 |
|---|---|---|---|
| T1 | **Actor 数据类扩展**（含 Redis 序列化） | `src/app/core/actor.py` + 测试 | 🟢 进行中 |
| T2 | **Alembic 迁移脚本** | 新增 5 表 + 用户/部门增量字段 | ⏳ 待 T1 完成 |
| T3 | **Pydantic Schema 扩展**（`UserOut` / `RoleOut` / `MenuOut` 等） | `src/app/api/schemas/` | ⏳ |
| T4 | **Actor 加载函数 + Redis 缓存 + 中间件** | `src/app/core/actor.py` + `src/app/middleware/` | ⏳ |
| T5 | **角色 API（17 个新接口）** | `src/app/api/v1/roles.py`（新建） | ⏳ |
| T6 | **菜单 + 数据范围 API（4 个新接口）** | `src/app/api/v1/menus.py`（新建） | ⏳ |
| T7 | **用户 API 增强（保留 + 新增 8 个）** | `src/app/api/v1/users.py`（增强） | ⏳ |
| T8 | **部门 API 增强（树形 CRUD + 软删）** | `src/app/api/v1/departments.py`（增强） | ⏳ |
| T9 | **admin-web 组织权限 3 模块** | `admin-web/src/app/organization/{users,roles,departments}/`（新建） | ⏳ |
| T10 | **admin-web 我的资料 + 修改密码** | `admin-web/src/app/profile/`（新建） | ⏳ |
| T11 | **web 员工端登录 + 我的资料** | `web/src/app/(auth)/`（确认或新建） | ⏳ |

---

## TDD 节奏约定

每个任务严格遵循 **Red → Green → Refactor**：

1. **Red**：先写 pytest 测试，验证它因缺乏实现而**失败**；
2. **Green**：写最小实现使测试通过；
3. **Refactor**：清理代码 + 删冗余；
4. **Verify**：跑全量测试 + 静态检查。

---

## T1：Actor 数据类扩展（当前任务）

### 测试文件

`tests/core/test_actor_extended.py`

### 实现文件

`src/app/core/actor.py`（扩字段，向后兼容）

### 测试要点（13 个用例）

1. 最小字段构造（向后兼容）
2. 扩展字段默认值
3. `has_role` 主角色
4. `has_role` 附加角色
5. `has_menu` 普通菜单
6. `has_menu` 超管捷径
7. `in_department` 四种 scope（all / department / self / custom）
8. `to_cache_dict` / `from_cache_dict` roundtrip
9. 缺失字段降级
10. frozen 不可变
11. 现有 helper（`is_department_admin` / `is_platform_admin`）兼容

### 验收

- 现有调用方 `get_actor` 36 处不受影响；
- 13 个测试全部通过；
- 静态检查（基于现有项目配置）通过。

---

## 后续任务（占位，详细测试列表在每个 Tn 文档展开）

### T2 Alembic 迁移

- 新增：`roles` / `user_roles` / `menus` / `role_menu_permissions` / `role_data_scopes`
- 增量字段：`users.status` 三态值约束 / `user_departments.is_primary` / `departments.code` / `departments.sort` / `departments.leader_user_id` / `departments.is_active` / `departments.deleted_at`
- 索引：`uk_user_dept(user_id, department_id)` 已存在；新增 `uk_user_primary_dept(user_id) WHERE is_primary = true`（MySQL 8 唯一索引或 PostgreSQL partial unique）

### T3 Schema

- `app/api/schemas/user.py`：扩展 `UserOut` 含 `status` / `departments` / `roles`
- 新增 `app/api/schemas/role.py`、`menu.py`、`data_scope.py`

### T4 中间件 + 缓存

- `load_actor(user_id, session_id)`：Redis → DB → Redis 回写（TTL 1800s ± 300s 抖动）
- 单飞锁 `asyncio.Lock` per user_id（防击穿）
- FastAPI Depends：`require_menu(menu_code)` / `require_role(role_code)` / `require_data_scope(scope)`
- 配置 `Settings.actor_cache_enabled / actor_cache_ttl_seconds`

### T5-T8 API

每个 API 配 1-2 个 pytest 测试（mock DB），覆盖：
- 正常路径
- 权限拒绝（403）
- 数据范围过滤
- 字段校验（422）
- 资源不存在（404）

### T9-T11 前端

每个页面配 React Testing Library 测试 + 1 个 E2E（Playwright）：
- 页面渲染（空 / 有数据）
- 列表筛选 / 搜索
- 抽屉表单提交
- 二次确认
- 错误处理

---

## 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| Actor 扩展破坏现有调用 | 13 个兼容测试 + 字段全部默认 | git revert T1 commit |
| Alembic 迁移失败 | dry-run + staging 演练 | alembic downgrade -1 |
| Redis 不可用 | 走 DB 重建 + 熔断 | 关 `actor_cache_enabled` |
| 前端大量新增文件 | 渐进合并，按域 T9.1 → T9.2 → T9.3 | 回退到 0.8.1 |

@author 赵振明