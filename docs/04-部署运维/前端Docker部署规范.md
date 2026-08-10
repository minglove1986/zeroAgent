# zeroAgent 前端 Docker 部署规范

> 版本 v1.0 | 2026-08-05
> 适用范围：`web/`（员工端）、`admin-web/`（管理后台）

---

## 文档版本

| 版本 | 日期 | 主要变更 |
|---|---|---|
| v1.0 | 2026-08-05 | 首次沉淀：4 条强制规范 + 故障排查清单（源于 2026-08-05 部署事故） |

---

## 一、背景与适用范围

zeroAgent 前端为 Next.js 15 应用，通过 Docker Compose 部署在 `zeroagent-web`（员工端 3000）与 `zeroagent-admin-web`（管理后台 3001）两个独立容器中。两个前端都通过 Next.js `rewrites` 把 `/api/*` 同源代理到 FastAPI 后端 `api:8000`。

本规范为 2026-08-05 部署事故沉淀的**强制规范**，目的是避免后续重复踩坑。

---

## 二、强制规范（共 4 条）

### 规范 ① 区分两种 `*_PROXY_TARGET` 环境变量

Next.js 项目存在两种作用范围完全不同的代理目标环境变量，**必须同时声明**：

| 变量名 | 读取方 | 作用范围 | 注入时机 |
|---|---|---|---|
| `API_PROXY_TARGET` | `next.config.ts`（服务端） | `rewrites()` 代理到 FastAPI | `next build` 时 webpack 内联到 server bundle |
| `NEXT_PUBLIC_API_PROXY_TARGET` | 浏览器侧业务代码 | 客户端直接调用后端（可选） | `next build` 时内联到 client bundle |

**反例**：
```ts
// next.config.ts —— 仅依赖 API_PROXY_TARGET
const api = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";
```
如果 Dockerfile 未声明 `ENV API_PROXY_TARGET`，构建时 `process.env.API_PROXY_TARGET` 为 `undefined`，触发 fallback 默认值，**即使 compose 注入了环境变量也无效**（因为 bundle 已被冻结）。

### 规范 ② Dockerfile builder 阶段必须同时声明两个 `ENV`

每个前端 Dockerfile 的 **builder 阶段**必须显式声明：

```dockerfile
# web/Dockerfile 或 admin-web/Dockerfile
FROM node:18-alpine AS builder
...
# API_PROXY_TARGET：next.config.ts 中 rewrites 运行时读取，Docker 容器内必须用 compose 服务名 api:8000
ENV API_PROXY_TARGET=http://api:8000
ENV NEXT_PUBLIC_API_PROXY_TARGET=http://api:8000
```

**禁止**只声明 `NEXT_PUBLIC_*`。两个值在生产环境中通常相同（`http://api:8000`），但必须分开写，因为它们对应不同的代码路径。

### 规范 ③ 容器内 API 地址必须用 compose 服务名

Docker Compose 网络内，前端访问后端必须使用**服务名**作为主机名：

| 场景 | ❌ 错误写法 | ✅ 正确写法 |
|---|---|---|
| 容器内前端 → 后端 | `http://127.0.0.1:8000`（指向容器自身） | `http://api:8000`（compose 服务名） |
| 宿主机浏览器 → 前端 | `http://api:8000`（不可达） | `http://localhost:3000` / `http://localhost:3001` |
| 宿主机 dev → 后端 | `http://api:8000`（不可达） | `http://127.0.0.1:8000` |

`.env.example` 中 `API_PROXY_TARGET=http://127.0.0.1:8000` 仅供**宿主机本地 dev** 使用；Docker 部署时由 `docker-compose.yml` 覆盖为 `http://api:8000`。

### 规范 ④ 修改前端配置后必须 `docker compose build --no-cache`

`next build` 阶段会把 `process.env.*` 内联到 bundle。**仅 `docker compose up -d` 不会重新打包**。规则：

| 改动类型 | 是否需 `--build` | 是否需 `--no-cache` |
|---|---|---|
| 改 `next.config.ts` | ✅ 必须 | ✅ 推荐 |
| 改 Dockerfile ENV | ✅ 必须 | ✅ 推荐 |
| 改 `package.json`（含依赖） | ✅ 必须 | ✅ 必须 |
| 改 `docker-compose.yml` 环境变量注入 | ❌ 否（runtime 注入） | ❌ 否 |
| 改业务代码 `.tsx/.ts` | ✅ 必须 | ❌ 否（依赖 layer cache） |

**推荐命令**：
```bash
docker compose build --no-cache web admin_web
docker compose up -d web admin_web
```

---

## 三、真实故障案例（2026-08-05 事故复盘）

### 案例 A：admin-web 容器从未运行

| 现象 | `docker compose ps` 中无 `zeroagent-admin-web` 容器 |
|---|---|
| 根因 | Next.js `next build` typecheck 失败，镜像未生成；且 19 个 TS 错误集中在 `l2-keywords/page.tsx`、`memory-fields/page.tsx` |
| 修复 | 给 `apiJson()` 调用传类型参数；补齐函数参数类型；导入 `TextArea`；Modal 用 `onCancel` 而非 `onClose` |

### 案例 B：端口冲突 `3001: bind: Only one usage`

| 现象 | `docker compose up admin_web` 报端口被占用 |
|---|---|
| 根因 | Cursor IDE 内嵌 `node.exe`（PID 28356）持续占用宿主机 3001，是用户在 Cursor 终端启动的 `npm run dev` 残留进程 |
| 修复 | `Stop-Process -Id 28356 -Force`；后续注意：本地 dev 与 Docker 部署互斥，先停一边 |

### 案例 C：端口映射错配 `3001:3000`

| 现象 | 容器启动成功，但宿主 3001 访问不到 |
|---|---|
| 根因 | `admin-web/package.json` 的 start 脚本是 `next start -p 3001`（容器内固定监听 3001），但 `docker-compose.yml:245` 写的是 `"3001:3000"` |
| 修复 | 改为 `"3001:3001"`，与 `web` 端 `3000:3000` 形成对称约定 |

### 案例 D：登录 500 `ECONNREFUSED 127.0.0.1:8000`

| 现象 | 登录请求 `POST /api/v1/auth/login` 返回 500，日志 `connect ECONNREFUSED 127.0.0.1:8000` |
|---|---|
| 根因 | Dockerfile builder 阶段**未声明** `ENV API_PROXY_TARGET`，构建时 `process.env.API_PROXY_TARGET` 为 `undefined`，fallback 到 `next.config.ts` 默认值 `http://127.0.0.1:8000`；容器内 127.0.0.1 是自身无后端 |
| 修复 | Dockerfile builder 阶段补 `ENV API_PROXY_TARGET=http://api:8000`；compose 同时注入 `API_PROXY_TARGET` 与 `NEXT_PUBLIC_API_PROXY_TARGET`；**重新 `docker compose build --no-cache`** |

---

## 四、故障排查清单

当出现"前端容器运行但 API 500"时，按以下顺序排查：

1. **直接打后端**：
   ```bash
   curl -i http://127.0.0.1:8000/api/v1/auth/login -X POST \
     -H "Content-Type: application/json" \
     --data-raw '{"username":"demo","password":"demo1234"}'
   ```
   预期：HTTP 200 + JSON。失败 → 后端问题，与前端无关。

2. **直连容器 exec**：
   ```bash
   docker exec zeroagent-web env | grep -E 'PROXY|API'
   docker exec zeroagent-admin-web env | grep -E 'PROXY|API'
   ```
   预期：两行 `API_PROXY_TARGET=http://api:8000` + `NEXT_PUBLIC_API_PROXY_TARGET=http://api:8000`。无 → compose `environment` 配置缺失。

3. **看容器日志**：
   ```bash
   docker logs --tail 50 zeroagent-web
   docker logs --tail 50 zeroagent-admin-web
   ```
   关键词：
   - `ECONNREFUSED 127.0.0.1:8000` → 规范 ②/③/④ 违规，未在构建期注入环境变量
   - `ECONNREFUSED api:8000` → api 容器未启动或健康检查未过
   - `bind: address already in use` → 宿主机端口被占用（规范 ② 案例 B）

4. **核对 bundle 内联值**：
   ```bash
   docker exec zeroagent-web sh -c "grep -r '127.0.0.1:8000\|api:8000' /app/.next/server/ 2>/dev/null | head"
   ```
   预期：仅出现 `api:8000`。出现 `127.0.0.1:8000` → 需 `docker compose build --no-cache`。

5. **端口占用排查**：
   ```bash
   netstat -ano | findstr ":3000"  # 宿主 3000
   netstat -ano | findstr ":3001"  # 宿主 3001
   ```
   占用进程：PowerShell `Get-Process -Id <PID>`。若为 IDE 内嵌 dev server，先停本地 dev 再启 Docker。

---

## 五、CI/CD 建议（待办）

未来可在 CI 流水线加入以下守门项：

- [ ] 前端 Dockerfile builder 阶段 `ENV` 注入 lint：检测 `API_PROXY_TARGET` 与 `NEXT_PUBLIC_API_PROXY_TARGET` 同时存在
- [ ] TypeScript 严格模式：禁止 `apiJson()` 调用缺泛型（可通过 ESLint 自定义规则实现）
- [ ] 部署流水线：检测到 `next.config.ts` / Dockerfile / `package.json` 变更时，强制 `docker compose build --no-cache` 而非 `up -d`

---

## 六、相关文件

- `web/Dockerfile` — 员工端构建
- `web/next.config.ts` — 员工端 Next.js 配置（含 rewrites）
- `admin-web/Dockerfile` — 管理后台构建
- `admin-web/next.config.ts` — 管理后台 Next.js 配置（含 rewrites）
- `deploy/docker-compose.yml` — 编排文件
- `deploy/.env.example` — 环境变量模板
- `docs/04-部署运维/DockerCompose.md` — 总体 Compose 部署文档

---

> 维护者：赵振明
> 最后更新：2026-08-05 11:54:05（东八区）
