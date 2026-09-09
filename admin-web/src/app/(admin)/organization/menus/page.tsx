/**
 * 菜单定义维护：树表展示，超管可写，平台管理员只读。
 *
 * @author 赵振明
 * @date 2026-08-11 14:16:34
 */
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined } from "@ant-design/icons";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type MenuRow = {
  code: string;
  name: string;
  icon?: string | null;
  path?: string | null;
  parent_code?: string | null;
  sort: number;
  app: string;
  is_visible: boolean;
  is_builtin: boolean;
  children?: MenuRow[];
};

type MenuFlat = Omit<MenuRow, "children">;

/** 扁平列表转树（按 parent_code）。 */
function buildTree(items: MenuFlat[]): MenuRow[] {
  const byCode: Record<string, MenuRow> = {};
  for (const it of items) {
    byCode[it.code] = { ...it, children: [] };
  }
  const roots: MenuRow[] = [];
  for (const it of items) {
    const node = byCode[it.code];
    const parent = it.parent_code;
    if (parent && byCode[parent]) {
      byCode[parent].children!.push(node);
    } else {
      roots.push(node);
    }
  }
  const prune = (nodes: MenuRow[]) => {
    for (const n of nodes) {
      if (n.children?.length) prune(n.children);
      else delete n.children;
    }
  };
  prune(roots);
  return roots;
}

export default function OrganizationMenusPage() {
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const [flat, setFlat] = useState<MenuFlat[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MenuFlat | null>(null);
  const [form] = Form.useForm();

  useAdminPageTitle("菜单管理");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiJson<{ items: MenuFlat[] }>(
        "/api/v1/menus?manage=1&app=admin",
      );
      if (res.code === 0) setFlat(res.data?.items ?? []);
      else message.error(res.message || "加载失败");
    } catch (e) {
      console.error(e);
      message.error("网络错误");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const treeData = useMemo(() => buildTree(flat), [flat]);

  const parentOptions = useMemo(
    () => [
      { value: "", label: "（顶级）" },
      ...flat.map((m) => ({
        value: m.code,
        label: `${m.name} (${m.code})`,
      })),
    ],
    [flat],
  );

  function openCreate() {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      app: "admin",
      sort: 100,
      is_visible: true,
      parent_code: "group.org",
    });
    setModalOpen(true);
  }

  function openEdit(row: MenuFlat) {
    setEditing(row);
    form.setFieldsValue({
      code: row.code,
      name: row.name,
      icon: row.icon,
      path: row.path,
      parent_code: row.parent_code || "",
      sort: row.sort,
      app: row.app,
      is_visible: row.is_visible,
    });
    setModalOpen(true);
  }

  async function onSubmit() {
    if (!isSuper) return;
    try {
      const values = await form.validateFields();
      const parent =
        values.parent_code === "" || values.parent_code == null
          ? null
          : values.parent_code;
      if (editing) {
        const res = await apiJson(`/api/v1/menus/${editing.code}`, {
          method: "PUT",
          body: JSON.stringify({
            name: values.name,
            icon: values.icon || null,
            path: values.path || null,
            parent_code: parent,
            sort: values.sort,
            app: values.app,
            is_visible: values.is_visible,
          }),
        });
        if (res.code === 0) {
          message.success("已更新");
          setModalOpen(false);
          await load();
        } else message.error(res.message || "更新失败");
      } else {
        const res = await apiJson("/api/v1/menus", {
          method: "POST",
          body: JSON.stringify({
            code: values.code,
            name: values.name,
            icon: values.icon || null,
            path: values.path || null,
            parent_code: parent,
            sort: values.sort,
            app: values.app,
          }),
        });
        if (res.code === 0) {
          message.success("已创建");
          setModalOpen(false);
          await load();
        } else message.error(res.message || "创建失败");
      }
    } catch {
      /* validate */
    }
  }

  function onDelete(row: MenuFlat) {
    if (!isSuper || row.is_builtin) return;
    Modal.confirm({
      title: `确认删除菜单「${row.name}」？`,
      content: row.code,
      okText: "删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        const res = await apiJson(`/api/v1/menus/${row.code}`, {
          method: "DELETE",
        });
        if (res.code === 0) {
          message.success("已删除");
          await load();
        } else message.error(res.message || "删除失败");
      },
    });
  }

  const columns: ColumnsType<MenuRow> = [
    {
      title: "名称",
      dataIndex: "name",
      render: (name: string, row) => (
        <Space size={8}>
          <span style={{ fontWeight: 500 }}>{name}</span>
          <span style={{ fontFamily: "monospace", fontSize: 12, opacity: 0.65 }}>
            {row.code}
          </span>
          {row.is_builtin && <Tag>内置</Tag>}
          {!row.is_visible && <Tag color="default">隐藏</Tag>}
        </Space>
      ),
    },
    {
      title: "路径",
      dataIndex: "path",
      width: 220,
      render: (v: string | null | undefined) =>
        v ? (
          <span style={{ fontFamily: "monospace", fontSize: 12 }}>{v}</span>
        ) : (
          <span style={{ color: "var(--text-secondary)" }}>分组</span>
        ),
    },
    {
      title: "排序",
      dataIndex: "sort",
      width: 72,
    },
    {
      title: "应用",
      dataIndex: "app",
      width: 80,
    },
    {
      title: "操作",
      width: 160,
      render: (_, row) =>
        isSuper ? (
          <Space>
            <Button type="link" size="small" onClick={() => openEdit(row)}>
              编辑
            </Button>
            {!row.is_builtin && (
              <Button type="link" size="small" danger onClick={() => onDelete(row)}>
                删除
              </Button>
            )}
          </Space>
        ) : (
          <span style={{ color: "var(--text-secondary)" }}>只读</span>
        ),
    },
  ];

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="菜单 path 必须有对应管理端页面或占位，否则壳内 404（D48）。"
        description={
          isSuper
            ? "当前为超级管理员：可增删改自定义菜单，可改内置项的名称/路径/排序/显隐。"
            : "当前为平台管理员：仅可浏览菜单定义，不可修改。"
        }
      />

      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginBottom: 12,
        }}
      >
        {isSuper && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增菜单
          </Button>
        )}
      </div>

      <Table
        loading={loading}
        rowKey="code"
        columns={columns}
        dataSource={treeData}
        pagination={false}
        expandable={{ defaultExpandAllRows: true }}
        size="middle"
      />

      <Modal
        title={editing ? `编辑菜单：${editing.name}` : "新增自定义菜单"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void onSubmit()}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={560}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="code"
            label="编码 code"
            rules={[
              { required: true, message: "必填" },
              {
                pattern: /^[a-z][a-z0-9._-]{1,62}$/,
                message: "小写字母开头，允许字母数字._-",
              },
            ]}
          >
            <Input disabled={!!editing} placeholder="如 custom.reports" />
          </Form.Item>
          <Form.Item name="name" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="中文名，侧栏显示" />
          </Form.Item>
          <Form.Item name="parent_code" label="父级">
            <Select
              options={parentOptions.filter(
                (o) => !editing || o.value !== editing.code,
              )}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item name="path" label="路由 path">
            <Input placeholder="叶子菜单必填，如 /organization/menus；分组可空" />
          </Form.Item>
          <Form.Item name="icon" label="图标名">
            <Input placeholder="Ant Design Icons 名，如 MenuOutlined" />
          </Form.Item>
          <Form.Item name="sort" label="排序" rules={[{ required: true }]}>
            <InputNumber min={0} max={9999} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="app" label="应用" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "admin", label: "管理端" },
                { value: "web", label: "员工端" },
                { value: "both", label: "两端" },
              ]}
            />
          </Form.Item>
          {editing && (
            <Form.Item
              name="is_visible"
              label="全局可见"
              valuePropName="checked"
            >
              <Switch checkedChildren="可见" unCheckedChildren="隐藏" />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  );
}
