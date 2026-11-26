/**
 * 知识库权限全量替换。
 * @author 赵振明
 * @date 2026-11-20 14:22:56
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  App,
  Button,
  Select,
  Space,
  Table,
  Typography,
  Input,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

const { Title, Paragraph, Text } = Typography;

type PermItem = {
  key: string;
  subject_type: string;
  subject_id: string;
};

export default function KnowledgePermissionsPage() {
  useAdminPageTitle("知识库权限");
  const { message } = App.useApp();
  const params = useParams();
  const kbId = String(params?.kb_id || "");
  const [items, setItems] = useState<PermItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!kbId) return;
    setLoading(true);
    try {
      const res = await apiJson<{ items: { subject_type: string; subject_id: string }[] }>(
        `/api/v1/knowledge-bases/${encodeURIComponent(kbId)}/permissions`,
      );
      if (res.code !== 0) {
        message.error(res.message || "加载权限失败");
        return;
      }
      setItems(
        (res.data?.items || []).map((p, i) => ({
          key: `${p.subject_type}-${p.subject_id}-${i}`,
          subject_type: p.subject_type,
          subject_id: p.subject_id,
        })),
      );
    } catch (err) {
      message.error(`加载失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [kbId, message]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onSave() {
    const payload = items
      .map((p) => ({
        subject_type: p.subject_type,
        subject_id: p.subject_id.trim(),
      }))
      .filter((p) => p.subject_id);
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/knowledge-bases/${encodeURIComponent(kbId)}/permissions`,
        {
          method: "PUT",
          body: JSON.stringify({ items: payload }),
        },
      );
      if (res.code !== 0) {
        message.error(res.message || "保存失败");
        return;
      }
      message.success("已保存权限");
      await load();
    } catch (err) {
      message.error(`保存失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const columns: ColumnsType<PermItem> = [
    {
      title: "主体类型",
      dataIndex: "subject_type",
      width: 160,
      render: (v, row, idx) => (
        <Select
          value={v}
          style={{ width: "100%" }}
          options={[
            { value: "user", label: "用户" },
            { value: "department", label: "部门" },
            { value: "role", label: "角色" },
          ]}
          onChange={(nv) => {
            setItems((prev) =>
              prev.map((p, i) => (i === idx ? { ...p, subject_type: nv } : p)),
            );
          }}
        />
      ),
    },
    {
      title: "主体 ID",
      dataIndex: "subject_id",
      render: (v, _row, idx) => (
        <Input
          value={v}
          placeholder="user_id / dept_id / role_code"
          onChange={(e) => {
            const nv = e.target.value;
            setItems((prev) =>
              prev.map((p, i) => (i === idx ? { ...p, subject_id: nv } : p)),
            );
          }}
        />
      ),
    },
    {
      title: "操作",
      width: 80,
      render: (_v, _row, idx) => (
        <Button
          type="link"
          danger
          onClick={() => setItems((prev) => prev.filter((_, i) => i !== idx))}
        >
          删除
        </Button>
      ),
    },
  ];

  return (
    <div style={{ padding: 20 }}>
      <Title level={3}>知识库权限</Title>
      <Paragraph type="secondary">
        KB：<Text code>{kbId}</Text> · 保存为全量替换；仅超管可写。
      </Paragraph>
      <Space style={{ marginBottom: 12 }}>
        <Button
          onClick={() =>
            setItems((prev) => [
              ...prev,
              {
                key: `new-${Date.now()}`,
                subject_type: "role",
                subject_id: "employee",
              },
            ])
          }
        >
          添加一行
        </Button>
        <Button type="primary" loading={busy} onClick={() => void onSave()}>
          保存
        </Button>
        <Link href={`/knowledge/${encodeURIComponent(kbId)}`}>
          <Button>返回详情</Button>
        </Link>
      </Space>
      <Table
        rowKey="key"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={false}
      />
    </div>
  );
}
