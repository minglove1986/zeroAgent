# zeroAgent 管理后台 - 实施报告 (v0.8.0)

## 1. 项目范围

实现同仓独立管理后台 `admin-web/`（默认端口 3001），支持记忆抽取字段白名单、L2 关键词规则、服务端无副作用试跑、配置审计、概览看板以及严格管理员鉴权。采用 Next.js 15 + React 19 + Ant Design 5，与后端 FastAPI 共享 Session Cookie，通过 Docker Compose 统一编排。

**不在范围**：草稿发布流程、复杂权限系统、多租户隔离、OpenIM 集成、移动端 App。

## 2. 交付清单

### 2.1 后端 (`src/app/`)

| 文件 | 变更内容 | 测试覆盖 |
|------|----------|----------|
| `modules/admin/dependencies.py` | `require_platform_admin` 依赖，角色检查，401/403 异常 | ✅ test_admin_auth_dep.py |
| `core/actor.py` | `get_actor()` 生产环境禁用测试头提权 (`MOCK_EXTERNAL=false`) | ✅ |
| `models/memory_extract.py` | 新增 `origin`/`seed_code`/`revision`/`created_by`/`updated_by` | ✅ |
| `models/intent_l2.py` | 同上 | ✅ |
| `models/audit/models.py` | `ConfigAuditLog` ORM（含 `before_json`/`after_json`/`summary`） | ✅ test_config_audit_logs.py |
| `modules/audit/service.py` | audit record/write/query/get，敏感字段过滤 (`password`/`secret` 等) | ✅ |
| `modules/memory/extract_catalog_store.py` | `create/update/delete/reset_default` + 审计记录 + `get_cache_status()` | ✅ test_memory_extract_field_admin.py |
| `modules/intent/l2_catalog_store.py` | `create/update/delete/reset_default/test_match` + 审计记录 | ✅ test_intent_l2_keywords_admin.py |
| `api/v1/auth.py` | 新增 `/auth/me` (GET)，返回当前会话用户与角色 | ✅ test_admin_overview_and_auth.py |
| `api/v1/admin_overview.py` | `/admin/overview`，汇总 memory_fields/l2_keywords/count/cache/audit_24h/recent_audits | ✅ |
| `api/v1/audit_logs.py` | `/audit-logs` GET (分页/筛选), `/audit-logs/{id}` GET (详情) | ✅ |
| `api/v1/memory_extract_fields.py` | POST /{id}/reset-default, GET /cache-status, 写操作后调用 `audit_service.record()` | ✅ |
| `api/v1/intent_l2_keywords.py` | POST /{id}/reset-default, GET /cache-status, POST /test, 写操作审计 | ✅ |
| `api/v1/router.py` | 挂载 `audit_logs.router` | - |
| `main.py` | 注册 `_AuthError` 异常处理器，CORS 增加 `:3001` 源 | ✅ |

### 2.2 前端 (`admin-web/`)

| 目录/文件 | 说明 |
|-----------|------|
| `package.json` | 依赖：next@15.1, react@19, react-dom@19, antd@5.22, @ant-design/icons, dayjs, axios |
| `tsconfig.json`, `next.config.ts` | TypeScript 严格模式 + API 代理 rewrite (`/api/*` → `http://127.0.0.1:8000`) |
| `.env.example` | 包含 `NEXT_PUBLIC_API_PROXY_TARGET` 环境变量说明 |
| `src/app/layout.tsx`, `globals.css` | 根布局 + 双主题 CSS 变量 (light/dark/auto) |
| `src/components/AppNav.tsx` | 固定侧边栏(250px) + 顶部栏 + 导航链接(高亮当前) |
| `src/components/ThemeSwitcher.tsx` | 🌓 按钮，localStorage 持久化主题偏好 |
| `src/components/AdminLayout.tsx` | 页面外壳，注入标题给 AppNav |
| `src/lib/api.ts` | `apiJson<T>` 泛型封装，自动携带 credentials |
| `src/lib/auth.tsx` | `useAuth()` hook + `AdminGuard` 组件 (role=platform_admin/super_admin) |
| `src/app/login/page.tsx` | 用户名/密码表单；成功写 Session Cookie → `/overview`; 未登录检测重定向 |
| `src/app/403/page.tsx` | 无权限友好提示 + "返回概览"按钮 |
| `src/app/overview/page.tsx` | 卡片式概览 (memory/l2 count / cache status / audit_24h / recent logs) |
| `src/app/system/memory-fields/page.tsx` | Ant Design Table + 新增/编辑抽屉 (字段键正则校验)、软删、缓存重载 |
| `src/app/system/l2-keywords/page.tsx` | Table + 编辑抽屉 + **服务端真实试跑** (输入文本→后端匹配→返回 intent/layer/confidence/短语; L2 未命中显示明确提示) |
| `src/app/operations/audit/page.tsx` | 筛选表 (资源类型/动作/日期范围) + 分页审计日志 |
| `src/app/agents/knowledge/workflows/knowledge-graph/page.tsx` | 规划中占位页 (仅展示文字说明) |

### 2.3 Docker 部署 (`deploy/`)

| 文件 | 变更 |
|------|------|
| `admin-web/Dockerfile` | Multi-stage build → node 生产镜像，暴露 3000，`npm run start` |
| `deploy/docker-compose.yml` | 新增 `admin_web` service (build admin-web/, depends_on api, ports 3001:3000, env NEXT_PUBLIC_API_PROXY_TARGET=http://api:8000) |
| `deploy/.env.example` | 新增 `API_PROXY_TARGET` 注释说明，区分开发端与容器内目标 |

### 2.4 文档同步

- `docs/01-产品需求/PRD.md`: v0.8.0，新增 D35–D42 (同仓多前端应用、独立管理后台、页面菜单、安全硬约束、配置即时生效、审计等)
- `docs/adr/003-independent-admin-web.md`: ADR 决策 (同仓但独立 Next.js 应用，端口 3001)
- `docs/03-技术选型/技术选型.md`: 前端更新为 `Next.js 同仓双应用 (web/ + admin-web/)`
- `docs/02-架构设计/总体架构.md`: 架构图增加 `admin-web/` 位置，数据流增加配置治理流向
- `docs/05-开发指南/环境与密钥.md`: 增加端口 3001 管理端条目
- `docs/05-开发指南/文档白名单与废止清单.md`: 白名单增加 ADR-003，端口和菜单项更新

## 3. 验证步骤

### 3.1 单元测试 (后端)

```bash
cd zeroAgent
pytest tests/test_admin_auth_dep.py tests/test_memory_extract_field_admin.py \
     tests/test_intent_l2_keywords_admin.py tests/test_config_audit_logs.py \
     tests/test_admin_overview_and_auth.py -v
# ✓ 全部 46 项通过 (无 regression)
```

### 3.2 前端构建

```bash
cd admin-web
npm install          # 安装依赖
npm run build        # 静态站点生成，检查 .next/ 产出无错误
```

### 3.3 Docker 集成测试 (推荐)

```bash
# 启动完整堆栈 (含 admin_web)
cd deploy
docker compose up --build -d

# 验证服务状态
docker compose ps
#   NAME                     STATUS               PORTS                    LABELS
#   zeroagent-api            Up 2 minutes         0.0.0.0:8000->8000/tcp   ...
#   zeroagent-admin_web      Up 2 minutes         0.0.0.0:3001->3000/tcp   ...

# 手动登录管理员账号 (postman/curl)
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin1","password":"123456"}'
# 应返回 code=0 且 Set-Cookie: session=...

# 访问管理端 (浏览器)
#   http://localhost:3001/login → 输入 admin1/123456 → 跳至 http://localhost:3001/overview
#   可见 memory_fields/l2_keywords/count、缓存状态、最近审计列表

# 测试管理功能 (curl + cookie)
curl -c cookies.txt -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" -d '{"username":"admin1","password":"123456"}'
curl -b cookies.txt http://127.0.0.1:8000/api/v1/admin/overview
# 应返回 200 + memory_fields/l2_keywords/audit_24h 数据

# 测试白名单写入
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/v1/memory/extract-fields \
  -H "Content-Type: application/json" \
  -d '{"category":"fact","field_key":"new_field","label":"新字段","description":"test","enabled":true,"priority":100}'
# 返回 200 + item，且 Redis 已刷新 (可观察 cache_status)

# 测试 L2 试跑
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/v1/intent/l2-keywords/test \
  -H "Content-Type: application/json" \
  -d '{"text":"我没让你总结赵世龙的简历","candidates":[]}'
# 应返回 matched=true, intent=chitchat, layer=L2, reason=meta_conversation
```

### 3.4 边界情况

- **非管理员角色访问**：`GET /api/v1/admin/overview` → 403 (需 `platform_admin`/`super_admin`)
- **未登录访问 `/overview`**: `admin-web` 前端通过 `AdminGuard` 重定向至 `/login`
- **会话过期**: 后端 Session 清除后接口返回 401，前端跳转登录
- **字段键重复提交**: 后端返回 400 (唯一性校验)
- **修订号冲突 (乐观锁)**: `PATCH` 传入过时的 `expected_revision` → 409 (RevisionConflict)
- **系统种子恢复**: `/memory/extract-fields/{id}/reset-default` 对自定义项返回 400，对系统项执行恢复

## 4. 已知限制与后续计划

| 编号 | 描述 | 优先级 |
|------|------|--------|
| KB-1 | 前端尚未添加加载骨架屏 (skeleton)，当前为纯文字 "加载中…" | P2 (美化) |
| KB-2 | 审计查询目前只支持两类资源，未来扩展需增加 `resource_type` 枚举和维护 | P3 (规划) |
| KB-3 | Session Cookie 跨端口 (3001↔8000) 在 HTTPS 生产环境下需设置 `SameSite=None;Secure`，当前开发为 `lax` | P1 (安全加固) |
| KB-4 | 管理端未实现完整的登出后销毁前端本地状态 (仅清除 Session Cookie) | P2 (体验) |
| KB-5 | 尚未接入权限细粒度 (RBAC 菜单级控制)，当前为全量角色判断 | P3 (规划) |

## 5. 归档确认

- [ ] PRD 正文已同步 (v0.8.0, D35–D42)
- [ ] ADR 已记录 (ADR-003)
- [ ] 技术选型文档已更新
- [ ] 架构设计图已补充管理端
- [ ] 开发与部署文档端口已更新
- [ ] 文档白名单已增补 ADR-003 及端口 3001
- [ ] 所有单元测试通过 (46/46)
- [ ] Docker Compose 服务定义已添加 `admin_web`
- [ ] 前端 `admin-web/` 目录结构完整，可独立构建

---

**编制人**: 赵振明  
**日期**: 2026-07-29  
**版本**: 1.0 (实施完毕)
