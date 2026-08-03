/**
 * 控制台概览：白名单/L2 计数、缓存健康、近 24h 审计。
 *
 * @author 赵振明
 * @date 2026-07-29 15:10:45
 */
"use client";

import { useEffect, useState } from "react";
import { Card, Col, message, Row, Tag } from "antd";
import { AdminLayout } from "@/components/AdminLayout";
import { apiJson } from "@/lib/api";

type CacheStatus = {
  redis_ok?: boolean;
  catalog_version?: string | number | null;
};

type OverviewData = {
  memory_fields: {
    total: number;
    enabled: number;
    disabled: number;
    cache: CacheStatus;
  };
  l2_keywords: {
    total: number;
    enabled: number;
    disabled: number;
    cache: CacheStatus;
  };
  audit_24h: number;
  recent_audits: Array<{
    id: string;
    actor_id: string;
    action: string;
    resource_type: string;
    summary: string;
    created_at: string | null;
  }>;
};

export default function OverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiJson<OverviewData>("/api/v1/admin/overview");
        if (cancelled) return;
        if (res.code !== 0 || !res.data) {
          setError(res.message || "加载概览失败");
          message.error(res.message || "加载概览失败");
          return;
        }
        setData(res.data);
      } catch (e) {
        if (cancelled) return;
        console.error(e);
        setError("加载概览失败");
        message.error("加载概览失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AdminLayout title="控制台概览">
      {!data ? (
        <div style={{ padding: 20 }}>{error || "加载中..."}</div>
      ) : (
        <div>
          <Row gutter={[24, 24]}>
            <Col span={6}>
              <Card bordered={false}>
                <h3 style={{ margin: "0 0 10px" }}>记忆抽取白名单</h3>
                <p style={{ fontSize: 32, fontWeight: "bold", color: "var(--primary)" }}>
                  {data.memory_fields.total}
                </p>
                <p style={{ fontSize: 12, color: "var(--text-secondary)" }}>总字段数</p>
                <Tag color="green">{data.memory_fields.enabled} 启用</Tag>
                <Tag>{data.memory_fields.disabled} 停用</Tag>
              </Card>
            </Col>
            <Col span={6}>
              <Card bordered={false}>
                <h3 style={{ margin: "0 0 10px" }}>L2 关键词规则</h3>
                <p style={{ fontSize: 32, fontWeight: "bold", color: "var(--primary)" }}>
                  {data.l2_keywords.total}
                </p>
                <p style={{ fontSize: 12, color: "var(--text-secondary)" }}>总短语数</p>
                <Tag color="green">{data.l2_keywords.enabled} 启用</Tag>
                <Tag>{data.l2_keywords.disabled} 停用</Tag>
              </Card>
            </Col>
            <Col span={6}>
              <Card bordered={false}>
                <h3 style={{ margin: "0 0 10px" }}>缓存健康度</h3>
                <p style={{ fontSize: 14, marginBottom: 8 }}>
                  白名单: {data.memory_fields.cache?.redis_ok ? "正常" : "异常"}
                </p>
                <p style={{ fontSize: 14, marginBottom: 8 }}>
                  L2: {data.l2_keywords.cache?.redis_ok ? "正常" : "异常"}
                </p>
                <p style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  版本: {String(data.memory_fields.cache?.catalog_version ?? "-")}
                </p>
              </Card>
            </Col>
            <Col span={6}>
              <Card bordered={false}>
                <h3 style={{ margin: "0 0 10px" }}>近期变更</h3>
                <p style={{ fontSize: 32, fontWeight: "bold", color: "var(--danger)" }}>
                  {data.audit_24h}
                </p>
                <p style={{ fontSize: 12, color: "var(--text-secondary)" }}>过去 24h</p>
                <Tag color="blue">配置审计记录</Tag>
              </Card>
            </Col>
          </Row>

          <div style={{ marginTop: 30 }}>
            <h3>最近 8 条审计日志</h3>
            <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 10 }}>
              <thead>
                <tr style={{ borderBottom: "2px solid var(--border-color)" }}>
                  <th style={{ textAlign: "left", padding: 8 }}>时间</th>
                  <th style={{ textAlign: "left", padding: 8 }}>操作人</th>
                  <th style={{ textAlign: "left", padding: 8 }}>动作</th>
                  <th style={{ textAlign: "left", padding: 8 }}>资源</th>
                  <th style={{ textAlign: "left", padding: 8 }}>摘要</th>
                </tr>
              </thead>
              <tbody>
                {(data.recent_audits || []).map((a) => (
                  <tr key={a.id} style={{ borderBottom: "1px solid var(--border-color)" }}>
                    <td style={{ padding: 8 }}>
                      {a.created_at ? new Date(a.created_at).toLocaleString() : "-"}
                    </td>
                    <td style={{ padding: 8 }}>{a.actor_id}</td>
                    <td style={{ padding: 8 }}>{a.action}</td>
                    <td style={{ padding: 8 }}>{a.resource_type}</td>
                    <td
                      style={{
                        padding: 8,
                        maxWidth: 240,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {a.summary}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </AdminLayout>
  );
}
