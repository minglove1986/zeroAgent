/**
 * 管理端会话上下文：拉取 /auth/me、管理员准入、退出登录。
 *
 * @author 赵振明
 * @date 2026-07-29 15:10:45
 */
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { apiJson } from "./api";

export type AdminUser = {
  id: string;
  username: string;
  name?: string;
  role: string;
  department_id?: string | null;
};

const ADMIN_ROLES = new Set(["platform_admin", "super_admin"]);

/** 判断角色是否允许进入管理端。 */
export function isAdminRole(role: string | undefined | null): boolean {
  return !!role && ADMIN_ROLES.has(role);
}

type AuthContextValue = {
  user: AdminUser | null;
  loading: boolean;
  refresh: () => Promise<AdminUser | null>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * 提供全局会话状态；登录成功后由 refresh 同步。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AdminUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (): Promise<AdminUser | null> => {
    try {
      const res = await apiJson<AdminUser>("/api/v1/auth/me");
      if (res.code === 0 && res.data) {
        setUser(res.data);
        return res.data;
      }
      setUser(null);
      return null;
    } catch {
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await apiJson("/api/v1/auth/logout", { method: "POST" });
    } catch {
      /* 忽略网络错误，本地仍清会话 */
    }
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, refresh, logout }),
    [user, loading, refresh, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** 读取会话上下文；必须在 AuthProvider 内使用。 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}

/**
 * 管理页守卫：未登录 → /login；非管理员 → /403。
 */
export function AdminGuard({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent(pathname || "/overview")}`);
      return;
    }
    if (!isAdminRole(user.role)) {
      router.replace("/403");
    }
  }, [loading, user, router, pathname]);

  if (loading) {
    return <div style={{ padding: 24 }}>加载会话...</div>;
  }
  if (!user || !isAdminRole(user.role)) {
    return null;
  }
  return <>{children}</>;
}
