# zeroAgent Admin Web (管理端)

同仓管理的独立 Next.js 应用，端口 **3001**。

## 开发流程

```bash
# 1. 进入 admin-web 目录
cd admin-web

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev
# 访问 http://127.0.0.1:3001
```

## 后端要求

- FastAPI 运行于 `http://127.0.0.1:8000`
- 用户需先通过 `/api/v1/auth/login` 登录获取 Session Cookie
- 管理端接口（overview、memory-fields、l2-keywords、audit-logs）需要 `platform_admin` / `super_admin` 角色

## 目录结构

```
admin-web/
├── src/
│   ├── app/          # Next.js App Router 页面
│   │   ├── layout.tsx            # 根布局（含 CSS 变量）
│   │   ├── globals.css           # 双主题样式表
│   │   ├── login/page.tsx        # 登录页
│   │   ├── overview/page.tsx     # 管理概览
│   │   ├── system/               # 配置管理页
│   │   │   ├── memory-fields/    # 记忆抽取白名单
│   │   │   └── l2-keywords/      # L2 关键词规则
│   │   └── operations/           # 审计
│   │       └── audit/            # 配置变更审计
│   └── components/               # UI 组件
│       ├── AppNav.tsx            # 固定侧边栏 + 顶部栏
│       ├── ThemeSwitcher.tsx     # 明暗主题切换
│       └── AdminLayout.tsx       # 页面外壳
├── lib/                        # 工具库
│   ├── api.ts                  # 类型化 fetch 封装
│   └── auth.tsx                # 客户端会话守卫（待补充）
├── .env.example                # 环境变量模板
├── next.config.ts              # API 代理转发
└── package.json                # 依赖与脚本
```

## 设计要点

- **三段式布局**：左侧固定侧边栏 (250px) + 顶部固定导航栏 (60px) + 右侧主内容区
- **明暗双主题**：遵循系统默认，可本地持久化切换
- **同仓部署**：通过 Next.js rewrite 将 `/api/*` 转发至 FastAPI (`:8000`)，共享 Session Cookie
- **权限校验**：`AdminLayout` 内校验 `require_platform_admin`，未授权跳转 `/403`
- **规划中页面**：Agents、Knowledge、Workflows、KnowledgeGraph 目前仅展示占位文本