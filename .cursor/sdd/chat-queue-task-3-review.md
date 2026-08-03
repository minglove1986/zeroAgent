# Task 3 审查：chatSendQueue 纯函数

**审查类型：** 只读（Spec + Quality）  
**审查时间：** 2026-07-30 14:52:00（东八区）  
**依据：** `chat-queue-task-3-brief.md`、`chat-queue-task-3-report.md`、`chat-queue-task-3-review-pkg.md`、`docs/superpowers/specs/2026-07-30-chat-send-queue-design.md` §4 / §8、`docs/superpowers/plans/2026-07-30-chat-send-queue.md` Task 3  
**审查者：** Code Review Agent  

---

## 裁决

| 维度 | 结论 |
|---|---|
| **Spec** | ✅ 通过 |
| **Quality** | **Approved**（有 Minor 测试/集成提示项，非阻塞 Task 3 验收） |

**一句话：** Task 3 按 brief 完整交付 `chatSendQueue` 纯函数模块与 8 项 Node 单测；`CHAT_SEND_QUEUE_MAX=5`、仅统计 `queued` 占名额、`dequeueForSend` FIFO 标 `sending`、`removeQueued` 仅删 `queued` 等核心语义与设计 §4 / §8 一致；未改 `page.tsx`、未 commit，符合全局约束。审查者复跑单测 8/8 PASS、`tsc --noEmit` PASS。

---

## Spec Compliance

| Brief / 设计 §4·§8 要求 | 状态 | 证据 |
|---|---|---|
| 新建 `web/src/lib/chatSendQueue.ts` | ✅ | 文件存在，91 行 |
| 新建 `web/src/lib/chatSendQueue.test.ts`（无 vitest 时用 node --test） | ✅ | 118 行；`web/package.json` 无 test 脚本，采用 Node 22 内置 test |
| `export const CHAT_SEND_QUEUE_MAX = 5` | ✅ | `chatSendQueue.ts` L7；单测 L35–37 |
| `QueueItemStatus` / `QueueItem` 类型 | ✅ | L9–15，与 brief 签名一致 |
| `enqueue`：满 5 条 `queued` → `{ ok: false, reason: "full" }` | ✅ | L34–47；单测 L39–43 |
| `enqueue`：成功追加 `{ localId, text, status: "queued" }` | ✅ | L41–46；`localId` 由 `crypto.randomUUID()` 生成 |
| `dequeueForSend`：取最早 `queued` 标 `sending`；无 queued → `null` | ✅ | L52–61；单测 L63–88 |
| `markStatus`：按 `localId` 不可变更新状态 | ✅ | L67–75；单测 L106–112 验证原数组不变 |
| `removeQueued`：仅移除 `status === "queued"` 的匹配项 | ✅ | L80–84；单测 L91–104（含 sending / missing 不变） |
| `clearQueue()` 返回 `[]` | ✅ | L89–91；单测 L114–116 |
| 测试：满 5 返回 full | ✅ | 单测 L39–43 |
| 测试：dequeue 最早 queued → sending | ✅ | 单测 L63–77 |
| 测试：removeQueued 只删 queued | ✅ | 单测 L91–104 |
| `sending/sent/failed` 不计入 queued 上限（设计 §4.1） | ✅ | `countQueued` 仅 filter `queued`；单测 L45–61 验证 sending 不占名额 |
| 全局：`CHAT_SEND_QUEUE_MAX=5` | ✅ | 常量与单测断言一致 |
| 全局：本 Task 不改 `page.tsx` | ✅ | Task 3 仅新增 `web/src/lib/chatSendQueue.*`；工作树中 `page.tsx` 变属 Task 4 并行改动，不计入 Task 3 交付 |
| 全局：不要求 commit | ✅ | 报告声明未 commit |
| 注释 `@author 赵振明` + 东八区时间 | ✅ | 两文件头注释 `2026-07-30 14:48:53`；各 export 函数有方法注释 |

**设计文档对齐摘要：**

- §4 队列项 `{ localId, text, status }` 四态 ✅  
- §4.1 队列满拒绝入队 ✅（`enqueue` 返回 `full`，UI 提示留 Task 4）  
- §4.3 / §7 仅 `queued` 可删除出队 ✅（`removeQueued`）  
- §8 发送失败标 `failed`、不堵后续 ✅（`markStatus` 支持；`dequeueForSend` 只取 `queued`，逻辑上不会 blocked）  

---

## Strengths

1. **纯函数 + 不可变更新**：所有 API 返回新数组/新对象，不 mutate 入参；`markStatus` 单测显式断言原 `items` 仍为 `queued`，利于 React `setSendQueue` 集成。
2. **上限语义正确且经测试锁定**：仅 `queued` 计入 `CHAT_SEND_QUEUE_MAX`，与 design「1 条在飞 + N 条排队」模型一致；避免 `sending` 占名额导致无法继续入队的错误实现。
3. **接口与 brief/plan 代码块 1:1 对齐**：无擅自增删 export；Task 4 可直接 `setSendQueue(d.rest)`、`sendText(head.text)`，报告中的集成提示准确。
4. **TDD 路径清晰**：8 项单测覆盖 brief 三步要求的核心断言；`seedQueued` helper 减少重复样板。
5. **测试跑法务实**：web 无 vitest/jest 时选用 `node --experimental-strip-types --test`，审查者复跑 **8/8 PASS**；`npx tsc --noEmit` **PASS**。
6. **范围克制**：仅 2 个新文件，无后端/ChatPage 越界改动，符合 Task 3 边界。
7. **注释规范**：文件头与方法级注释齐全，符合仓库 `@author 赵振明` 要求。

---

## Issues

### Critical

*无。* 导出契约、上限语义、FIFO 出队、queued-only 删除均符合 brief 与设计 §4 / §8。

### Important

*无阻塞项。* 下列为 Task 4 集成时应知悉的行为，不构成 Task 3 Fail：

1. **`enqueue` 不拒绝 trim 后空串**  
   `"   "` 会入队为 `{ text: "", status: "queued" }`。报告已说明由 ChatPage 调用前拦截；纯函数层未校验属可接受分工，但 Task 4 `onSubmit` 必须在 `enqueue` 前 `trim` 并 return。

2. **`dequeueForSend` 的 `rest` 保留全量历史项**  
   `sending` / `sent` / `failed` 仍留在数组中，仅状态变更。与设计一致（气泡需对应 localId），Task 4 需在 UI 层管理展示/清理策略，避免 `sendQueue` 无限增长——属集成职责，非本 Task 缺陷。

### Minor

1. **测试覆盖小缺口（非 brief 强制项）**  
   - 未单测 `enqueue` 的 `text.trim()` 行为（如 `"  hello  "` → `"hello"`）。  
   - 未单测 `sent` / `failed` 不计入上限（仅测了 `sending`）。  
   - 未单测「存在 `failed` 项时 `dequeueForSend` 仍取下一 `queued`」（design §8「不堵死后续」的逻辑保障，建议 Task 4 联调或补 1 条断言）。

2. **测试文件 `@ts-nocheck`**  
   为 Node `--test` + `.ts` 扩展名导入的 pragmatic workaround，牺牲测试侧类型检查；可接受，后续若引入 vitest 可移除。

3. **`markStatus` 对未知 `localId` 静默 no-op**  
   返回原数组副本语义（map 无匹配）；brief 未要求报错，Task 4 调用方应保证 id 有效。

4. **Node 运行警告**  
   `node --test` 输出 `MODULE_TYPELESS_PACKAGE_JSON`（web 未设 `"type": "module"`）；不影响结果，可选在 `package.json` 增加 `"test"` script 便于 CI/开发者发现（非 Task 3 必须）。

5. **`crypto.randomUUID()` 环境依赖**  
   Next.js 客户端与现代 Node 均支持；极旧浏览器非本期目标，与项目栈一致。

---

## Assessment

**Task quality: Approved**

Task 3 完整实现 brief 规定的 `chatSendQueue` 纯函数模块：常量、类型、五个 export 函数签名与行为均匹配；单测覆盖 brief 三步要求（满员、FIFO 出队、sending 不占名额、removeQueued 语义、不可变更新、clearQueue）；静态检查与单测均通过。未触碰 `page.tsx`、未 commit，符合全局硬约束。

**Task 4 前置条件已就绪：** 可直接 `import { enqueue, dequeueForSend, markStatus, removeQueued, clearQueue, CHAT_SEND_QUEUE_MAX } from "@/lib/chatSendQueue"`（或相对路径）接入状态机；注意空串拦截与 `rest` 数组生命周期管理。

**Spec ✅ | Quality Approved**

---

## 审查者验证

```powershell
# web/ 目录
node --experimental-strip-types --test src/lib/chatSendQueue.test.ts
# pass 8 / fail 0

npx tsc --noEmit
# exit 0
```

**Git 状态（Task 3 范围）：**

- `?? web/src/lib/chatSendQueue.ts`
- `?? web/src/lib/chatSendQueue.test.ts`
- `web/src/app/chat/page.tsx` 有并行修改（`M`），不属于 Task 3 交付物
