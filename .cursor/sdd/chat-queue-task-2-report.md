# Task 2 报告：postSse AbortSignal 支持

**完成时间（东八区）**：2026-07-30 14:45:16  
**作者**：赵振明  
**状态**：✅ 已完成

## 变更摘要

| 文件 | 操作 |
|------|------|
| `web/src/lib/sse.ts` | 修改 `postSse` 签名，新增可选第 4 参数并传入 `fetch` |

## 实现细节

### 签名

```typescript
export async function postSse(
  path: string,
  body: unknown,
  onEvent: SseHandler,
  options?: { signal?: AbortSignal },
): Promise<void>
```

### fetch 传参

- `signal: options?.signal` 写入 `fetch` 的 `RequestInit`。
- 未传 `options` 或 `options.signal` 时为 `undefined`，行为与改前一致。

### AbortError 传播

- 函数体内**无**包裹 `fetch` / `reader.read` 的 try/catch。
- `signal.abort()` 后：
  - 若尚未建立连接：`fetch` 抛出 `DOMException`（`name === "AbortError"`）。
  - 若已在读流：`reader.read()` 抛出同类错误。
- 错误原样向上抛出，供 ChatPage（Task 3+）用 `error.name === "AbortError"` 区分用户取消与真实失败。

### 读流循环

- `while (true) { await reader.read() }` 逻辑未改；abort 时由底层自动中断。

## 调用方兼容性

| 调用点 | 文件 | 第 4 参 | 结论 |
|--------|------|---------|------|
| messages/send | `web/src/app/chat/page.tsx:566` | 未传 | ✅ 兼容 |
| card-action | `web/src/app/chat/page.tsx:679` | 未传 | ✅ 兼容 |
| retry | `web/src/app/chat/page.tsx:770` | 未传 | ✅ 兼容 |

**ChatPage 未改动**（符合 Task 2 范围）。

## 自审清单

- [x] 第 4 参数可选，现有三处 `postSse(a,b,c)` 无需修改
- [x] `signal` 仅传给 `fetch`，不重复包装 AbortController
- [x] 不吞 AbortError
- [x] 方法注释说明 abort 语义
- [x] 未引入 `@author` 于函数级（文件头已有）；新增方法注释符合规范
- [x] 未改 ChatPage / 后端
- [x] 未 git commit

## 验证

| 项 | 结果 |
|----|------|
| `npx tsc --noEmit`（web/） | ✅ 通过 |
| ESLint（sse.ts） | ✅ 无新增告警 |
| 单元测试 | ⏭ 跳过 — web 包无 vitest/jest；按 brief 留待 Chat 联调验收 |

## 风险与后续

1. **Task 3（ChatPage）** 需在 `send` / `card-action` / `retry` 路径创建 `AbortController`，并在 dismiss/supersede 时 `abort()`，catch 中忽略 `AbortError`。
2. **已收到部分 SSE 再 abort**：已触发的 `onEvent` 不会回滚；上层需自行处理半完成 UI（与后端 dismiss 语义对齐）。
3. **HTTP 错误 vs abort**：`!res.ok` 仍抛 `Error(formatApiErrorText(...))`，与 `AbortError` 类型不同，便于区分。

## Git

按约束：**未 commit**。
