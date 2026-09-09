/**
 * 技能管理（最小可用）：列表 / 启停 / 删除（系统种子不可删）。
 *
 * @author 赵振明
 * @date 2026-08-20 17:29:20
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Modal, Space, Table, Tag, message } from "antd";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

type SkillItem = {
  id: string;
  name: string;
  description: string | null;
  status: string;
  current_version: string | null;
  origin: string;
  seed_code: string | null;
  tool_ids: string[];
  deletable: boolean;
};

/** 状态徽标颜色。 */
function statusColor(status: string): string {
  if (status === "published") return "green";
  if (status === "disabled") return "default";
  return "orange";
}

/** 来源徽标。 */
function originLabel(origin: string): { text: string; color: string } {
  if (origin === "system") return { text: "系统种子", color: "purple" };
  return { text: "自定义", color: "blue" };
}

export default function SkillsPage() {
  useAdminPageTitle("技能管理");
  const [items, setItems] = useState<SkillItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiJson<{ items: SkillItem[] }>("/api/v1/skills");
      if (res.code !== 0) {
        message.error(res.message || "加载失败");
        return;
      }
      setItems(res.data?.items || []);
    } catch {
      message.error("网络错误");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** 启停：published ↔ disabled。 */
  async function setStatus(row: SkillItem, next: "published" | "disabled") {
    setBusyId(row.id);
    try {
      const res = await apiJson(`/api/v1/skills/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      if (res.code !== 0) {
        message.error(res.message || "更新失败");
        return;
      }
      message.success(next === "published" ? "已启用" : "已停用");
      await load();
    } catch {
      message.error("网络错误");
    } finally {
      setBusyId(null);
    }
  }

  /** 删除自定义技能；系统种子前端直接拦截。 */
  function onDelete(row: SkillItem) {
    if (!row.deletable || row.origin === "system") {
      message.warning("系统种子技能不可删除，仅可停用");
      return;
    }
    Modal.confirm({
      title: `删除技能「${row.name}」？`,
      content: "将解除 Agent 绑定与工具关联，不可恢复。",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        setBusyId(row.id);
        try {
          const res = await apiJson(`/api/v1/skills/${row.id}`, {
            method: "DELETE",
          });
          if (res.code !== 0) {
            message.error(res.message || "删除失败");
            return;
          }
          message.success("已删除");
          await load();
        } catch {
          message.error("网络错误");
        } finally {
          setBusyId(null);
        }
      },
    });
  }

  const columns = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      render: (name: string, row: SkillItem) => (
        <Space direction="vertical" size={0}>
          <span>{name}</span>
          <span style={{ color: "var(--text-secondary)", fontSize: 12 }}>{row.id}</span>
        </Space>
      ),
    },
    {
      title: "来源",
      dataIndex: "origin",
      key: "origin",
      width: 110,
      render: (origin: string) => {
        const o = originLabel(origin || "custom");
        return <Tag color={o.color}>{o.text}</Tag>;
      },
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (status: string) => <Tag color={statusColor(status)}>{status}</Tag>,
    },
    {
      title: "版本",
      dataIndex: "current_version",
      key: "current_version",
      width: 90,
      render: (v: string | null) => v || "-",
    },
    {
      title: "工具",
      dataIndex: "tool_ids",
      key: "tool_ids",
      render: (ids: string[]) =>
        ids?.length ? ids.map((id) => <Tag key={id}>{id}</Tag>) : "-",
    },
    {
      title: "描述",
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (d: string | null) => d || "-",
    },
    {
      title: "操作",
      key: "actions",
      width: 200,
      render: (_: unknown, row: SkillItem) => {
        const published = row.status === "published";
        return (
          <Space>
            {published ? (
              <Button
                size="small"
                loading={busyId === row.id}
                onClick={() => void setStatus(row, "disabled")}
              >
                停用
              </Button>
            ) : (
              <Button
                size="small"
                type="primary"
                loading={busyId === row.id}
                onClick={() => void setStatus(row, "published")}
              >
                启用
              </Button>
            )}
            <Button
              size="small"
              danger
              disabled={!row.deletable || row.origin === "system"}
              title={
                !row.deletable || row.origin === "system"
                  ? "系统种子不可删除，仅可停用"
                  : undefined
              }
              loading={busyId === row.id}
              onClick={() => onDelete(row)}
            >
              删除
            </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <div style={{ padding: 20 }}>
      <Space style={{ marginBottom: 16 }} wrap>
        <span style={{ color: "var(--text-secondary)" }}>
          列表只读展示；可启停。系统种子不可删除，仅可停用。
        </span>
        <Button onClick={() => void load()} loading={loading}>
          刷新
        </Button>
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
