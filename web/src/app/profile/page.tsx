/**
 * 员工端"我的资料"页。
 * @author 赵振明
 * @date 2026-08-07
 */
"use client";

import { useEffect, useState } from "react";
import { apiJson } from "@/lib/api";

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
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiJson<Me>("/api/v1/auth/me")
      .then((res) => {
        if (res.code === 0 && res.data) setMe(res.data);
        else setError(res.message || "加载失败");
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <h1>我的资料</h1>
        <p style={{ color: "#c00" }}>{error}</p>
        <p>请前往 <a href="/login">登录</a>。</p>
      </div>
    );
  }

  return (
    <div style={{ padding: 24, maxWidth: 720, margin: "0 auto" }}>
      <h1>我的资料</h1>
      {!me ? (
        <p>加载中...</p>
      ) : (
        <div
          style={{
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            padding: 16,
            background: "#fff",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              <tr>
                <th style={th}>用户名</th>
                <td style={td}>{me.username}</td>
              </tr>
              <tr>
                <th style={th}>显示名</th>
                <td style={td}>{me.name}</td>
              </tr>
              <tr>
                <th style={th}>角色</th>
                <td style={td}>{ROLE_LABEL[me.role] || me.role}</td>
              </tr>
              <tr>
                <th style={th}>主部门</th>
                <td style={td}>{me.department_id || "-"}</td>
              </tr>
              <tr>
                <th style={th}>用户 ID</th>
                <td style={td}>{me.id}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      <p style={{ marginTop: 16, color: "#6b7280", fontSize: 12 }}>
        资料修改请联系系统管理员；密码修改请前往「修改密码」入口（v1.1）。
      </p>
    </div>
  );
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 12px",
  borderBottom: "1px solid #f1f5f9",
  width: 120,
  color: "#6b7280",
  fontWeight: 500,
};

const td: React.CSSProperties = {
  padding: "10px 12px",
  borderBottom: "1px solid #f1f5f9",
};