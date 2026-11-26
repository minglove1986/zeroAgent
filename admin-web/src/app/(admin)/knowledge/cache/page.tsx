/**
 * 知识库缓存（波次 5；无接口时保持占位）。
 * @author 赵振明
 * @date 2026-11-20 14:22:56
 */
"use client";

import { Typography } from "antd";
import { useAdminPageTitle } from "@/components/AdminTitle";

const { Paragraph, Title } = Typography;

export default function KnowledgeCachePage() {
  useAdminPageTitle("知识库缓存");
  return (
    <div style={{ padding: 20 }}>
      <Title level={3}>知识库缓存</Title>
      <Paragraph type="secondary">
        规划对接缓存统计与 purge。当前后端若未实现，本页仅占位。
      </Paragraph>
    </div>
  );
}
