/**
 * 知识库审计（波次 5；无接口时保持占位）。
 * @author 赵振明
 * @date 2026-11-20 14:22:56
 */
"use client";

import { Typography } from "antd";
import { useAdminPageTitle } from "@/components/AdminTitle";

const { Paragraph, Title } = Typography;

export default function KnowledgeAuditPage() {
  useAdminPageTitle("知识库审计");
  return (
    <div style={{ padding: 20 }}>
      <Title level={3}>知识库审计</Title>
      <Paragraph type="secondary">
        规划对接 GET /api/v1/admin/kb-audit-events。当前后端若未实现，本页仅占位，不展示假数据。
      </Paragraph>
    </div>
  );
}
