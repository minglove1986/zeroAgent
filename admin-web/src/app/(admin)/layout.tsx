/**
 * 管理端业务页持久布局：侧栏/顶栏跨路由保持，仅主内容区切换。
 *
 * @author 赵振明
 * @date 2026-08-10 13:45:12
 */
"use client";

import type { ReactNode } from "react";
import { AdminLayout } from "@/components/AdminLayout";

export default function AdminSectionLayout({ children }: { children: ReactNode }) {
  return <AdminLayout>{children}</AdminLayout>;
}
