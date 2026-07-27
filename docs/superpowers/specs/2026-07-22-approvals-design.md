# 高风险审批待办设计

@author 赵振明
@date 2026-07-22 10:28:20

## 范围

- 表 `approval_tasks`（对齐库表 DDL）
- API：列表 / 创建 / 通过 / 驳回
- 通过后：`workflow_human` + `ref_type=workflow_instance` → resume；通知 requester
- 工作流启动进入 `waiting_human` 时自动创建待办
- 前端 `/approvals`

## 不做

- 真工具 FC 高风险、角色匹配、超时取消、对话内嵌卡
