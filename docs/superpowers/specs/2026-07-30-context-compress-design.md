# 上下文摘要压缩设计

> 状态：已确认  
> 日期：2026-07-30  
> 作者：赵振明  
> 对齐：PRD §5.5「滑动窗口 + LLM 摘要压缩」；相对会话模型窗口 + 回合后异步  

## 1. 目标

1. 短记忆占用达到当前会话模型窗口的触发比例时，**异步**用 LLM 摘要早期轮次。  
2. 摘要写入 Redis，并改写短记忆为「摘要 + 近轮」，供**下一轮**注入。  
3. 本轮对话仍依赖 ContextBudgetPacker **优先级截断**防超窗，不阻塞首字。  

## 2. 非目标

- 同步阻塞发消息前压缩。  
- 删除 MySQL `messages` / 改写 UI 气泡。  
- 本期强制串联记忆抽取（可后续挂钩）。  
- 精确厂商 tokenizer。  

## 3. 已确认裁定

| 项 | 裁定 |
|---|---|
| 阈值口径 | **相对当前模型** `max_input_tokens`（回落 `CONTEXT_WINDOW_TOKENS`） |
| 触发 | 短记忆估算 token ≥ `window * trigger_ratio`（默认 0.75） |
| 摘要目标 | ≤ `min(target_max, window * target_ratio)`（默认 max=2000、ratio=0.15） |
| 时机 | 回合结束后 Celery 异步 |
| 同步安全网 | 保留 ContextBudgetPacker 截断 |

## 4. 数据

- Redis digest：`za:ctxdigest:{user_id}:{conversation_id}`  
  JSON：`text`, `model_name`, `window_tokens`, `created_at`, `source_turns`  
  TTL：与短记忆一致（2h）  
- 压缩成功后重建短记忆 list：1 条摘要占位 + 最近 K 条原始 turn（默认 K=4，user/assistant 合计条数）  

## 5. 注入顺序

平台安全 → 人格 → 身份 → 用户记忆 → **会话摘要（可选）** → 来源边界 → 短记忆近轮 / 打包历史  

## 6. 失败与防抖

- 同会话 `CONTEXT_COMPRESS_DEDUP_SECONDS` 内不重复投递。  
- LLM 失败 / 空摘要：不改写短记忆，仅打日志。  
- Worker 不可用：调度静默失败，对话仍靠截断。  

## 7. 验收

- 超阈触发任务；未超阈不触发。  
- 压缩后下一轮 system 含 `【会话摘要】`。  
- 换小窗模型后阈值随 `resolve_window_tokens` 变化。  
