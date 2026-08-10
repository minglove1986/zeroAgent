"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tree,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

type Department = {
  id: string;
  name: string;
  code?: string | null;
  parent_id?: string | null;
  sort: number;
  leader_user_id?: string | null;
  is_active: boolean;
  deleted_at?: string | null;
};

type TreeNode = {
  key: string;
  title: React.ReactNode;
  children?: TreeNode[];
  raw: Department;
};

function buildTree(items: Department[]): TreeNode[] {
  const map = new Map<string, TreeNode>();
  items.forEach((d) => {
    map.set(d.id, {
      key: d.id,
      title: (
        <Space size="small">
          <span>{d.name}</span>
          {d.code && <span style={{ color: "#999", fontSize: 12 }}>({d.code})</span>}
          {!d.is_active && <Tag color="default">停用</Tag>}
        </Space>
      ),
      raw: d,
    });
  });
  // ... rest unchanged
  const roots: TreeNode[] = [];
  map.forEach((n) => {
    const p = n.raw.parent_id;
    if (p && map.has(p)) {
      const parent = map.get(p)!;
      parent.children = parent.children || [];
      parent.children.push(n);
    } else {
      roots.push(n);
    }
  });
  return roots;
}

export default function DepartmentsPage() {
  const { message, modal } = App.useApp();
  const [items, setItems] = useState<Department[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Department | null>(null);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();

  const loadDepts = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiJson<{ items: Department[] }>(
        "/api/v1/departments?include_deleted=false",
      );
      if (res.code === 0 && res.data) setItems(res.data.items);
    } catch (err) {
      message.error(`加载失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    loadDepts();
  }, [loadDepts]);

  const treeData = useMemo(() => buildTree(items), [items]);

  const onCreate = async () => {
    try {
      const values = await createForm.validateFields();
      const res = await apiJson<Department>("/api/v1/departments", {
        method: "POST",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("创建成功");
        setCreateOpen(false);
        createForm.resetFields();
        loadDepts();
      } else {
        message.error(res.message || "创建失败");
      }
    } catch (err) {
      if ((err as Error).message) message.error((err as Error).message);
    }
  };

  const onEdit = async () => {
    if (!editing) return;
    try {
      const values = await editForm.validateFields();
      const res = await apiJson<Department>(`/api/v1/departments/${editing.id}`, {
        method: "PUT",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("更新成功");
        setEditing(null);
        loadDepts();
      } else {
        message.error(res.message || "更新失败");
      }
    } catch (err) {
      if ((err as Error).message) message.error((err as Error).message);
    }
  };

  const onDelete = (dept: Department) => {
    modal.confirm({
      title: `确认软删部门 ${dept.name}？`,
      content: "历史数据保留。有用户归属时会被拒绝。",
      okText: "确认",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        const res = await apiJson(`/api/v1/departments/${dept.id}`, {
          method: "DELETE",
        });
        if (res.code === 0) {
          message.success("已软删");
          loadDepts();
        } else {
          message.error(res.message || "软删失败");
        }
      },
    });
  };

  const onToggleActive = async (dept: Department) => {
    const action = dept.is_active ? "disable" : "enable";
    const label = dept.is_active ? "停用" : "启用";
    const res = await apiJson(
      `/api/v1/departments/${dept.id}/${action}`,
      { method: "POST" },
    );
    if (res.code === 0) {
      message.success(`${label}成功`);
      loadDepts();
    } else {
      message.error(res.message || `${label}失败`);
    }
  };

  const columns: ColumnsType<Department> = [
    { title: "ID", dataIndex: "id", width: 160 },
    { title: "名称", dataIndex: "name", width: 200 },
    {
      title: "编码",
      dataIndex: "code",
      width: 140,
      render: (v?: string | null) => v || "-",
    },
    {
      title: "父部门",
      dataIndex: "parent_id",
      width: 160,
      render: (v?: string | null) =>
        items.find((d) => d.id === v)?.name || v || "-",
    },
    {
      title: "负责人",
      dataIndex: "leader_user_id",
      width: 160,
      render: (v?: string | null) => v || "-",
    },
    {
      title: "状态",
      dataIndex: "is_active",
      width: 100,
      render: (v: boolean) => (
        <Tag color={v ? "green" : "default"}>{v ? "启用" : "停用"}</Tag>
      ),
    },
    {
      title: "操作",
      width: 240,
      render: (_: unknown, r: Department) => (
        <Space size="small">
          <Button
            size="small"
            onClick={() => {
              setEditing(r);
              editForm.setFieldsValue({
                name: r.name,
                code: r.code,
                parent_id: r.parent_id,
                sort: r.sort,
                leader_user_id: r.leader_user_id,
                is_active: r.is_active,
              });
            }}
          >
            编辑
          </Button>
          <Button size="small" onClick={() => onToggleActive(r)}>
            {r.is_active ? "停用" : "启用"}
          </Button>
          <Popconfirm
            title={`确认软删 ${r.name}？`}
            onConfirm={() => onDelete(r)}
            okText="确认"
            cancelText="取消"
          >
            <Button size="small" danger>
              软删
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  useAdminPageTitle("部门管理");
  return (
    <>
      <Space style={{ width: "100%" }} align="start" size={16}>
        <Card title="部门树" style={{ width: 360 }}>
          {treeData.length === 0 ? (
            <div style={{ color: "var(--text-secondary)" }}>暂无部门</div>
          ) : (
            <Tree
              treeData={treeData}
              defaultExpandAll
              selectable
              onSelect={(keys) => {
                const key = keys[0];
                if (typeof key === "string") {
                  const d = items.find((x) => x.id === key);
                  if (d) {
                    setEditing(d);
                    editForm.setFieldsValue({
                      name: d.name,
                      code: d.code,
                      parent_id: d.parent_id,
                      sort: d.sort,
                      leader_user_id: d.leader_user_id,
                      is_active: d.is_active,
                    });
                  }
                }
              }}
            />
          )}
        </Card>
        <Card style={{ flex: 1 }} title="部门列表">
          <div style={{ marginBottom: 16 }}>
            <Button type="primary" onClick={() => setCreateOpen(true)}>
              + 新建部门
            </Button>
          </div>
          <Table
            rowKey="id"
            loading={loading}
            columns={columns}
            dataSource={items}
            pagination={false}
            size="middle"
          />
        </Card>
      </Space>

      <Modal
        title="新建部门"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          createForm.resetFields();
        }}
        onOk={onCreate}
        okText="创建"
        cancelText="取消"
        width={520}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical">
          <Form.Item
            label="ID"
            name="id"
            rules={[{ required: true, max: 32, message: "必填，最长 32 位" }]}
          >
            <Input placeholder="如 dept_finance" />
          </Form.Item>
          <Form.Item
            label="名称"
            name="name"
            rules={[{ required: true, message: "必填" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item label="编码" name="code">
            <Input />
          </Form.Item>
          <Form.Item label="父部门" name="parent_id">
            <Select
              allowClear
              options={items.map((d) => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          <Form.Item label="排序" name="sort" initialValue={0}>
            <InputNumber min={0} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑部门：${editing?.name || ""}`}
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={onEdit}
        okText="保存"
        cancelText="取消"
        width={520}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical">
          <Form.Item label="名称" name="name">
            <Input />
          </Form.Item>
          <Form.Item label="编码" name="code">
            <Input />
          </Form.Item>
          <Form.Item label="父部门" name="parent_id">
            <Select
              allowClear
              options={items
                .filter((d) => d.id !== editing?.id)
                .map((d) => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          <Form.Item label="负责人" name="leader_user_id">
            <Input placeholder="用户 ID" />
          </Form.Item>
          <Form.Item label="排序" name="sort">
            <InputNumber min={0} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}