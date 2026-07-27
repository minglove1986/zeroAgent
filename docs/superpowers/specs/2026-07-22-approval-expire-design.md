# 审批超时取消设计

@author 赵振明
@date 2026-07-22 10:55:21

## 范围（已批准）

- 默认 `expires_at = now + approval_timeout_minutes`（默认 30）
- 惰性：`expire_due_approvals` 在列表/决定前执行；`POST /approvals/expire-due`
- 过期 → `cancelled` + 通知；workflow 实例 cancel

## 定时（修订）

原「不做 Celery Beat」已废止。  
Beat 扫描由 `2026-07-22-celery-harden-design.md` 启用；本文件惰性过期与 `POST /approvals/expire-due` 仍有效。
