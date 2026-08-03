# 系统人格：平台安全段 + 试聊 + 恢复默认

> 日期：2026-07-29  
> 作者：赵振明  
> 规格：`docs/superpowers/specs/2026-07-29-system-persona-design.md`  
> PRD：D43–D47  

## Goal

在已落地的系统人格之上，补齐平台安全硬注入、管理端人设试聊与一键恢复默认。

## Tasks

### Task 1：平台安全段

- [x] 新增 `src/app/modules/system/platform_safety.py` 常量 `PLATFORM_SAFETY_RULE`
- [x] `TurnContextBlocks.system_sections()` 最前插入 `【平台安全】`
- [x] GET persona 响应附带 `platform_safety` 只读字段
- [x] 管理页只读展示该段

### Task 2：恢复默认

- [x] `persona_store.reset_persona_to_default`
- [x] `POST /api/v1/system/persona/reset-default` + 审计
- [x] UI 二次确认按钮

### Task 3：人设试聊

- [x] `POST /api/v1/system/persona/test`：安全 + 人格 + 极简身份；LiteLLM；审计 `action=test`
- [x] 管理页试聊区

### Task 4：测试与断点

- [x] 安全段始终在人格之前；停用人格仍有安全段
- [x] 试聊不落记忆；恢复默认等于种子
- [x] 更新 `CHECKPOINT.md`
