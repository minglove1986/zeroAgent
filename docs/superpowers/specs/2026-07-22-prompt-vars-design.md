# Prompt 变量插值设计

@author 赵振明
@date 2026-07-22 10:42:58

## 范围（已批准 · 方案 A）

- 语法 `{{name}}`；Agent variables > 内置；未知保留原占位符
- `prompt_templates.variables_schema_json`；Agent 缺必填 → 422
- `agents.variables_json`
- `prompt_template_versions` 发布快照；rollback → draft
- 前端：模板 schema + Agent 变量表单

## 不做

自动优化、复杂表达式、回滚直接 published
