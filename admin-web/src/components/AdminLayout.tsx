/**
 * 管理页外壳：侧栏 + 顶栏 + 主内容，外层强制 AdminGuard；注入 antd App + 系统通知。
 *
 * @author 赵振明
 * @date 2026-11-20 17:14:26
 */
"use client";

import type { ReactNode } from "react";
import { App } from "antd";
import AppNav from "./AppNav";
import { AdminTitleProvider } from "./AdminTitle";
import { AdminGuard } from "@/lib/auth";
import { SystemNotifyProvider } from "@/lib/system-notify";

/**
 * 管理端持久壳：鉴权 + antd App + 全局系统通知（含提示音）。
 *
 * @author 赵振明
 * @date 2026-11-20 17:14:26
 */
export function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AdminGuard>
      <App>
        <SystemNotifyProvider>
          <AdminTitleProvider>
            <AppNav>{children}</AppNav>
          </AdminTitleProvider>
        </SystemNotifyProvider>
      </App>
    </AdminGuard>
  );
}
