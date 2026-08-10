"use client";

import { useCallback, useEffect, useState } from "react";
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

type RoleOut = {
  code: string;
  name: string;
  description?: string | null;
  is_builtin: boolean;
  is_active: boolean;
  data_scope_default: string;
  user_count?: number | null;
};

const SCOPE_LABEL: Record<string, string> = {
  all: "全部数据",
  custom: "自定义部门",
  department: "本部门",
  self: "仅自己",
};

const SCOPE_OPTIONS = Object.entries(SCOPE_LABEL).map(([value, label]) => ({
  value,
  label,
}));

export default function RolesPage() {
  const { message, modal } = App.useApp();
  const [items, setItems] = useState<RoleOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<RoleOut | null>(null);
  const [menusOpen, setMenusOpen] = useState<RoleOut | null>(null);
  const [scopeOpen, setScopeOpen] = useState<RoleOut | null>(null);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [scopeForm] = Form.useForm();

  const loadRoles = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiJson<{ items: RoleOut[]; total: number }>(
        "/api/v1/roles",
      );
      if (res.code === 0 && res.data) setItems(res.data.items);
    } catch (err) {
      message.error(`加载失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    loadRoles();
  }, [loadRoles]);

  const onCreate = async () => {
    try {
      const values = await createForm.validateFields();
      const res = await apiJson<RoleOut>("/api/v1/roles", {
        method: "POST",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("创建成功");
        setCreateOpen(false);
        createForm.resetFields();
        loadRoles();
      } else {
        message.error(res.message || "创建失败");
      }
    } catch (err) {
      if ((err as Error).message) message.error((err as Error).message);
    }
  };

  const onEditName = async () => {
    if (!editing) return;
    try {
      const values = await editForm.validateFields();
      const res = await apiJson<RoleOut>(`/api/v1/roles/${editing.code}`, {
        method: "PUT",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("更新成功");
        setEditing(null);
        loadRoles();
      } else {
        message.error(res.message || "更新失败");
      }
    } catch (err) {
      if ((err as Error).message) message.error((err as Error).message);
    }
  };

  const onDelete = (role: RoleOut) => {
    modal.confirm({
      title: `确认删除角色 ${role.name}？`,
      content: "有用户持有时会被拒绝；不可恢复。",
      okText: "确认",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        const res = await apiJson<{ code: string }>(
          `/api/v1/roles/${role.code}`,
          { method: "DELETE" },
        );
        if (res.code === 0) {
          message.success("已删除");
          loadRoles();
        } else {
          message.error(res.message || "删除失败");
        }
      },
    });
  };

  const onSaveMenus = async (roleCode: string, items: { menu_code: string; can_view: boolean }[]) => {
    const res = await apiJson(`/api/v1/roles/${roleCode}/menus`, {
      method: "PUT",
      body: JSON.stringify({
        items: items.map((i) => ({ menu_code: i.menu_code, can_view: i.can_view, can_edit: false })),
      }),
    });
    if (res.code === 0) {
      message.success("菜单权限已更新");
      setMenusOpen(null);
    } else {
      message.error(res.message || "保存失败");
    }
  };

  const onSaveScope = async () => {
    if (!scopeOpen) return;
    try {
      const values = await scopeForm.validateFields();
      const res = await apiJson(`/api/v1/roles/${scopeOpen.code}/data-scopes`, {
        method: "PUT",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("数据范围已更新");
        setScopeOpen(null);
        loadRoles();
      } else {
        message.error(res.message || "保存失败");
      }
    } catch (err) {
      if ((err as Error).message) message.error((err as Error).message);
    }
  };

  const columns: ColumnsType<RoleOut> = [
    {
      title: "编码",
      dataIndex: "code",
      width: 180,
      render: (v: string, r) => (
        <Space size="small">
          <span style={{ fontFamily: "monospace" }}>{v}</span>
          {r.is_builtin && <Tag color="blue">内置</Tag>}
          {!r.is_active && <Tag color="default">停用</Tag>}
        </Space>
      ),
    },
    { title: "名称", dataIndex: "name", width: 160 },
    {
      title: "描述",
      dataIndex: "description",
      ellipsis: true,
    },
    {
      title: "数据范围",
      dataIndex: "data_scope_default",
      width: 140,
      render: (v: string) => SCOPE_LABEL[v] || v,
    },
    {
      title: "用户数",
      dataIndex: "user_count",
      width: 100,
      render: (v?: number | null) => v ?? 0,
    },
    {
      title: "操作",
      width: 280,
      render: (_: unknown, r: RoleOut) => (
        <Space size="small">
          <Button
            size="small"
            onClick={() => {
              setEditing(r);
              editForm.setFieldsValue({ name: r.name, description: r.description });
            }}
          >
            编辑
          </Button>
          <Button
            size="small"
            onClick={() => {
              setMenusOpen(r);
            }}
          >
            菜单权限
          </Button>
          <Button
            size="small"
            onClick={() => {
              setScopeOpen(r);
              scopeForm.setFieldsValue({
                scope_type: r.data_scope_default,
                scope_departments: [],
              });
            }}
          >
            数据范围
          </Button>
          {!r.is_builtin && (
            <Popconfirm
              title={`确认删除 ${r.name}？`}
              onConfirm={() => onDelete(r)}
              okText="确认"
              cancelText="取消"
            >
              <Button size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  useAdminPageTitle("角色权限");
  return (
    <>
      <Card
        title="角色列表"
        extra={
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            + 新建自定义角色
          </Button>
        }
      >
        <Table
          rowKey="code"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={false}
          size="middle"
        />
      </Card>

      <Modal
        title="新建自定义角色"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          createForm.resetFields();
        }}
        onOk={onCreate}
        okText="创建"
        cancelText="取消"
        width={560}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical">
          <Form.Item
            label="编码"
            name="code"
            rules={[
              { required: true, message: "必填" },
              {
                pattern: /^[a-z][a-z0-9_]*$/,
                message: "小写字母开头，可含字母数字下划线",
              },
            ]}
          >
            <Input placeholder="如 hr_specialist" />
          </Form.Item>
          <Form.Item
            label="名称"
            name="name"
            rules={[{ required: true, message: "必填" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            label="默认数据范围"
            name="data_scope_default"
            initialValue="self"
            rules={[{ required: true, message: "必填" }]}
          >
            <Select options={SCOPE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑角色：${editing?.name || ""}`}
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={onEditName}
        okText="保存"
        cancelText="取消"
        width={560}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical">
          <Form.Item label="名称" name="name">
            <Input />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={2} />
          </Form.Item>
          {editing?.is_builtin && (
            <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
              内置角色不可修改 data_scope_default
            </div>
          )}
        </Form>
      </Modal>

      <RoleMenusModal
        open={!!menusOpen}
        role={menusOpen}
        onCancel={() => setMenusOpen(null)}
        onSave={onSaveMenus}
      />

      <Modal
        title={`数据范围：${scopeOpen?.name || ""}`}
        open={!!scopeOpen}
        onCancel={() => setScopeOpen(null)}
        onOk={onSaveScope}
        okText="保存"
        cancelText="取消"
        width={520}
        destroyOnClose
      >
        <Form form={scopeForm} layout="vertical">
          <Form.Item
            label="数据范围"
            name="scope_type"
            rules={[{ required: true, message: "必填" }]}
          >
            <Select options={SCOPE_OPTIONS} />
          </Form.Item>
          <Form.Item
            label="自定义部门（仅 custom 生效）"
            name="scope_departments"
          >
            <Select mode="tags" placeholder="输入部门 ID" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function RoleMenusModal({
  open,
  role,
  onCancel,
  onSave,
}: {
  open: boolean;
  role: RoleOut | null;
  onCancel: () => void;
  onSave: (code: string, items: { menu_code: string; can_view: boolean }[]) => void;
}) {
  const [items, setItems] = useState<{ menu_code: string; can_view: boolean }[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !role) return;
    setLoading(true);
    apiJson<{ items: { menu_code: string; can_view: boolean; can_edit: boolean }[] }>(
      `/api/v1/roles/${role.code}/menus`,
    )
      .then((res) => {
        if (res.code === 0 && res.data) setItems(res.data.items);
      })
      .finally(() => setLoading(false));
  }, [open, role]);

  return (
    <Modal
      title={`菜单权限：${role?.name || ""}`}
      open={open}
      onCancel={onCancel}
      onOk={() => role && onSave(role.code, items)}
      okText="保存"
      cancelText="取消"
      width={640}
    >
      {loading ? (
        <div>加载中...</div>
      ) : (
        <div style={{ maxHeight: 360, overflow: "auto" }}>
          {items.map((it) => (
            <div
              key={it.menu_code}
              style={{
                display: "flex",
                alignItems: "center",
                padding: "6px 0",
                borderBottom: "1px solid var(--border-color, #eee)",
              }}
            >
              <span style={{ flex: 1, fontFamily: "monospace" }}>{it.menu_code}</span>
              <Tabs
                size="small"
                activeKey={it.can_view ? "view" : "hide"}
                onChange={(k) =>
                  setItems((prev) =>
                    prev.map((p) =>
                      p.menu_code === it.menu_code
                        ? { ...p, can_view: k === "view" }
                        : p,
                    ),
                  )
                }
                items={[
                  { key: "view", label: "可见" },
                  { key: "hide", label: "隐藏" },
                ]}
              />
            </div>
          ))}
          {items.length === 0 && (
            <div style={{ color: "var(--text-secondary)" }}>暂无菜单权限（全部隐藏）</div>
          )}
        </div>
      )}
    </Modal>
  );
}