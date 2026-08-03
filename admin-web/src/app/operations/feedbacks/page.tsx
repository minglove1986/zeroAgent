/**
 * 消息反馈审阅：汇总卡 + 筛选列表 + 上下文抽屉。
 *
 * @author 赵振明
 * @date 2026-07-30 16:01:04
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Card,
  Col,
  DatePicker,
  Drawer,
  Form,
  Input,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { AdminLayout } from "@/components/AdminLayout";
import { apiJson } from "@/lib/api";

type Stats = {
  total: number;
  up: number;
  down: number;
  with_comment: number;
  success_rate: number | null;
};

type FeedbackItem = {
  id: string;
  rating: string;
  comment?: string | null;
  created_at?: string | null;
  user_id?: string;
  user_name?: string | null;
  conversation_id?: string;
  agent_id?: string | null;
  agent_name?: string | null;
  message_id?: string;
  message_preview?: string | null;
};

type ContextMsg = {
  id: string;
  role: string;
  content?: string | null;
  created_at?: string | null;
  is_target?: boolean;
};

type Detail = FeedbackItem & {
  message_content?: string | null;
  context_messages?: ContextMsg[];
};

function defaultRange(): [Dayjs, Dayjs] {
  return [dayjs().subtract(7, "day"), dayjs()];
}

export default function FeedbacksPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [rating, setRating] = useState<string | undefined>();
  const [hasComment, setHasComment] = useState<string | undefined>();
  const [q, setQ] = useState("");
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(defaultRange());
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const buildParams = useCallback(() => {
    const params = new URLSearchParams();
    if (dateRange?.[0]) params.append("start_date", dateRange[0].toISOString());
    if (dateRange?.[1]) params.append("end_date", dateRange[1].toISOString());
    if (rating) params.append("rating", rating);
    if (hasComment) params.append("has_comment", hasComment);
    if (q.trim()) params.append("q", q.trim());
    return params;
  }, [dateRange, rating, hasComment, q]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const base = buildParams();
      const statsRes = await apiJson<Stats>(
        `/api/v1/admin/feedbacks/stats?${base.toString()}`,
      );
      if (statsRes.code !== 0 || !statsRes.data) {
        message.error(statsRes.message || "加载汇总失败");
      } else {
        setStats(statsRes.data);
      }

      const listParams = new URLSearchParams(base);
      listParams.append("page", String(page));
      listParams.append("page_size", String(pageSize));
      const listRes = await apiJson<{ items: FeedbackItem[]; total: number }>(
        `/api/v1/admin/feedbacks?${listParams.toString()}`,
      );
      if (listRes.code !== 0 || !listRes.data) {
        message.error(listRes.message || "加载列表失败");
        setItems([]);
        setTotal(0);
      } else {
        setItems(listRes.data.items || []);
        setTotal(listRes.data.total || 0);
      }
    } catch (e) {
      console.error(e);
      message.error("网络错误");
    } finally {
      setLoading(false);
    }
  }, [buildParams, page]);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  async function openDetail(id: string) {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      const res = await apiJson<Detail>(`/api/v1/admin/feedbacks/${encodeURIComponent(id)}`);
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "加载详情失败");
        return;
      }
      setDetail(res.data);
    } catch (e) {
      console.error(e);
      message.error("加载详情失败");
    } finally {
      setDetailLoading(false);
    }
  }

  async function copyId(id: string) {
    try {
      await navigator.clipboard.writeText(id);
      message.success("已复制编号");
    } catch {
      message.error("复制失败");
    }
  }

  const columns = [
    {
      title: "编号",
      dataIndex: "id",
      width: 160,
      render: (id: string) => (
        <Space>
          <Typography.Text code>{id}</Typography.Text>
          <Button type="link" size="small" onClick={() => void copyId(id)}>
            复制
          </Button>
        </Space>
      ),
    },
    {
      title: "时间",
      dataIndex: "created_at",
      render: (t?: string | null) => (t ? new Date(t).toLocaleString() : "—"),
    },
    {
      title: "评价",
      dataIndex: "rating",
      render: (r: string) =>
        r === "up" ? <Tag color="green">赞</Tag> : <Tag color="red">踩</Tag>,
    },
    {
      title: "评论",
      dataIndex: "comment",
      ellipsis: true,
      render: (c?: string | null) => c || "—",
    },
    { title: "用户", dataIndex: "user_name", render: (v?: string | null) => v || "—" },
    { title: "Agent", dataIndex: "agent_name", render: (v?: string | null) => v || "—" },
    {
      title: "消息摘要",
      dataIndex: "message_preview",
      ellipsis: true,
      render: (v?: string | null) => v || "—",
    },
    {
      title: "操作",
      key: "op",
      width: 90,
      render: (_: unknown, row: FeedbackItem) => (
        <Button type="link" onClick={() => void openDetail(row.id)}>
          详情
        </Button>
      ),
    },
  ];

  const rateText =
    stats?.success_rate == null ? "—" : `${(stats.success_rate * 100).toFixed(1)}%`;

  return (
    <AdminLayout title="消息反馈">
      <div>
        <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
          <Col xs={24} sm={12} md={4}>
            <Card size="small" loading={loading && !stats}>
              <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>反馈总数</div>
              <div style={{ fontSize: 22, fontWeight: 600 }}>{stats?.total ?? "—"}</div>
            </Card>
          </Col>
          <Col xs={24} sm={12} md={4}>
            <Card size="small">
              <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>👍</div>
              <div style={{ fontSize: 22, fontWeight: 600 }}>{stats?.up ?? "—"}</div>
            </Card>
          </Col>
          <Col xs={24} sm={12} md={4}>
            <Card size="small">
              <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>👎</div>
              <div style={{ fontSize: 22, fontWeight: 600 }}>{stats?.down ?? "—"}</div>
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small">
              <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>问答成功率</div>
              <div style={{ fontSize: 22, fontWeight: 600 }}>{rateText}</div>
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small">
              <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>有文字反馈</div>
              <div style={{ fontSize: 22, fontWeight: 600 }}>{stats?.with_comment ?? "—"}</div>
            </Card>
          </Col>
        </Row>

        <Form layout="inline" style={{ marginBottom: 16, display: "flex", flexWrap: "wrap", gap: 8 }}>
          <Form.Item label="日期">
            <DatePicker.RangePicker
              value={dateRange}
              onChange={(v) => {
                setPage(1);
                setDateRange(v as [Dayjs, Dayjs] | null);
              }}
            />
          </Form.Item>
          <Form.Item label="评价">
            <Select
              allowClear
              style={{ width: 120 }}
              value={rating}
              onChange={(v) => {
                setPage(1);
                setRating(v);
              }}
              options={[
                { value: "up", label: "赞" },
                { value: "down", label: "踩" },
              ]}
              placeholder="全部"
            />
          </Form.Item>
          <Form.Item label="评论">
            <Select
              allowClear
              style={{ width: 140 }}
              value={hasComment}
              onChange={(v) => {
                setPage(1);
                setHasComment(v);
              }}
              options={[
                { value: "true", label: "有评论" },
                { value: "false", label: "无评论" },
              ]}
              placeholder="全部"
            />
          </Form.Item>
          <Form.Item label="关键词">
            <Input
              allowClear
              style={{ width: 200 }}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onPressEnter={() => {
                setPage(1);
                void fetchAll();
              }}
              placeholder="评论/消息"
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              onClick={() => {
                setPage(1);
                void fetchAll();
              }}
            >
              查询
            </Button>
          </Form.Item>
          <Form.Item>
            <Button
              onClick={() => {
                setRating(undefined);
                setHasComment(undefined);
                setQ("");
                setDateRange(defaultRange());
                setPage(1);
              }}
            >
              重置
            </Button>
          </Form.Item>
        </Form>

        <Table
          loading={loading}
          dataSource={items}
          columns={columns}
          rowKey="id"
          pagination={{
            total,
            pageSize,
            current: page,
            onChange: setPage,
          }}
        />

        <Drawer
          title={detail ? `反馈 ${detail.id}` : "反馈详情"}
          width={560}
          open={detailOpen}
          onClose={() => setDetailOpen(false)}
          destroyOnClose
        >
          {detailLoading || !detail ? (
            <div>{detailLoading ? "加载中…" : "无数据"}</div>
          ) : (
            <div>
              <Space style={{ marginBottom: 12 }}>
                {detail.rating === "up" ? (
                  <Tag color="green">赞</Tag>
                ) : (
                  <Tag color="red">踩</Tag>
                )}
                <Button size="small" onClick={() => void copyId(detail.id)}>
                  复制编号
                </Button>
              </Space>
              <p>
                <strong>用户：</strong>
                {detail.user_name || detail.user_id || "—"}
              </p>
              <p>
                <strong>Agent：</strong>
                {detail.agent_name || "—"}
              </p>
              <p>
                <strong>评论：</strong>
                {detail.comment || "—"}
              </p>
              <Typography.Title level={5}>对话上下文</Typography.Title>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {(detail.context_messages || []).map((m) => (
                  <div
                    key={m.id}
                    style={{
                      padding: 10,
                      borderRadius: 8,
                      border: m.is_target
                        ? "2px solid var(--primary, #1677ff)"
                        : "1px solid var(--border-color, #eee)",
                      background: m.is_target ? "rgba(22,119,255,0.06)" : undefined,
                    }}
                  >
                    <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>
                      {m.role}
                      {m.is_target ? " · 目标消息" : ""}
                    </div>
                    <div style={{ whiteSpace: "pre-wrap" }}>{m.content || ""}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Drawer>
      </div>
    </AdminLayout>
  );
}
