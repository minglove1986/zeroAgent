# 开发种子数据说明
# 用法（Task 2+）：python -m seeds.bootstrap
# 默认超管：admin / 见环境变量 SEED_ADMIN_PASSWORD

roles:
  - code: super_admin
    name: 超级管理员
  - code: department_admin
    name: 部门管理员
  - code: business_expert
    name: 业务专家
  - code: end_user
    name: 终端用户

# 部门管理员范围（D26）：用量/告警 + 用户只读 + 对话脱敏只读
# 禁止：启停用户 / 改角色 / 系统配置
