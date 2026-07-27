# Task 6 报告：重做 `/knowledge` 管理闭环 UI

- **Status**: DONE（2026-07-23 09:28:43 东八区）
- **Changed**: `web/src/app/knowledge/page.tsx` 左 KB 列表+新建 / 右上传+文档表+权限面板；`processing` 每 2s 轮询 status；发布/软删/恢复；`include_deleted=1`；`globals.css` 增加 `.kb-*`
- **Concerns**: 前端未存 role，新建/写权限靠后端 403；联调需后端+登录态+Celery；未跑浏览器
- **Path**: `web/src/app/knowledge/page.tsx`；`web/src/app/globals.css`
- **Manual checklist**
  1. 超管建库出现在列表 — 代码路径已接 POST/GET；**需浏览器+超管会话**
  2. PUT user 权限后 employee 可见 — API 已绑；**需双角色联调**
  3. 上传 txt → processing → ready — 轮询已接；**需 Celery worker**
  4. 无 QA 发布 → 42201 — 展示 `body.message`；**需浏览器点发布**
  5. 软删+恢复提示 — 列表 `include_deleted=1`+恢复文案已写；**需浏览器验证**
  - 无浏览器可核：页面编译结构、API 路径与 `apiJson`/`code` 处理逻辑
