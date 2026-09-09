"use client";

/**
 * 根级错误边界：登录等非壳路由崩溃时全屏 500。
 *
 * @author 赵振明
 * @date 2026-08-11 16:21:00
 */
import { useEffect } from "react";
import { ErrorHero } from "@/components/ErrorHero";

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return <ErrorHero kind="500" onRetry={reset} />;
}
