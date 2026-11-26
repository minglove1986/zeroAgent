# 管理端 404/500 错误拦截页（插画）

> 状态：已实现（ErrorHero + 壳内 not-found/error + 根兜底）  
> 日期：2026-08-11 16:17:51（东八区）  
> 作者：赵振明  
> 依据：主 PRD D48 / 权限用户菜单 PRD §9.0 壳内 404；会话裁定：路由级 A、壳内展示、操作 A、方案 1  
> 素材：用户提供 404「形象丢失」、500「服务器出错」插画
> 计划：`docs/superpowers/plans/2026-08-11-admin-error-pages.md`

## 1. 目标与非目标

### 1.1 目标

1. 管理端 **未知路由** 展示统一 404 插画页（保留侧栏/顶栏）。
2. 管理端 **(admin) 子树渲染崩溃** 展示统一 500 插画页（保留壳；可重试）。
3. 根级 / global 崩溃有兜底 500（可能无壳）。
4. 插画使用用户提供图；操作：404→返回概览；500→重试 + 返回概览。

### 1.2 非目标

- 拦截业务 API 4xx/5xx 跳转错误页（继续 Toast / 页内提示）。
- 业务资源 404（如用户详情不存在）强制改走插画路由页（可继续页内空态；后续可选）。
- 员工端 `web/`、`/403` 换图。
- 在页面上重复绘制图内已有大标题文案。

## 2. 裁定摘要

| 项 | 裁定 |
|---|---|
| 范围 | 路由级 404 + 渲染/未捕获异常 500 |
| 布局 | 壳内（`(admin)` 内保留侧栏顶栏） |
| 操作 | 404：返回概览；500：重试 + 返回概览 |
| 实现 | Next App Router 约定文件 + `ErrorHero` |

## 3. 资源

| 文件 | 说明 |
|---|---|
| `admin-web/public/error/404.png` | 404 提示图（形象丢失） |
| `admin-web/public/error/500.png` | 500 提示图（服务器出错） |

来源：会话附图拷贝；若含「豆包AI生成」水印，能裁则裁，否则原图入库并在本规格备注。

## 4. 组件

`admin-web/src/components/ErrorHero.tsx`（`"use client"`）

- Props：`kind: "404" | "500"`；`onRetry?: () => void`
- 内容区垂直居中；`<img src={/error/404.png|500.png} alt=... />`（或 `next/image`，注意 public 静态路径）
- 按钮：
  - 404：`Link`/`router.push` → `/overview`「返回概览」
  - 500：主按钮「重试」→ `onRetry`；次按钮「返回概览」
- 调用方设置 `useAdminPageTitle`（壳内）或自设 document title（global）

## 5. 路由挂载

| 文件 | 行为 |
|---|---|
| `(admin)/not-found.tsx` | `ErrorHero kind="404"` + 页标题「页面未找到」 |
| `(admin)/[...slug]/page.tsx` | 直接渲染 `ErrorHero kind="404"`（与 not-found 同视觉；避免仅 `notFound()` 在无会话探测时难验） |
| `(admin)/error.tsx` | `ErrorHero kind="500" onRetry={reset}`；`console.error(error)` |
| `app/error.tsx` | 非壳路由崩溃：全屏 `ErrorHero` 500 |
| `app/global-error.tsx` | 根 layout 崩溃：自带 html/body + 500 + 回 `/login` |

## 6. 验收

- [ ] 访问不存在路径（如 `/organization/no-such-page`）→ 壳内 404 插画 + 可回概览
- [ ] 临时在某 `(admin)` 页 `throw new Error("boom")` → 壳内 500 插画；点重试可恢复（去掉 throw 后）
- [ ] 侧栏在 404/壳内 500 时仍可见可点
- [ ] 图加载正常；无叠加大标题

## 7. 风险

| 风险 | 应对 |
|---|---|
| `error.tsx` 无法捕获事件处理器内错误 / async 未处理 rejection | 文档说明边界；关键路径仍用 try/catch + Toast |
| 大图体积 | public 已用压缩图；必要时后续再压 |
| global-error 无壳 | 预期行为；提供回登录 |

## 8. 实现后

- 更新 `docs/superpowers/CHECKPOINT.md`
- 计划文件：`docs/superpowers/plans/2026-08-11-admin-error-pages.md`（确认规格后编写）
