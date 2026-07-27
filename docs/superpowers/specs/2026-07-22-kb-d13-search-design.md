# D13 并集鉴权进检索设计

@author 赵振明
@date 2026-07-22 15:00:38

## 范围（已确认）

查知识库 / `kb_lookup` 时：

1. 先按 Agent 绑定的库缩小范围（已有）  
2. 再按**当前用户**对知识库的授权过滤（本刀）  
3. **无任何授权行 → 拒绝**（该库不可搜）  
4. **`platform_admin` 不卡权限**（跳过第 2 步；仍可受 Agent 绑定约束）  

## 不做

Hybrid、`kg_ids`、改并集算法本身  

## 行为（白话）

| 情况 | 结果 |
|---|---|
| KB 没有配任何「谁可以看」 | 普通人搜不到 |
| KB 配了授权且用户命中（本人/部门/角色） | 可搜 |
| KB 配了但用户没命中 | 搜不到 |
| 超级管理员 | 不看授权表，凡 Agent 允许（或未绑定时的全库解析）都可搜 |
| Agent 只绑了库 A | 即使用户有权看 B，也只搜 A |

## 实现要点

- `list_accessible_kb_ids(db, user_id, department_ids, role_ids)`：逐库读 `KbPermission`；0 行 → 跳过；有行 → `can_access_kb_union`  
- 部门：`Actor.department_id` + `UserDepartment` 中该用户全部部门  
- 角色：`[Actor.role]`（admin 整步跳过）  
- `run_kb_lookup(..., user_id=, department_ids=, role_ids=, is_platform_admin=)`  
- runtime / messages 传入 Actor 上下文  

## 测试

- 无权限行 → 非 admin 检索空  
- 有 user/dept 授权 → 命中  
- admin → 无授权行也能命中（在 Agent 允许范围内）  
- 与 agent_kbs 求交仍成立  

## 运维注意

演示前须给要用的 KB **至少写一条** `KbPermission`，否则非管理员永远搜不到。  
