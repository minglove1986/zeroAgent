# 系统人格提示词设计

> 状态：已确认（含安全段 / 试聊 / 恢复默认）  
> 日期：2026-07-29  
> 作者：赵振明  
> 对齐 PRD：**D43–D47**

## 目标

1. 管理后台可配置「系统人格」system 提示词（如公司智能助手人设）。  
2. **system 处理器路径必注入**（enabled 时）。  
3. 新建/编辑 Agent 可勾选 **继承系统人格**；勾选后运行时拼接同一段文案（非创建时拷贝）。  
4. **平台安全段**始终最前硬注入；管理端只读。  
5. 管理端 **人设试聊**（无副作用）与 **恢复默认种子**。

## 非目标

- 多套人格 A/B、按部门差异化。  
- 将 system 建成 `agents` 表假实体。  
- 人设草稿发布流。  
- 管理端完整 Agent CRUD（继承字段协议已存在即可）。

## 数据

- 表 `system_persona_settings`：单行生效（`id=sys_persona_default`）。  
- `agents.inherit_system_persona`：SMALLINT，默认 1。  
- 平台安全文案：**代码常量**（非 DB），见 `platform_safety.py`。

## 缓存

遵循「配置类模块缓存约定」：MySQL → 启动/CRUD 刷 Redis `za:system:persona:v1` → 热路径只读。

## 注入顺序（D45）

```text
【平台安全】 → 【系统人格】(enabled) → 身份 → 记忆 → 【来源边界】 →（Agent 技能/模板）
```

### 与来源边界的分工

| 块 | 职责 |
|---|---|
| 平台安全 | 拒泄密 / 高风险走审批 / 不伪造身份与权限 / 不绕过安全策略 |
| 来源边界 | 第三人称身份：称呼只信身份块与记忆，会话/RAG 中人名不当作用户 |

停用人格后：**不注入**【系统人格】，但仍注入【平台安全】。

## 试聊（D46）

- `POST /api/v1/system/persona/test`  
  - body：`{ message, system_prompt? }`  
  - 未传 `system_prompt`：用当前生效配置（含 enabled；若停用则不带人格段）  
  - 传入：用候选文案试跑（可不先保存）  
- 仅拼：平台安全 +（候选或当前）人格 + 极简身份占位（管理员试聊身份）  
- **不**加载用户记忆、不写短记忆、不 enqueue 记忆抽取、不改业务状态  
- 走 LiteLLM 单轮非流式；写审计 `resource_type=system_persona, action=test`

## 恢复默认（D47）

- `POST /api/v1/system/persona/reset-default`  
- 回写种子 `title` / `system_prompt`（`enabled` 保持当前或按产品定为保持）；`revision+1`；刷 Redis；审计 `action=reset_default`

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/system/persona` | 读配置 + 缓存状态 + 只读安全段 |
| PUT | `/api/v1/system/persona` | 更新（乐观锁 revision） |
| POST | `/api/v1/system/persona/reload-cache` | DB→Redis |
| POST | `/api/v1/system/persona/test` | 无副作用试聊 |
| POST | `/api/v1/system/persona/reset-default` | 恢复种子 |
