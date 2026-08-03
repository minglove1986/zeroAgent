/**
 * 配置变更审计列表（记忆白名单 / L2 关键词相关）。
 *
 * @author 赵振明
 * @date 2026-07-29 15:10:45
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Col,
  DatePicker,
  Form,
  message,
  Row,
  Select,
  Table,
  Tag,
} from "antd";
import type { Dayjs } from "dayjs";
import { AdminLayout } from "@/components/AdminLayout";
import { apiJson } from "@/lib/api";

type AuditItem = {
  id: string;
  created_at?: string;
  actor_id?: string;
  actor_role?: string;
  action?: string;
  resource_type?: string;
  resource_id?: string;
  summary?: string;
  result?: string;
};

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [filterResource, setFilterResource] = useState<string | undefined>();
  const [filterAction, setFilterAction] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [page, setPage] = useState(1);
  const pageSize = 10;

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterResource) params.append("resource_type", filterResource);
      if (filterAction) params.append("action", filterAction);
      if (dateRange?.[0] && dateRange?.[1]) {
        params.append("start_date", dateRange[0].toISOString());
        params.append("end_date", dateRange[1].toISOString());
      }
      params.append("page", String(page));
      params.append("page_size", String(pageSize));

      const res = await apiJson<{ items: AuditItem[]; total: number }>(
        `/api/v1/audit-logs?${params.toString()}`,
      );
      if (res.code === 0 && res.data) {
        setLogs(res.data.items || []);
        setTotal(res.data.total || 0);
      } else {
        message.error(res.message || "加载失败");
      }
    } catch (e) {
      console.error(e);
      message.error("网络错误");
    } finally {
      setLoading(false);
    }
  }, [filterResource, filterAction, dateRange, page]);

  useEffect(() => {
    void fetchLogs();
  }, [fetchLogs]);

  const handleResetFilters = () => {
    setFilterResource(undefined);
    setFilterAction(undefined);
    setDateRange(null);
    setPage(1);
  };

  const columns = [
    {
      title: "时间",
      dataIndex: "created_at",
      render: (text: string) => (text ? new Date(text).toLocaleString() : "-"),
    },
    { title: "操作人", dataIndex: "actor_id" },
    { title: "角色", dataIndex: "actor_role" },
    {
      title: "动作",
      dataIndex: "action",
      render: (text: string) => <Tag color="blue">{text}</Tag>,
    },
    { title: "资源类型", dataIndex: "resource_type" },
    { title: "资源ID", dataIndex: "resource_id" },
    { title: "摘要", dataIndex: "summary", width: 200 },
    {
      title: "结果",
      dataIndex: "result",
      render: (v: string) => (
        <Tag color={v === "success" ? "green" : "red"}>{v}</Tag>
      ),
    },
  ];

  return (
    <AdminLayout title="配置变更审计">
      <div>
        <Row gutter={[16, 16]} style={{ marginBottom: 20 }} justify="space-between">
          <Col span={24}>
            <Form layout="inline" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              <Form.Item label="资源类型">
                <Select
                  allowClear
                  style={{ width: 180 }}
                  value={filterResource}
                  onChange={setFilterResource}
                  placeholder="全部"
                  options={[
                    { value: "memory_extract_field", label: "记忆字段" },
                    { value: "intent_l2_keyword", label: "L2关键词" },
                  ]}
                />
              </Form.Item>
              <Form.Item label="动作">
                <Select
                  allowClear
                  style={{ width: 160 }}
                  value={filterAction}
                  onChange={setFilterAction}
                  placeholder="全部"
                  options={[
                    { value: "create", label: "创建" },
                    { value: "update", label: "更新" },
                    { value: "delete", label: "删除" },
                    { value: "reset_default", label: "恢复默认" },
                    { value: "reload_cache", label: "重载缓存" },
                    { value: "test", label: "规则试跑" },
                  ]}
                />
              </Form.Item>
              <Form.Item label="日期范围">
                <DatePicker.RangePicker
                  value={dateRange}
                  onChange={(v) => setDateRange(v)}
                />
              </Form.Item>
              <Form.Item>
                <Button type="primary" onClick={() => void fetchLogs()}>
                  查询
                </Button>
              </Form.Item>
              <Form.Item>
                <Button onClick={handleResetFilters}>重置</Button>
              </Form.Item>
            </Form>
          </Col>
        </Row>
        <Table
          loading={loading}
          dataSource={logs}
          columns={columns}
          rowKey="id"
          pagination={{
            total,
            pageSize,
            current: page,
            onChange: setPage,
          }}
        />
      </div>
    </AdminLayout>
  );
}
