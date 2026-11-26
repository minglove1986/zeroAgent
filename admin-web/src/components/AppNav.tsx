/**
 * 管理端三段式导航：树形侧栏（分组折叠 + 整栏收窄）+ 顶栏标题/主题/退出。
 *
 * @author 赵振明
 * @date 2026-08-10 13:29:58
 */
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
  type ComponentType,
} from "react";
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  RightOutlined,
} from "@ant-design/icons";
import * as AntIcons from "@ant-design/icons";
import { BrandMark } from "./BrandMark";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { useAdminTitle } from "./AdminTitle";
import { useAuth } from "@/lib/auth";
import { apiJson } from "@/lib/api";

type MenuItem = {
  code: string;
  name: string;
  icon?: string | null;
  path?: string | null;
  children?: MenuItem[];
};

const STORAGE_COLLAPSED = "za-admin-nav-collapsed";
const STORAGE_OPEN = "za-admin-nav-open-groups";

const FALLBACK_TREE: MenuItem[] = [
  { code: "overview", name: "概览", icon: "DashboardOutlined", path: "/overview" },
  {
    code: "group.knowledge",
    name: "知识与编排",
    children: [
      { code: "knowledge", name: "知识库", icon: "BookOutlined", path: "/knowledge" },
      {
        code: "knowledge.focus-terms",
        name: "检索专名",
        icon: "TagOutlined",
        path: "/knowledge/focus-terms",
      },
    ],
  },
  {
    code: "group.org",
    name: "组织权限",
    children: [
      { code: "org.users", name: "用户管理", icon: "TeamOutlined", path: "/organization/users" },
      {
        code: "org.roles",
        name: "角色权限",
        icon: "SafetyCertificateOutlined",
        path: "/organization/roles",
      },
      {
        code: "org.departments",
        name: "部门管理",
        icon: "ApartmentOutlined",
        path: "/organization/departments",
      },
      {
        code: "org.menus",
        name: "菜单管理",
        icon: "MenuOutlined",
        path: "/organization/menus",
      },
    ],
  },
  {
    code: "group.system",
    name: "系统治理",
    children: [
      { code: "system.persona", name: "系统人格", icon: "UserOutlined", path: "/system/persona" },
      {
        code: "models",
        name: "模型治理",
        icon: "CloudOutlined",
        path: "/system/llm-models",
      },
      {
        code: "system.memory-fields",
        name: "记忆白名单",
        icon: "FilterOutlined",
        path: "/system/memory-fields",
      },
      {
        code: "system.l2-keywords",
        name: "L2关键词",
        icon: "TagsOutlined",
        path: "/system/l2-keywords",
      },
    ],
  },
  {
    code: "group.operations",
    name: "运维审计",
    children: [
      {
        code: "operations.audit",
        name: "审计日志",
        icon: "AuditOutlined",
        path: "/operations/audit",
      },
      {
        code: "operations.feedbacks",
        name: "消息反馈",
        icon: "MessageOutlined",
        path: "/operations/feedbacks",
      },
    ],
  },
];

/** 判断路径是否命中菜单项（精确或子路径）。 */
function isPathActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** 收集含子路径命中的分组 code，用于默认展开。 */
function collectOpenByPath(nodes: MenuItem[], pathname: string): string[] {
  const open: string[] = [];
  for (const n of nodes) {
    if (!n.children?.length) continue;
    const hit = n.children.some(
      (c) =>
        (c.path && isPathActive(pathname, c.path)) ||
        (c.children?.length &&
          collectOpenByPath([c], pathname).length > 0),
    );
    if (hit) {
      open.push(n.code);
      open.push(...collectOpenByPath(n.children, pathname));
    }
  }
  return open;
}

/** 拍平仅含 path 的叶子，供窄栏图标轨使用。 */
function flattenLeaves(nodes: MenuItem[]): MenuItem[] {
  const out: MenuItem[] = [];
  const walk = (list: MenuItem[]) => {
    for (const n of list) {
      if (n.path) out.push(n);
      if (n.children?.length) walk(n.children);
    }
  };
  walk(nodes);
  return out;
}

/** 按菜单 icon 名解析 Ant Design 图标组件。 */
function resolveIcon(name?: string | null): ComponentType<{ style?: object }> | null {
  if (!name) return null;
  const icons = AntIcons as unknown as Record<
    string,
    ComponentType<{ style?: object }> | undefined
  >;
  const Icon = icons[name];
  return typeof Icon === "function" ? Icon : null;
}

export default function AppNav({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const title = useAdminTitle();
  const [tree, setTree] = useState<MenuItem[]>(FALLBACK_TREE);
  const [collapsed, setCollapsed] = useState(false);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      const c = localStorage.getItem(STORAGE_COLLAPSED);
      if (c === "1") setCollapsed(true);
      const raw = localStorage.getItem(STORAGE_OPEN);
      if (raw) {
        const parsed = JSON.parse(raw) as string[];
        if (Array.isArray(parsed)) setOpenGroups(new Set(parsed));
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiJson<{ items: MenuItem[] }>(
          "/api/v1/menus/tree?app=admin",
        );
        if (cancelled) return;
        if (res.code === 0 && res.data?.items?.length) {
          setTree(res.data.items);
        }
      } catch {
        /* 保持 FALLBACK */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const need = collectOpenByPath(tree, pathname);
    if (!need.length) return;
    setOpenGroups((prev) => {
      const next = new Set(prev);
      let changed = false;
      for (const code of need) {
        if (!next.has(code)) {
          next.add(code);
          changed = true;
        }
      }
      if (changed) {
        try {
          localStorage.setItem(STORAGE_OPEN, JSON.stringify([...next]));
        } catch {
          /* ignore */
        }
      }
      return changed ? next : prev;
    });
  }, [pathname, tree]);

  /** 切换整侧栏收窄，并持久化。 */
  const toggleCollapsed = useCallback(() => {
    setCollapsed((v) => {
      const next = !v;
      try {
        localStorage.setItem(STORAGE_COLLAPSED, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  /** 切换分组展开，并持久化。 */
  const toggleGroup = useCallback((code: string) => {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      try {
        localStorage.setItem(STORAGE_OPEN, JSON.stringify([...next]));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  async function onLogout() {
    await logout();
    router.replace("/login");
  }

  const displayName = user?.name || user?.username || "管理员";
  const leaves = useMemo(() => flattenLeaves(tree), [tree]);

  /** 渲染展开态树节点（分组 / 叶子）。 */
  function renderNode(node: MenuItem, depth = 0): ReactNode {
    const hasChildren = Boolean(node.children?.length);
    const open = openGroups.has(node.code);

    if (hasChildren) {
      return (
        <div key={node.code} className="admin-nav-group">
          <button
            type="button"
            className={`admin-nav-group-btn${open ? " is-open" : ""}`}
            onClick={() => toggleGroup(node.code)}
            aria-expanded={open}
          >
            <span className="admin-nav-group-label">{node.name}</span>
            <RightOutlined className="admin-nav-chevron" />
          </button>
          <div className={`admin-nav-collapse${open ? " is-open" : ""}`}>
            <div className="admin-nav-collapse-inner">
              {node.children!.map((c) => renderNode(c, depth + 1))}
            </div>
          </div>
        </div>
      );
    }

    if (!node.path) return null;
    const active = isPathActive(pathname, node.path);
    const Icon = resolveIcon(node.icon);
    return (
      <Link
        key={node.code}
        href={node.path}
        className={`admin-nav-link${active ? " is-active" : ""}`}
        style={{ paddingLeft: 16 + depth * 8 }}
        title={node.name}
      >
        <span className="admin-nav-active-bar" aria-hidden />
        {Icon ? <Icon style={{ fontSize: 16 }} /> : <span className="admin-nav-dot" />}
        <span className="admin-nav-link-text">{node.name}</span>
      </Link>
    );
  }

  return (
    <div className="admin-shell">
      <aside className={`admin-sidebar${collapsed ? " is-collapsed" : ""}`}>
        <div className="admin-sidebar-brand">
          <BrandMark size={collapsed ? 28 : 32} priority />
          {!collapsed && (
            <div className="admin-sidebar-brand-text">
              <strong>zeroAgent</strong>
              <span>Admin</span>
            </div>
          )}
        </div>

        <nav className="admin-sidebar-nav" aria-label="管理端菜单">
          {collapsed
            ? leaves.map((n) => {
                if (!n.path) return null;
                const active = isPathActive(pathname, n.path);
                const Icon = resolveIcon(n.icon);
                return (
                  <Link
                    key={n.code}
                    href={n.path}
                    className={`admin-nav-icon-link${active ? " is-active" : ""}`}
                    title={n.name}
                  >
                    <span className="admin-nav-active-bar" aria-hidden />
                    {Icon ? (
                      <Icon style={{ fontSize: 18 }} />
                    ) : (
                      <span className="admin-nav-initial">{n.name.slice(0, 1)}</span>
                    )}
                  </Link>
                );
              })
            : tree.map((n) => renderNode(n))}
        </nav>

        <button
          type="button"
          className="admin-sidebar-toggle"
          onClick={toggleCollapsed}
          title={collapsed ? "展开侧栏" : "收起侧栏"}
          aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
        >
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          {!collapsed && <span>收起菜单</span>}
        </button>
      </aside>

      <div className="admin-main">
        <header className="admin-header">
          <h1>{title}</h1>
          <div className="admin-header-actions">
            <ThemeSwitcher />
            <span className="admin-header-user">
              {displayName}
              {user?.role ? ` · ${user.role}` : ""}
            </span>
            <button type="button" className="btn btn-danger" onClick={() => void onLogout()}>
              退出
            </button>
          </div>
        </header>
        <main className="admin-content">{children}</main>
      </div>
    </div>
  );
}
