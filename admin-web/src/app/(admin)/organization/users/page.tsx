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
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

type UserStatus = "active" | "disabled" | "terminated";
type UserOut = {
  id: string;
  username: string;
  name: string;
  employee_no: string;
  email: string;
  phone: string;
  position: string;
  hire_date: string;
  main_department_id: string;
  role: string;
  status: UserStatus;
  created_at?: string | null;
  updated_at?: string | null;
  last_login_at?: string | null;
};

type DepartmentLite = { id: string; name: string };

const STATUS_COLOR: Record<UserStatus, string> = {
  active: "green",
  disabled: "orange",
  terminated: "default",
};

const STATUS_LABEL: Record<UserStatus, string> = {
  active: "活跃",
  disabled: "已停用",
  terminated: "已离职",
};

const ROLE_LABEL: Record<string, string> = {
  employee: "员工",
  expert: "业务专家",
  agent_dev: "Agent 开发者",
  department_admin: "部门管理员",
  platform_admin: "平台管理员",
  super_admin: "超级管理员",
};

export default function UsersPage() {
  const { message, modal } = App.useApp();
  const [items, setItems] = useState<UserOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<UserStatus[]>([
    "active",
    "disabled",
  ]);
  const [roleFilter, setRoleFilter] = useState<string | undefined>();
  const [departments, setDepartments] = useState<DepartmentLite[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<UserOut | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      statusFilter.forEach((s) => params.append("status", s));
      if (roleFilter) params.set("role", roleFilter);
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      const res = await apiJson<{ items: UserOut[]; total: number }>(
        `/api/v1/users?${params.toString()}`,
      );
      if (res.code === 0 && res.data) {
        setItems(res.data.items);
        setTotal(res.data.total);
      }
    } catch (err) {
      message.error(`加载失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter, roleFilter, page, pageSize, message]);

  const loadDepartments = useCallback(async () => {
    const res = await apiJson<{ items: DepartmentLite[] }>(
      "/api/v1/departments",
    );
    if (res.code === 0 && res.data) setDepartments(res.data.items);
  }, []);

  useEffect(() => {
    loadUsers();
    loadDepartments();
  }, [loadUsers, loadDepartments]);

  const onCreate = async () => {
    try {
      const values = await createForm.validateFields();
      const res = await apiJson<UserOut>("/api/v1/users", {
        method: "POST",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("创建成功");
        setCreateOpen(false);
        createForm.resetFields();
        loadUsers();
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
      const res = await apiJson<UserOut>(`/api/v1/users/${editing.id}`, {
        method: "PUT",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("更新成功");
        setEditing(null);
        loadUsers();
      } else {
        message.error(res.message || "更新失败");
      }
    } catch (err) {
      if ((err as Error).message) message.error((err as Error).message);
    }
  };

  const onToggleStatus = async (
    userId: string,
    current: UserStatus,
  ) => {
    const next: UserStatus = current === "disabled" ? "active" : "disabled";
    const action = next === "active" ? "启用" : "停用";
    modal.confirm({
      title: `确认${action}用户？`,
      content: `用户将被${next === "active" ? "启用" : "停用"}，${next === "active" ? "可" : "不可"}登录。`,
      okText: action,
      cancelText: "取消",
      okButtonProps: { danger: next === "disabled" },
      onOk: async () => {
        const res = await apiJson<{ id: string; status: UserStatus }>(
          `/api/v1/users/${userId}/status`,
          {
            method: "PATCH",
            body: JSON.stringify({ status: next }),
          },
        );
        if (res.code === 0) {
          message.success(`${action}成功`);
          loadUsers();
        } else {
          message.error(res.message || `${action}失败`);
        }
      },
    });
  };

  const onTerminate = (userId: string) => {
    modal.confirm({
      title: "确认标记离职？",
      content: "离职后账号无法恢复，但历史数据保留。",
      okText: "确认",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        const res = await apiJson<{ id: string }>(
          `/api/v1/users/${userId}`,
          { method: "DELETE" },
        );
        if (res.code === 0) {
          message.success("已标记离职");
          loadUsers();
        } else {
          message.error(res.message || "操作失败");
        }
      },
    });
  };

  const columns: ColumnsType<UserOut> = [
    {
      title: "用户名",
      dataIndex: "username",
      width: 140,
      render: (v: string) => <span style={{ fontFamily: "monospace" }}>{v}</span>,
    },
    { title: "显示名", dataIndex: "name", width: 120 },
    { title: "工号", dataIndex: "employee_no", width: 120 },
    {
      title: "主部门",
      dataIndex: "main_department_id",
      width: 140,
      render: (v: string) =>
        departments.find((d) => d.id === v)?.name || v,
    },
    {
      title: "角色",
      dataIndex: "role",
      width: 120,
      render: (v: string) => (
        <Tag color="blue">{ROLE_LABEL[v] || v}</Tag>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (v: UserStatus) => (
        <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v]}</Tag>
      ),
    },
    {
      title: "操作",
      width: 220,
      render: (_: unknown, record: UserOut) => (
        <Space size="small">
          <Button
            size="small"
            onClick={() => {
              setEditing(record);
              editForm.setFieldsValue(record);
            }}
          >
            编辑
          </Button>
          {record.status !== "terminated" && (
            <Button
              size="small"
              onClick={() => onToggleStatus(record.id, record.status)}
            >
              {record.status === "disabled" ? "启用" : "停用"}
            </Button>
          )}
          {record.status !== "terminated" && (
            <Popconfirm
              title="确认标记离职？"
              onConfirm={() => onTerminate(record.id)}
              okText="确认"
              cancelText="取消"
            >
              <Button size="small" danger>
                离职
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  useAdminPageTitle("用户管理");
  return (
    <>
      <Card
        title="用户列表"
        extra={
          <Space>
            <Button type="primary" onClick={() => setCreateOpen(true)}>
              + 新建用户
            </Button>
          </Space>
        }
      >
        <Space style={{ marginBottom: 16 }} wrap>
          <Input.Search
            placeholder="搜索用户名/工号/姓名"
            allowClear
            onSearch={(v) => {
              setSearch(v);
              setPage(1);
            }}
            style={{ width: 280 }}
          />
          <Select
            mode="multiple"
            placeholder="状态"
            value={statusFilter}
            onChange={(v: UserStatus[]) => {
              setStatusFilter(v);
              setPage(1);
            }}
            style={{ width: 180 }}
            options={[
              { value: "active", label: "活跃" },
              { value: "disabled", label: "已停用" },
              { value: "terminated", label: "已离职" },
            ]}
          />
          <Select
            placeholder="角色"
            allowClear
            value={roleFilter}
            onChange={(v: string | undefined) => {
              setRoleFilter(v);
              setPage(1);
            }}
            style={{ width: 180 }}
            options={Object.entries(ROLE_LABEL).map(([value, label]) => ({
              value,
              label,
            }))}
          />
        </Space>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      </Card>

      <Modal
        title="新建用户"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          createForm.resetFields();
        }}
        onOk={onCreate}
        okText="创建"
        cancelText="取消"
        width={640}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical">
          <Form.Item
            label="用户名"
            name="username"
            rules={[
              { required: true, message: "必填" },
              {
                pattern: /^[a-zA-Z0-9_]+$/,
                message: "仅字母数字下划线",
              },
            ]}
          >
            <Input placeholder="登录凭证" />
          </Form.Item>
          <Form.Item
            label="初始密码"
            name="password"
            rules={[
              { required: true, message: "必填" },
              { min: 6, message: "至少 6 位" },
            ]}
          >
            <Input.Password placeholder="≥6 位" />
          </Form.Item>
          <Form.Item
            label="显示名"
            name="name"
            rules={[{ required: true, message: "必填" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label="工号"
            name="employee_no"
            rules={[{ required: true, message: "必填" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label="主部门"
            name="main_department_id"
            rules={[{ required: true, message: "必填" }]}
          >
            <Select
              options={departments.map((d) => ({
                value: d.id,
                label: d.name,
              }))}
            />
          </Form.Item>
          <Form.Item label="主角色" name="role" initialValue="employee">
            <Select
              options={Object.entries(ROLE_LABEL).map(([value, label]) => ({
                value,
                label,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑用户：${editing?.username || ""}`}
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={onEdit}
        okText="保存"
        cancelText="取消"
        width={640}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical">
          <Form.Item label="显示名" name="name">
            <Input />
          </Form.Item>
          <Form.Item label="邮箱" name="email">
            <Input />
          </Form.Item>
          <Form.Item label="手机号" name="phone">
            <Input />
          </Form.Item>
          <Form.Item label="职位" name="position">
            <Input />
          </Form.Item>
          <Form.Item label="主部门" name="main_department_id">
            <Select
              options={departments.map((d) => ({
                value: d.id,
                label: d.name,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}