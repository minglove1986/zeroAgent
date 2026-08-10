"use client";

import { useEffect, useState } from "react";
import { App, Avatar, Button, Card, Descriptions, Form, Input, Space } from "antd";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Me = {
  id: string;
  username: string;
  name: string;
  role: string;
  department_id?: string | null;
};

const ROLE_LABEL: Record<string, string> = {
  employee: "员工",
  expert: "业务专家",
  agent_dev: "Agent 开发者",
  department_admin: "部门管理员",
  platform_admin: "平台管理员",
  super_admin: "超级管理员",
};

export default function ProfilePage() {
  const { message } = App.useApp();
  const { user, refresh } = useAuth();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(false);
  const [pwdOpen, setPwdOpen] = useState(false);
  const [pwdForm] = Form.useForm();

  const loadMe = async () => {
    setLoading(true);
    try {
      const res = await apiJson<Me>("/api/v1/auth/me");
      if (res.code === 0 && res.data) setMe(res.data);
    } catch (err) {
      message.error((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMe();
  }, []);

  const onChangePwd = async () => {
    try {
      const v = await pwdForm.validateFields();
      const res = await apiJson("/api/v1/users/me/password", {
        method: "POST",
        body: JSON.stringify({
          old_password: v.old_password,
          new_password: v.new_password,
        }),
      });
      if (res.code === 0) {
        message.success("密码已更新，请重新登录");
        setPwdOpen(false);
        pwdForm.resetFields();
        await refresh();
      } else {
        message.error(res.message || "修改失败");
      }
    } catch (err) {
      if ((err as Error).message) message.error((err as Error).message);
    }
  };

  useAdminPageTitle("我的资料");
  return (
    <>
      <Card title="基本信息" loading={loading} style={{ maxWidth: 720 }}>
        <Space size={16} align="start">
          <Avatar size={64} style={{ background: "var(--primary, #1677ff)" }}>
            {(me?.name || me?.username || "?").slice(0, 1).toUpperCase()}
          </Avatar>
          <Descriptions column={1} size="middle" bordered>
            <Descriptions.Item label="用户名">
              {me?.username || user?.username || "-"}
            </Descriptions.Item>
            <Descriptions.Item label="显示名">
              {me?.name || user?.name || "-"}
            </Descriptions.Item>
            <Descriptions.Item label="角色">
              {ROLE_LABEL[me?.role || user?.role || ""] ||
                me?.role ||
                user?.role ||
                "-"}
            </Descriptions.Item>
            <Descriptions.Item label="部门 ID">
              {me?.department_id || user?.department_id || "-"}
            </Descriptions.Item>
            <Descriptions.Item label="用户 ID">{me?.id || "-"}</Descriptions.Item>
          </Descriptions>
        </Space>
        <div style={{ marginTop: 16 }}>
          <Space>
            <Button type="primary" onClick={() => setPwdOpen(true)}>
              修改密码
            </Button>
          </Space>
        </div>
      </Card>

      {pwdOpen && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setPwdOpen(false)}
        >
          <Card
            title="修改密码"
            style={{ width: 460 }}
            onClick={(e) => e.stopPropagation()}
          >
            <Form form={pwdForm} layout="vertical">
              <Form.Item
                label="旧密码"
                name="old_password"
                rules={[{ required: true, message: "必填" }]}
              >
                <Input.Password />
              </Form.Item>
              <Form.Item
                label="新密码"
                name="new_password"
                rules={[
                  { required: true, message: "必填" },
                  { min: 6, message: "至少 6 位" },
                ]}
              >
                <Input.Password />
              </Form.Item>
              <Form.Item
                label="确认新密码"
                name="confirm_password"
                dependencies={["new_password"]}
                rules={[
                  { required: true, message: "必填" },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue("new_password") === value) {
                        return Promise.resolve();
                      }
                      return Promise.reject(new Error("两次密码不一致"));
                    },
                  }),
                ]}
              >
                <Input.Password />
              </Form.Item>
            </Form>
            <Space style={{ marginTop: 8 }}>
              <Button type="primary" onClick={onChangePwd}>
                提交
              </Button>
              <Button onClick={() => setPwdOpen(false)}>取消</Button>
            </Space>
          </Card>
        </div>
      )}
    </>
  );
}