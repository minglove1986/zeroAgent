"use client";

/**
 * 根 layout 级崩溃兜底：自带 html/body + 500 插画。
 *
 * @author 赵振明
 * @date 2026-08-11 16:21:00
 */
import Link from "next/link";
import { Button } from "antd";
import { ErrorHero } from "@/components/ErrorHero";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  console.error(error);
  return (
    <html lang="zh-CN">
      <body style={{ margin: 0 }}>
        <ErrorHero
          kind="500"
          onRetry={reset}
          extraAction={
            <Link href="/login">
              <Button>返回登录</Button>
            </Link>
          }
        />
      </body>
    </html>
  );
}
