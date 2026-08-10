/**
 * 通知告警占位页。
 *
 * @author 赵振明
 * @date 2026-08-10 13:52:30
 */
"use client";

import { useAdminPageTitle } from "@/components/AdminTitle";

export default function AlertsPage() {
  useAdminPageTitle("通知告警");
  return (
    <div style={{ padding: 20 }}>
      <h1>通知告警</h1>
      <p style={{ color: "var(--text-secondary)" }}>站内通知与 Webhook 告警配置（规划中）</p>
    </div>
  );
}
