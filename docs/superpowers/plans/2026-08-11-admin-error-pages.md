# 管理端 404/500 错误插画页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理端壳内统一展示 404/500 插画错误页，未知路径与渲染崩溃可拦截并提供返回概览/重试。

**Architecture:** 静态图放入 `public/error/`；共享 `ErrorHero`；`(admin)/not-found` + `[...slug]`→`notFound()` 统一 404；`(admin)/error.tsx` 壳内 500；根级 `error`/`global-error` 兜底。

**Tech Stack:** Next.js App Router（admin-web）、React client components、Ant Design Button（若项目已用；否则原生 button + 现有 CSS 变量）。

**Spec:** `docs/superpowers/specs/2026-08-11-admin-error-pages-design.md`

## Global Constraints

- D48：业务页不包 `AdminLayout`；壳内 404 保留侧栏
- 不重复图内大标题文案
- 不拦截 API Toast 级错误
- 注释：`@author 赵振明`；东八区实时时间
- **Git commit：** 未获用户明确「提交」指令时跳过 commit 步骤
- 素材路径：会话附图 → `admin-web/public/error/404.png`、`500.png`

---

## File map

| 文件 | 职责 |
|---|---|
| `admin-web/public/error/404.png` | 404 插画 |
| `admin-web/public/error/500.png` | 500 插画 |
| `admin-web/src/components/ErrorHero.tsx` | 插画 + 操作按钮 |
| `admin-web/src/app/(admin)/not-found.tsx` | 壳内 404 |
| `admin-web/src/app/(admin)/[...slug]/page.tsx` | `notFound()` |
| `admin-web/src/app/(admin)/error.tsx` | 壳内 500 |
| `admin-web/src/app/error.tsx` | 非壳 500 |
| `admin-web/src/app/global-error.tsx` | 根崩溃兜底 |
| `docs/superpowers/CHECKPOINT.md` | 断点 |

---

### Task 1: 拷贝静态插画

**Files:**
- Create: `admin-web/public/error/404.png`
- Create: `admin-web/public/error/500.png`

**Interfaces:**
- Produces: HTTP 可访问 `/error/404.png`、`/error/500.png`

- [ ] **Step 1: 创建目录并拷贝**

源文件（Cursor workspaceStorage 附图，路径以本机会话 `image_files` 为准）：

```powershell
New-Item -ItemType Directory -Force -Path "d:\HermesWork\zeroAgent\admin-web\public\error" | Out-Null
Copy-Item -Force "<404源png>" "d:\HermesWork\zeroAgent\admin-web\public\error\404.png"
Copy-Item -Force "<500源png>" "d:\HermesWork\zeroAgent\admin-web\public\error\500.png"
Get-Item "d:\HermesWork\zeroAgent\admin-web\public\error\*.png" | Select-Object Name, Length
```

Expected: 两个文件非空（Length > 0）。

- [ ] **Step 2: Commit（仅用户要求时）**

```bash
git add admin-web/public/error/
git commit -m "assets(admin): add 404 and 500 error illustrations"
```

---

### Task 2: `ErrorHero` 组件

**Files:**
- Create: `admin-web/src/components/ErrorHero.tsx`

**Interfaces:**
- Produces:
```tsx
export type ErrorHeroKind = "404" | "500";
export function ErrorHero(props: {
  kind: ErrorHeroKind;
  onRetry?: () => void;
}): JSX.Element;
```

- [ ] **Step 1: 实现组件**

```tsx
"use client";
/**
 * 管理端错误插画区（404/500）。
 * @author 赵振明
 * @date <东八区实时>
 */
import Link from "next/link";
import { Button, Space } from "antd";

export type ErrorHeroKind = "404" | "500";

const META: Record<ErrorHeroKind, { src: string; alt: string }> = {
  "404": { src: "/error/404.png", alt: "404 形象丢失" },
  "500": { src: "/error/500.png", alt: "服务器出错" },
};

export function ErrorHero({
  kind,
  onRetry,
}: {
  kind: ErrorHeroKind;
  onRetry?: () => void;
}) {
  const meta = META[kind];
  return (
    <div
      style={{
        minHeight: "60vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        textAlign: "center",
      }}
    >
      <img
        src={meta.src}
        alt={meta.alt}
        style={{
          width: "min(520px, 100%)",
          height: "auto",
          objectFit: "contain",
          marginBottom: 20,
        }}
      />
      <Space>
        {kind === "500" && onRetry ? (
          <Button type="primary" onClick={onRetry}>
            重试
          </Button>
        ) : null}
        <Link href="/overview">
          <Button type={kind === "404" ? "primary" : "default"}>返回概览</Button>
        </Link>
      </Space>
    </div>
  );
}
```

- [ ] **Step 2: 手工冒烟** — 暂可在任意页临时 import 渲染后删；或进入 Task 3 一并验。

- [ ] **Step 3: Commit（仅用户要求时）**

```bash
git add admin-web/src/components/ErrorHero.tsx
git commit -m "feat(admin): add ErrorHero for 404/500 illustrations"
```

---

### Task 3: 壳内 404（not-found + catch-all）

**Files:**
- Modify: `admin-web/src/app/(admin)/not-found.tsx`
- Modify: `admin-web/src/app/(admin)/[...slug]/page.tsx`

**Interfaces:**
- Consumes: `ErrorHero`
- Produces: 未知路径 → 壳内插画 404

- [ ] **Step 1: 重写 not-found**

```tsx
"use client";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { ErrorHero } from "@/components/ErrorHero";

export default function AdminNotFound() {
  useAdminPageTitle("页面未找到");
  return <ErrorHero kind="404" />;
}
```

- [ ] **Step 2: catch-all 改为 notFound()**

```tsx
"use client";
import { notFound } from "next/navigation";

export default function AdminCatchAllPage() {
  notFound();
}
```

注意：client 组件直接调用 `notFound()` 在 Next 中可用；若构建告警，改为服务端组件仅一行 `notFound()`（无 `"use client"`）。

- [ ] **Step 3: 验收**

浏览器打开 `http://localhost:3001/organization/no-such-page`  
Expected: 侧栏仍在；内容区为 404 插画；「返回概览」可用。

- [ ] **Step 4: Commit（仅用户要求时）**

```bash
git add "admin-web/src/app/(admin)/not-found.tsx" "admin-web/src/app/(admin)/[...slug]/page.tsx"
git commit -m "feat(admin): shell 404 with ErrorHero"
```

---

### Task 4: 壳内 + 根级 500 边界

**Files:**
- Create: `admin-web/src/app/(admin)/error.tsx`
- Create: `admin-web/src/app/error.tsx`
- Create: `admin-web/src/app/global-error.tsx`

**Interfaces:**
- Consumes: `ErrorHero`；Next `error`/`reset` props

- [ ] **Step 1: `(admin)/error.tsx`**

```tsx
"use client";
import { useEffect } from "react";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { ErrorHero } from "@/components/ErrorHero";

export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useAdminPageTitle("服务异常");
  useEffect(() => {
    console.error(error);
  }, [error]);
  return <ErrorHero kind="500" onRetry={reset} />;
}
```

- [ ] **Step 2: `app/error.tsx`**

同构全屏（可无 `useAdminPageTitle`）；`ErrorHero` + `onRetry={reset}`；次要回概览已在组件内。

- [ ] **Step 3: `app/global-error.tsx`**

```tsx
"use client";
import { ErrorHero } from "@/components/ErrorHero";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  console.error(error);
  return (
    <html lang="zh-CN">
      <body>
        <ErrorHero kind="500" onRetry={reset} />
        {/* 额外：可加 Link 到 /login —— 若 ErrorHero 仅回 overview，global 时 overview 可能不可用；
            实现时在 global-error 下于 ErrorHero 外再放「返回登录」按钮指向 /login */}
      </body>
    </html>
  );
}
```

实现时：`global-error` 在 `ErrorHero` 下方增加 `Link href="/login"`「返回登录」（规格要求）。

- [ ] **Step 4: 验收 500（临时）**

在 `(admin)/overview/page.tsx` 临时加：

```tsx
if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("boom") === "1") {
  throw new Error("boom");
}
```

访问 `/overview?boom=1` → 壳内 500 插画；去掉代码后点「重试」或再进 overview 正常。

**验收完必须删除临时 throw。**

- [ ] **Step 5: Commit（仅用户要求时）**

```bash
git add "admin-web/src/app/(admin)/error.tsx" admin-web/src/app/error.tsx admin-web/src/app/global-error.tsx
git commit -m "feat(admin): error boundaries with 500 illustration"
```

---

### Task 5: 规格状态 + CHECKPOINT

**Files:**
- Modify: `docs/superpowers/specs/2026-08-11-admin-error-pages-design.md`
- Modify: `docs/superpowers/CHECKPOINT.md`

- [ ] **Step 1: 规格文首改为「已实现」**
- [ ] **Step 2: 覆盖写当前断点 + 追加日志**（禁止密钥）
- [ ] **Step 3: Commit（仅用户要求时）**

---

## Spec coverage

| 规格项 | Task |
|---|---|
| 静态图 | 1 |
| ErrorHero | 2 |
| 壳内 404 / catch-all | 3 |
| (admin)/error | 4 |
| app/error + global-error | 4 |
| CHECKPOINT | 5 |

## Placeholder scan

无 TBD；global-error 登录入口写死 `/login`。
