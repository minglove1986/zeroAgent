/**
 * 管理页外壳：侧栏 + 顶栏 + 主内容，外层强制 AdminGuard。
 * 须挂在 Next.js 路由 layout 中，保证跨页导航时壳层不卸载。
 *
 * @author 赵振明
 * @date 2026-08-10 13:45:12
 */
"use client";

import type { ReactNode } from "react";
import AppNav from "./AppNav";
import { AdminTitleProvider } from "./AdminTitle";
import { AdminGuard } from "@/lib/auth";

export function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AdminGuard>
      <AdminTitleProvider>
        <AppNav>{children}</AppNav>
      </AdminTitleProvider>
    </AdminGuard>
  );
}
