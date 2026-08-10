/**
 * 管理端壳内未知路径：仅主内容区提示，侧栏/顶栏保持由 (admin)/layout 提供。
 *
 * @author 赵振明
 * @date 2026-08-10 13:52:30
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAdminPageTitle } from "@/components/AdminTitle";

export default function AdminCatchAllPage() {
  const pathname = usePathname() || "/";
  useAdminPageTitle("页面未找到");

  return (
    <div style={{ padding: 24, maxWidth: 560 }}>
      <h2 style={{ margin: "0 0 8px", fontSize: 20 }}>页面不存在</h2>
      <p style={{ color: "var(--text-secondary)", margin: "0 0 16px" }}>
        路径 <code>{pathname}</code> 尚未接入或地址有误。侧栏与顶栏保持不变，可继续切换其它菜单。
      </p>
      <Link href="/overview" style={{ color: "var(--primary)" }}>
        返回概览
      </Link>
    </div>
  );
}
