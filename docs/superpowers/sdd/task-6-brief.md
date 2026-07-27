# Task 6 Brief

### Task 6: 重做 `web/src/app/knowledge/page.tsx`

**Files:**
- Modify: `web/src/app/knowledge/page.tsx`
- Modify: `web/src/app/globals.css`（仅当需要 `.kb-*` 类时）

**Interfaces:**
- Consumes: Task 2–5 全部 API；现有 `apiJson`、`AppNav`

- [ ] **Step 1: 页面结构（client component）**

状态：`kbs`、`selectedKbId`、`docs`、`perms`、`showPerms`、`file`、`title`、`busy`、`error`、`msg`、`isAdmin`（可由首次 list 后根据「能否看到新建按钮」简化：尝试用环境/角色头不可靠；**第一刀**：始终渲染「新建」按钮，非超管点击后展示后端 403 文案；或调用登录态若前端已有 role 则用它——查 `web` 内是否存 role，有则用，无则按钮+403）。

布局：

1. 左：KB 列表 + 新建表单（name）  
2. 右：上传表单；文档表列：title / status / hit_rate / qa_count / 操作（发布、删除、恢复）  
3. 权限面板：列表 items + 增行 + 保存 PUT（失败 403 提示仅超管）

- [ ] **Step 2: 轮询**

```typescript
useEffect(() => {
  const processing = docs.filter((d) => d.status === "processing" && !d.deleted_at);
  if (!processing.length) return;
  const t = setInterval(async () => {
    // 对每个 id GET /api/v1/documents/{id}/status 更新行
  }, 2000);
  return () => clearInterval(t);
}, [docs]);
```

- [ ] **Step 3: 操作绑定**

- 发布：`POST .../publish`；422 展示 `message`  
- 删除：`DELETE ...` 后刷新列表  
- 恢复：`POST .../recover` 后提示「需重新上传/入库后才能检索」  
- 上传：沿用现有 base64 → `POST /documents/upload`

- [ ] **Step 4: 手工联调清单（打勾）**

1. 超管建库出现在列表  
2. PUT 一条 user 权限后，employee 头可见该库  
3. 上传 txt → processing → ready（需 Celery worker）或 Mock 路径下最终状态正确  
4. 无 QA 发布 → 42201  
5. 软删后 `include_deleted=1` 可见；恢复提示可读  

- [ ] **Step 5: Commit**（仅用户要求时）

---
