/**
 * 管理端壳内 notFound()：仍走 (admin)/layout，避免整页丢失侧栏。
 *
 * @author 赵振明
 * @date 2026-08-11 16:21:00
 */
"use client";

import { useAdminPageTitle } from "@/components/AdminTitle";
import { ErrorHero } from "@/components/ErrorHero";

export default function AdminNotFound() {
  useAdminPageTitle("页面未找到");
  return <ErrorHero kind="404" />;
}
