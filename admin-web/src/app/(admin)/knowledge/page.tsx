/**
 * 知识库列表：加载 / 删除 / 进入详情。
 * @author 赵振明
 * @date 2026-11-20 14:22:56
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  App,
  Button,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

const { Title, Paragraph } = Typography;

type KbItem = {
  id: string;
  name: string;
  description?: string | null;
  owner_department_id?: string | null;
  visibility: string;
  created_at?: string | null;
};

type Viewer = { is_platform_admin?: boolean };

export default function KnowledgeListPage() {
  useAdminPageTitle("知识库管理");
  const { message } = App.useApp();
  const [items, setItems] = useState<KbItem[]>([]);
  const [viewer, setViewer] = useState<Viewer>({});
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiJson<{ items: KbItem[]; viewer?: Viewer }>(
        "/api/v1/knowledge-bases",
      );
      if (res.code !== 0) {
        message.error(res.message || "加载知识库失败");
        return;
      }
      setItems(res.data?.items || []);
      setViewer(res.data?.viewer || {});
    } catch (err) {
      message.error(`加载失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onDelete(row: KbItem) {
    try {
      const res = await apiJson(`/api/v1/knowledge-bases/${encodeURIComponent(row.id)}`, {
        method: "DELETE",
      });
      if (res.code !== 0) {
        message.error(res.message || "删除失败");
        return;
      }
      message.success(`已删除「${row.name}」`);
      await load();
    } catch (err) {
      message.error(`删除失败：${(err as Error).message}`);
    }
  }

  const columns: ColumnsType<KbItem> = [
    {
      title: "名称",
      dataIndex: "name",
      render: (name: string, row) => (
        <Link href={`/knowledge/${encodeURIComponent(row.id)}`}>{name}</Link>
      ),
    },
    {
      title: "可见性",
      dataIndex: "visibility",
      width: 120,
      render: (v: string) =>
        v === "public" ? <Tag color="blue">公司公开</Tag> : <Tag>部门私有</Tag>,
    },
    {
      title: "归属部门",
      dataIndex: "owner_department_id",
      width: 160,
      render: (id?: string | null) => id || "—",
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 180,
      render: (t?: string | null) => (t ? t.replace("T", " ").slice(0, 19) : "—"),
    },
    {
      title: "操作",
      key: "actions",
      width: 200,
      render: (_, row) => (
        <Space>
          <Link href={`/knowledge/${encodeURIComponent(row.id)}`}>
            <Button type="link" size="small">
              详情
            </Button>
          </Link>
          <Link href={`/knowledge/${encodeURIComponent(row.id)}/permissions`}>
            <Button type="link" size="small">
              权限
            </Button>
          </Link>
          {viewer.is_platform_admin ? (
            <Popconfirm
              title={`确认删除知识库「${row.name}」？其下文档将一并软删。`}
              onConfirm={() => void onDelete(row)}
            >
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 20 }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            知识库管理
          </Title>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            建库、文档、切块与权限仅在管理端维护。
          </Paragraph>
        </div>
        <Space wrap>
          <Link href="/knowledge/categories">
            <Button>分类</Button>
          </Link>
          <Link href="/knowledge/audit">
            <Button>审计</Button>
          </Link>
          <Link href="/knowledge/cache">
            <Button>缓存</Button>
          </Link>
          {viewer.is_platform_admin ? (
            <Link href="/knowledge/new">
              <Button type="primary">新建知识库</Button>
            </Link>
          ) : null}
        </Space>
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{ pageSize: 20 }}
      />
    </div>
  );
}
