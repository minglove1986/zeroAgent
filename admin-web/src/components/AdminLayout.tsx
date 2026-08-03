/**
 * 管理页外壳：侧栏 + 顶栏 + 主内容，外层强制 AdminGuard。
 *
 * @author 赵振明
 * @date 2026-07-29 15:10:45
 */
"use client";

import type { ReactNode } from "react";
import AppNav from "./AppNav";
import { AdminGuard } from "@/lib/auth";

export function AdminLayout({
  title,
  children,
}: {
  title?: string;
  children: ReactNode;
}) {
  return (
    <AdminGuard>
      <AppNav title={title}>{children}</AppNav>
    </AdminGuard>
  );
}
