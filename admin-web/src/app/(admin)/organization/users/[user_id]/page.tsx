"use client";

/**
 * 用户详情页：顶栏 + 基本信息 / 部门与角色 / 会话历史 / 操作日志。
 *
 * @author 赵振明
 * @date 2026-08-11 15:41:23
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  App,
  Avatar,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

type UserStatus = "active" | "disabled" | "terminated";

type DeptItem = { id: string; name: string; is_primary: boolean };
type RoleItem = { code: string; name: string; is_primary: boolean };

type UserDetail = {
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
  id_card?: string | null;
  created_at?: string | null;
  last_login_at?: string | null;
  last_login_ip?: string | null;
  created_by?: string | null;
  departments?: DeptItem[];
  roles?: RoleItem[];
};

type SessionRow = {
  id: string;
  client_ip?: string | null;
  user_agent?: string | null;
  created_at?: string | null;
  last_seen_at?: string | null;
  is_active?: boolean;
};

type AuditRow = {
  id: string;
  created_at?: string | null;
  actor_id?: string | null;
  actor_role?: string | null;
  action: string;
  summary?: string | null;
  result?: string | null;
  client_ip?: string | null;
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

const PHONE_RULE = {
  pattern: /^1[3-9]\d{9}$/,
  message: "须为 11 位大陆手机号",
};

/** 选填身份证：空通过，有值才校验格式。 */
const ID_CARD_RULE = {
  validator: async (_: unknown, value: string | undefined) => {
    if (!value || !String(value).trim()) return;
    if (!/^[0-9]{17}[0-9Xx]$/.test(String(value).trim())) {
      throw new Error("须为 18 位身份证号（末位数字或 X）");
    }
  },
};

export default function UserDetailPage() {
  const params = useParams();
  const userId = String(params.user_id || "");
  const { message, modal } = App.useApp();
  const [user, setUser] = useState<UserDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [audits, setAudits] = useState<AuditRow[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditPageSize, setAuditPageSize] = useState(20);
  const [editOpen, setEditOpen] = useState(false);
  const [departments, setDepartments] = useState<DepartmentLite[]>([]);
  const [editForm] = Form.useForm();

  useAdminPageTitle(user ? `用户 · ${user.name}` : "用户详情");

  const loadDetail = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const res = await apiJson<UserDetail>(`/api/v1/users/${userId}`);
      if (res.code === 0 && res.data) {
        setUser(res.data);
        setNotFound(false);
      } else if (res.code === 40401 || res.message?.includes("not found")) {
        setNotFound(true);
        setUser(null);
      } else {
        message.error(res.message || "加载用户失败");
        setNotFound(true);
      }
    } catch (err) {
      message.error(`加载失败：${(err as Error).message}`);
      setNotFound(true);
    } finally {
      setLoading(false);
    }
  }, [userId, message]);

  const loadSessions = useCallback(async () => {
    if (!userId) return;
    const res = await apiJson<{ items: SessionRow[] }>(
      `/api/v1/users/${userId}/sessions?limit=10`,
    );
    if (res.code === 0 && res.data) {
      setSessions(res.data.items || []);
    }
  }, [userId]);

  const loadAudits = useCallback(async () => {
    if (!userId) return;
    const res = await apiJson<{ items: AuditRow[]; total: number }>(
      `/api/v1/users/${userId}/audit-logs?page=${auditPage}&page_size=${auditPageSize}`,
    );
    if (res.code === 0 && res.data) {
      setAudits(res.data.items || []);
      setAuditTotal(res.data.total || 0);
    }
  }, [userId, auditPage, auditPageSize]);

  useEffect(() => {
    void loadDetail();
    void loadSessions();
  }, [loadDetail, loadSessions]);

  useEffect(() => {
    void loadAudits();
  }, [loadAudits]);

  useEffect(() => {
    void (async () => {
      const res = await apiJson<{ items: DepartmentLite[] }>(
        "/api/v1/departments",
      );
      if (res.code === 0 && res.data) setDepartments(res.data.items);
    })();
  }, []);

  const onToggleStatus = () => {
    if (!user || user.status === "terminated") return;
    const next: UserStatus = user.status === "disabled" ? "active" : "disabled";
    const action = next === "active" ? "启用" : "停用";
    modal.confirm({
      title: `确认${action}用户？`,
      okText: action,
      cancelText: "取消",
      okButtonProps: { danger: next === "disabled" },
      onOk: async () => {
        const res = await apiJson(`/api/v1/users/${user.id}/status`, {
          method: "PATCH",
          body: JSON.stringify({ status: next }),
        });
        if (res.code === 0) {
          message.success(`${action}成功`);
          await loadDetail();
          await loadAudits();
        } else {
          message.error(res.message || `${action}失败`);
        }
      },
    });
  };

  const onTerminate = () => {
    if (!user) return;
    modal.confirm({
      title: "确认标记离职？",
      content: "离职后账号无法登录，历史数据保留。",
      okText: "确认",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        const res = await apiJson(`/api/v1/users/${user.id}`, {
          method: "DELETE",
        });
        if (res.code === 0) {
          message.success("已标记离职");
          await loadDetail();
          await loadAudits();
        } else {
          message.error(res.message || "操作失败");
        }
      },
    });
  };

  const onResetPassword = () => {
    if (!user) return;
    let pwd = "";
    modal.confirm({
      title: "重置密码",
      content: (
        <Input.Password
          placeholder="新密码（≥6 位）"
          onChange={(e) => {
            pwd = e.target.value;
          }}
        />
      ),
      okText: "重置",
      cancelText: "取消",
      onOk: async () => {
        if (!pwd || pwd.length < 6) {
          message.error("密码至少 6 位");
          return Promise.reject();
        }
        const res = await apiJson(`/api/v1/users/${user.id}/reset-password`, {
          method: "POST",
          body: JSON.stringify({ new_password: pwd }),
        });
        if (res.code === 0) {
          message.success("密码已重置");
          await loadAudits();
        } else {
          message.error(res.message || "重置失败");
          return Promise.reject();
        }
      },
    });
  };

  const onRevokeSessions = () => {
    if (!user) return;
    modal.confirm({
      title: "注销全部会话？",
      content: "目标用户将立即下线（含当前设备若为其本人）。",
      okText: "注销全部",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        const res = await apiJson(
          `/api/v1/users/${user.id}/sessions/revoke-all`,
          { method: "POST" },
        );
        if (res.code === 0) {
          message.success("已注销全部会话");
          await loadSessions();
          await loadAudits();
        } else {
          message.error(res.message || "操作失败");
        }
      },
    });
  };

  const openEdit = () => {
    if (!user) return;
    editForm.setFieldsValue({
      name: user.name,
      email: user.email,
      phone: user.phone,
      id_card: user.id_card || "",
      position: user.position,
      main_department_id: user.main_department_id,
    });
    setEditOpen(true);
  };

  const onSaveEdit = async () => {
    if (!user) return;
    try {
      const values = await editForm.validateFields();
      const body = {
        ...values,
        id_card:
          values.id_card === undefined || values.id_card === ""
            ? null
            : values.id_card,
      };
      const res = await apiJson<UserDetail>(`/api/v1/users/${user.id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      if (res.code === 0) {
        message.success("已保存");
        setEditOpen(false);
        await loadDetail();
        await loadAudits();
      } else {
        message.error(res.message || "保存失败");
      }
    } catch (err) {
      if ((err as Error).message) message.error((err as Error).message);
    }
  };

  const sessionColumns: ColumnsType<SessionRow> = [
    {
      title: "登录时间",
      dataIndex: "created_at",
      render: (v: string | null | undefined) =>
        v ? new Date(v).toLocaleString() : "—",
    },
    {
      title: "IP",
      dataIndex: "client_ip",
      render: (v: string | null | undefined) => v || "—",
    },
    {
      title: "User-Agent",
      dataIndex: "user_agent",
      ellipsis: true,
      render: (v: string | null | undefined) => v || "—",
    },
  ];

  const auditColumns: ColumnsType<AuditRow> = [
    {
      title: "时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string | null | undefined) =>
        v ? new Date(v).toLocaleString() : "—",
    },
    {
      title: "操作者",
      width: 160,
      render: (_: unknown, r) => (
        <span>
          {r.actor_id || "—"}
          {r.actor_role ? (
            <Typography.Text type="secondary"> ({r.actor_role})</Typography.Text>
          ) : null}
        </span>
      ),
    },
    { title: "动作", dataIndex: "action", width: 180 },
    { title: "摘要", dataIndex: "summary", ellipsis: true },
    {
      title: "结果",
      dataIndex: "result",
      width: 90,
      render: (v: string | null | undefined) => v || "—",
    },
    {
      title: "IP",
      dataIndex: "client_ip",
      width: 130,
      render: (v: string | null | undefined) => v || "—",
    },
  ];

  if (loading) {
    return <div style={{ padding: 24 }}>加载中…</div>;
  }

  if (notFound || !user) {
    return (
      <div style={{ padding: 24 }}>
        <Typography.Paragraph>用户不存在或无权查看。</Typography.Paragraph>
        <Link href="/organization/users">返回用户列表</Link>
      </div>
    );
  }

  const initial = (user.name || user.username || "?").slice(0, 1);

  return (
    <>
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
          <Space size="middle">
            <Link href="/organization/users">
              <Button>← 返回</Button>
            </Link>
            <Avatar size={48}>{initial}</Avatar>
            <div>
              <Typography.Title level={4} style={{ margin: 0 }}>
                {user.name}{" "}
                <Typography.Text type="secondary" style={{ fontSize: 14 }}>
                  @{user.username}
                </Typography.Text>
              </Typography.Title>
              <Space size="small" style={{ marginTop: 4 }}>
                <Typography.Text type="secondary">
                  工号 {user.employee_no}
                </Typography.Text>
                <Tag color={STATUS_COLOR[user.status]}>
                  {STATUS_LABEL[user.status]}
                </Tag>
              </Space>
            </div>
          </Space>
          <Space wrap>
            <Button onClick={openEdit}>编辑</Button>
            <Button onClick={onResetPassword}>重置密码</Button>
            {user.status !== "terminated" && (
              <Button onClick={onToggleStatus}>
                {user.status === "disabled" ? "启用" : "停用"}
              </Button>
            )}
            {user.status !== "terminated" && (
              <Button danger onClick={onTerminate}>
                标记离职
              </Button>
            )}
          </Space>
        </Space>

        <Tabs
          items={[
            {
              key: "basic",
              label: "基本信息",
              children: (
                <Descriptions bordered column={2} size="middle">
                  <Descriptions.Item label="手机">
                    {user.phone || "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="邮箱">
                    {user.email || "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="身份证">
                    {user.id_card || "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="职位">
                    {user.position || "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="入职日期">
                    {user.hire_date || "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="创建时间">
                    {user.created_at
                      ? new Date(user.created_at).toLocaleString()
                      : "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="最后登录">
                    {user.last_login_at
                      ? new Date(user.last_login_at).toLocaleString()
                      : "从未登录"}
                  </Descriptions.Item>
                  <Descriptions.Item label="最后 IP">
                    {user.last_login_ip || "—"}
                  </Descriptions.Item>
                </Descriptions>
              ),
            },
            {
              key: "org",
              label: "部门与角色",
              children: (
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  <div>
                    <Typography.Text strong>部门</Typography.Text>
                    <div style={{ marginTop: 8 }}>
                      {(user.departments || []).length === 0 ? (
                        <Typography.Text type="secondary">无</Typography.Text>
                      ) : (
                        (user.departments || []).map((d) => (
                          <Tag
                            key={d.id}
                            color={d.is_primary ? "blue" : undefined}
                            style={{ marginBottom: 4 }}
                          >
                            {d.name}
                            {d.is_primary ? "（主）" : ""}
                          </Tag>
                        ))
                      )}
                    </div>
                  </div>
                  <div>
                    <Typography.Text strong>角色</Typography.Text>
                    <div style={{ marginTop: 8 }}>
                      {(user.roles || []).length === 0 ? (
                        <Tag color="blue">{user.role}</Tag>
                      ) : (
                        (user.roles || []).map((r) => (
                          <Tag
                            key={r.code}
                            color={r.is_primary ? "blue" : undefined}
                            style={{ marginBottom: 4 }}
                          >
                            {r.name || r.code}
                            {r.is_primary ? "（主）" : ""}
                          </Tag>
                        ))
                      )}
                    </div>
                  </div>
                </Space>
              ),
            },
            {
              key: "sessions",
              label: "会话历史",
              children: (
                <>
                  <Space style={{ marginBottom: 12 }}>
                    <Button danger onClick={onRevokeSessions}>
                      注销全部会话
                    </Button>
                    <Button onClick={() => void loadSessions()}>刷新</Button>
                  </Space>
                  <Table
                    rowKey="id"
                    size="small"
                    columns={sessionColumns}
                    dataSource={sessions}
                    pagination={false}
                  />
                </>
              ),
            },
            {
              key: "audits",
              label: "操作日志",
              children: (
                <Table
                  rowKey="id"
                  size="small"
                  columns={auditColumns}
                  dataSource={audits}
                  pagination={{
                    current: auditPage,
                    pageSize: auditPageSize,
                    total: auditTotal,
                    showSizeChanger: true,
                    onChange: (p, ps) => {
                      setAuditPage(p);
                      setAuditPageSize(ps);
                    },
                  }}
                />
              ),
            },
          ]}
        />
      </Space>

      <Drawer
        title={`编辑用户：${user.username}`}
        open={editOpen}
        onClose={() => setEditOpen(false)}
        width={480}
        destroyOnClose
        extra={
          <Button type="primary" onClick={() => void onSaveEdit()}>
            保存
          </Button>
        }
      >
        <Form form={editForm} layout="vertical">
          <Form.Item label="显示名" name="name">
            <Input />
          </Form.Item>
          <Form.Item label="邮箱" name="email">
            <Input />
          </Form.Item>
          <Form.Item label="手机号" name="phone" rules={[PHONE_RULE]}>
            <Input />
          </Form.Item>
          <Form.Item label="身份证号" name="id_card" rules={[ID_CARD_RULE]}>
            <Input placeholder="选填" />
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
      </Drawer>
    </>
  );
}
