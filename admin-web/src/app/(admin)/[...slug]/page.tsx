/**
 * 管理端壳内未知路径：内容区展示 404 插画（侧栏由 (admin)/layout 保留）。
 *
 * @author 赵振明
 * @date 2026-08-11 16:21:00
 */
"use client";

import { useAdminPageTitle } from "@/components/AdminTitle";
import { ErrorHero } from "@/components/ErrorHero";

export default function AdminCatchAllPage() {
  useAdminPageTitle("页面未找到");
  return <ErrorHero kind="404" />;
}
