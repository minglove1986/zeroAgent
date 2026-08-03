/**
 * 管理端首页：跳转概览。
 *
 * @author 赵振明
 * @date 2026-07-29 15:10:45
 */
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/overview");
  }, [router]);
  return <div style={{ padding: 24 }}>正在进入控制台...</div>;
}
