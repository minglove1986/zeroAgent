"use client";

/**
 * 管理端壳内错误边界：渲染崩溃时展示 500 插画（保留侧栏）。
 *
 * @author 赵振明
 * @date 2026-08-11 16:21:00
 */
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
