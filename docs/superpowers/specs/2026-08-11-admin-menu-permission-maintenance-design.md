# 管理端菜单定义 + 角色授权维护

> 状态：已实现 · 2026-08-11  
> 对应计划：菜单与权限维护页

## 裁定

- 组织权限下独立「菜单管理」`/organization/menus`（`org.menus`）
- 写：仅 `super_admin`；`platform_admin` 只读
- 角色菜单 PUT：仍仅超管；前端中文树勾选

## 后端

- `GET /api/v1/menus?manage=1`：平台管理员/超管可读全量（含隐藏）
- 写接口统一 `resolve_actor`；新建自定义菜单自动授 `super_admin` 可见
- 迁移 `0038_org_menus_admin`

## 前端

- `organization/menus/page.tsx`：树表维护
- `organization/roles`：`RoleMenusModal` 中文树 + 只读态

## 验收

1. 侧栏出现「菜单管理」
2. 超管可增改；平台管理员只读
3. 角色菜单权限为中文树，保存后侧栏按角色变化
