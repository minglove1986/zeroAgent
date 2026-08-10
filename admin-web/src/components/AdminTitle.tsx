/**
 * 管理端顶栏标题上下文：壳层持久时由各页设置标题，避免整壳随路由重挂。
 *
 * @author 赵振明
 * @date 2026-08-10 13:45:12
 */
"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type AdminTitleContextValue = {
  title: string;
  setTitle: (title: string) => void;
};

const AdminTitleContext = createContext<AdminTitleContextValue | null>(null);

/** 提供顶栏标题状态，挂在持久 Admin 壳内。 */
export function AdminTitleProvider({ children }: { children: ReactNode }) {
  const [title, setTitle] = useState("控制台");
  const value = useMemo(() => ({ title, setTitle }), [title]);
  return (
    <AdminTitleContext.Provider value={value}>{children}</AdminTitleContext.Provider>
  );
}

/** 读取当前顶栏标题。 */
export function useAdminTitle(): string {
  return useContext(AdminTitleContext)?.title ?? "控制台";
}

/**
 * 页面进入时写入顶栏标题；离开时不强制清空（下一页会覆盖）。
 */
export function useAdminPageTitle(title: string): void {
  const ctx = useContext(AdminTitleContext);
  useEffect(() => {
    if (!ctx) return;
    ctx.setTitle(title);
  }, [ctx, title]);
}
