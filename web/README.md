# zeroAgent Web（Next.js）

> 同仓前端 · PRD D34 · 2026-07-21

## 职责

- 登录（Session Cookie，经 rewrite 代理到 FastAPI）
- **系统对话页**（SSE + 交互卡片 / ask_user）
- 控制台：Agent / KB / 工作流 / 用量等

## 本地

```bash
# 终端 1：后端
uvicorn app.main:app --app-dir src --reload --port 8000

# 终端 2：前端
cd web
cp .env.example .env.local
npm install
npm run dev
```

浏览器打开 http://127.0.0.1:3000 。  
`/api/*` 默认代理到 `http://127.0.0.1:8000`。

## 约定

- 不另开前端仓库
- 业务 API 以 `docs/01-产品需求/API接口规范.md` 为准
- 实现节奏：后端 Task 推进后，再补对应页面（优先登录 + 系统对话）
