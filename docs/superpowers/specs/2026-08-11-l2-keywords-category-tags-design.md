# L2 关键词按分类标签呈现（管理端 UI）

> 状态：已实现 · 仅前端 · 无后端契约变更  
> 日期：2026-08-11

## 背景

扁平表格把同一分类短语打散，难以按意图分类扫词。改为「固定分类卡片 + 短语 Tag 云」。

## 裁定

- 纯前端按 `category` 分组；沿用 `GET/POST/PATCH/DELETE /api/v1/intent/l2-keywords` 与试跑/重载缓存。
- 列表 `page_size=200`，必要时翻页拉齐。
- Tag：短语 + 含/等/前徽标；停用灰显虚线；点击编辑；关闭确认软删。
- 分类标题旁「+」预填并锁定分类；`editForm` / `testForm` 分离。

## 落点

- `admin-web/src/app/(admin)/system/l2-keywords/page.tsx`

## 非目标

- 不新增 grouped API；不改 L2 匹配引擎。
