/**
 * 管理页外壳：侧栏 + 顶栏 + 主内容，外层强制 AdminGuard；注入 antd App。
 *
 * @author 赵振明
 * @date 2026-09-09 15:08:00
 */
"use client";

import type { ReactNode } from "react";
import { App } from "antd";
import AppNav from "./AppNav";
import { AdminTitleProvider } from "./AdminTitle";
import { AdminGuard } from "@/lib/auth";

/**
 * 管理端持久壳：鉴权 + antd App 上下文（message/modal）+ 侧栏。
 *
 * @author 赵振明
 * @date 2026-09-09 15:08:00
 */
export function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AdminGuard>
      <App>
        <AdminTitleProvider>
          <AppNav>{children}</AppNav>
        </AdminTitleProvider>
      </App>
    </AdminGuard>
  );
}
