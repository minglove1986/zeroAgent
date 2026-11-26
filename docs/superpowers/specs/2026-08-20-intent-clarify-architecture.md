# 意图链路七项短板修复（架构规格）

> **日期**：2026-08-20 11:46:59（东八区）  
> **状态**：自我审核已修订，待用户确认  
> **作者**：赵振明  
> **目标**：仅针对 7 项现状短板；不扩展无关能力  
> **边界**：澄清在漏斗层；Plan-Execute **不做**意图闲聊确认  
> **实现拆分**：P0 / P0.5 / P1 分三份实现计划，禁止一张计划吞七项  

---

## 0. 架构硬约束

1. 意图标签 ≠ UI：下游由 `slots.form` / `route.kind` / `slots.agent_id|skill_id` 决定。  
2. `route_clarify` 管「假设对不对 / 路怎么走」；业务字段卡管「字段怎么补」。  
3. 不确定：澄清或安全降级；**无 `slots.form` 禁止出业务表单卡**。  
4. 守卫进 L2 词表 + `intent/policy.py`；**禁止**再往 `_L3_SYSTEM` 堆个案。  
5. PE 只执行已成立任务，不猜意图。

---

## 1. 短板 → 对策（一一对应）

### ① `ask_user_form` ≈ 请假

| | |
|---|---|
| **问题** | 意图一到下游就请假卡，误判放大。 |
| **对策** | `ask_user_form` =「需要表单」；**出卡前置条件**：`slots.form` 非空且已注册。本期仅注册 `leave` → 请假类型卡。无 form / 未注册 form → **不得** `route.kind=ask_form`，改 `chitchat`（feature: `ask_form_no_form`）。 |
| **落点** | L2 leave 命中必须写 `slots.form=leave`；`intent_to_route` / `_ask_form_node` 双闸；L4 `policy.allow_ask_form`。 |
| **验收** | 联系方式句不出请假卡；「我要请假」L2 仍出请假类型卡。 |

### ② 模糊时只「问路径」、不「问意图」

| | |
|---|---|
| **问题** | 非 kb/多助手时中低置信多半闲聊；缺「您是不是想××」。 |
| **对策（本期拍死范围）** | 仅做两类假设确认（仍用 `route_clarify`，D33 不经 `ask_user`）： |
| | **A. 中置信 `kb_lookup`**：title/body「您是不是想查「{query}」？」；options：`kb_lookup`=是，去检索 / `chitchat`=否，随便聊聊。（复用现有 `clarify_kind=kb_confirm`，**只改文案**，不新增 kind，降低改动面。） |
| | **B. 中置信 leave 办理假设**：当文本含 leave 词表线索、且置信中档、尚未直通时：`clarify_kind=intent_confirm`，文案「您是不是要请假？」；options：`confirm_leave`=是 / `chitchat`=否。选「是」→ card-action 后续跑时注入 `slots.form=leave` 并走请假卡或等价 ask_form 路径。 |
| | **明确不做（移出本期）**：「办理 vs 咨询」三选项卡 → **P1**，避免无触发条件时乱弹。 |
| **落点** | `funnel` 中置信分支；`build_route_clarify_card`；`stream_after_card_action` 增加 `confirm_leave`。不改 PE。 |
| **验收** | 中置信查库类 → 出现「您是不是想查…」；中置信偏请假且未直通 → 「您是不是要请假？」；低置信仍闲聊不问。 |

### ③ 开放意图输入几乎没有

| | |
|---|---|
| **问题** | 澄清卡只有封闭 chips。 |
| **对策** | 仅 `type=route_clarify` 增加可选字段 `intent_text`（单行/多行均可，**≤200 字**）。UI：**有文本则禁用/清空选项**（互斥）。 |
| | **提交**：`card-action` payload：`{ "action": "submit", "form": { "intent_text": "..." } }`（可无 selected_option_ids）。服务端拼装续跑内容： |
| | `原问题：{meta.original_user_content}\n用户补充意图：{intent_text}` |
| | 然后走与 send 同构的 Turn Graph；`suppress_route_clarify=true` 传入漏斗，本轮 L4 **禁止**再产出 `route_clarify`。 |
| | **空文本 + 无选项**：422，提示须选题或填写意图。 |
| **落点** | `build_route_clarify_card` 写入 `fields` + `meta.original_user_content` + `meta.allow_free_intent`；runtime 续跑；funnel 认 suppress。 |
| **验收** | 输入「帮我查差旅标准」提交 → 可检索/进 Agent；本轮不再弹路由澄清卡。 |

### ④ 退出澄清产品语义不完整

| | |
|---|---|
| **问题** | dismiss API 有，UI/心智不统一。 |
| **对策** | 路由卡与业务卡统一文案「取消」：调用 `POST /messages/dismiss-card`，**不**触发 card-action 续跑、**不**自动 PE。Composer placeholder：「可直接发消息继续（将跳过当前卡）」——与现网 `supersede_pending_card` 一致。 |
| | **用词**：UI 只用「取消」，不用「跳过续跑」，避免与 ③ 的提交续跑混淆。 |
| **落点** | `web/chat` 所有 `pendingCard` 展示取消；已有请假取消则对齐文案。 |
| **验收** | 任意 pending 卡可取消；取消后无 SSE 续跑；可继续 send。 |

### ⑤ L3 仍是提示词分类器

| | |
|---|---|
| **问题** | 契约在 prompt；案例不能像 L2 运营。 |
| **对策** | • `_L3_SYSTEM` **冻结为短契约**（已有含义/下游/禁止）；新增个案**禁止**改此字符串扩写 |
| | • P0：扩展代码内 `l3_fixtures`（联系方式→chitchat、否定请假→chitchat、纠正总结→chitchat 等）+ 单测 |
| | • P1：若需运营再上管理端；**P0 不上 DB/管理端**（范围收口） |
| | • 阈值继续 `get_tau_*`，调参靠测例，不靠改文案 |
| **验收** | 新误判只加 fixture/测；`test_l3_system_contract` 仍通过；prompt 行数不因个案增长。 |

### ⑥ 技能与意图耦合松

| | |
|---|---|
| **问题** | `skill_task` / `call_agent` 常被默默映射成闲聊。 |
| **对策** | |
| | **P0（最小可观测）**：`intent_to_route` 对二者：若 `slots.agent_id` 或会话 `agent_id` 非空 → `handler=agent` 进 PE；否则 → `chitchat` 且 **必须** `features` 含 `skill_unbound`（禁止静默）。系统会话无 Agent 时一律 `skill_unbound`，**不**擅自绑 `SYSTEM_AGENT_ID` 冒充技能命中。 |
| | **P1**：L2/L3/目录对齐产出 `skill_id`，澄清选项可带 skill/agent id。 |
| **验收** | P0：无 agent 时 meta 含 `skill_unbound`；有 agent 时进入 PE 路径（现有 stream 可验证）。 |

### ⑦ 守卫偏打补丁

| | |
|---|---|
| **问题** | 否定正则、请假守卫散落 L3/L4。 |
| **对策** | 新建 `app/modules/intent/policy.py`（名称可微调，须单模块）： |
| | • `allow_ask_form(text, decision) -> bool`（form 槽位 + catalog leave 线索；承接并替换散落的 `leave_intent_allowed` 调用点） |
| | • `suppress_route_clarify` 时强制不得返回 `route_clarify` |
| | • 否定句：优先 L2 `meta_reply` 词表；policy 内**不**再复制一套否定正则（⑦ 与词表单一真相）。若现有 `_LEAVE_NEGATE_RE` 仍需要，**迁入 policy 且 leave 短语来自 catalog**，删 rules 内重复。 |
| **验收** | 无 form 禁卡测例走 policy；L3 不因新守卫扩写。 |

---

## 2. 目标链路

```text
用户句
  → L2（词表可运营）
  → L3（短契约 + fixture）
  → L4 policy（直通 / kb·leave 假设确认 / 禁卡 / 降级 / suppress）
  → route + Turn Graph
       ├─ route_clarify（文案确认 + 可选 intent_text）
       ├─ ask_form（仅 form 已注册）
       ├─ kb / agent PE
       └─ chitchat
  → 取消 = dismiss，用户自行再 send
```

---

## 3. 分期（三份计划）

| 期 | 短板 | 交付物 |
|---|---|---|
| **P0** | ①②④⑦⑤（fixture）⑥（打标） | 解耦出卡；kb/leave 确认文案与 confirm_leave；统一取消；policy；fixture；skill_unbound |
| **P0.5** | ③ | intent_text + 拼装续跑 + suppress |
| **P1** | ⑥加深、⑤管理端（可选）、办理vs咨询 | skill_id 对齐；可选管理端 fixture；办理/咨询卡 |
| **禁止** | — | PE 意图确认；取消自动续跑；无 form 新假表单；P0 做管理端 L3 |

---

## 4. 模块落点

| 模块 | 短板 |
|---|---|
| `route` / `turn_graph` | ①⑥ |
| `funnel` + `policy.py` | ①②⑦③suppress |
| `runtime` 出卡/card-action | ②③ |
| `web/chat` | ③④ |
| `classifier` + `l3_fixtures` | ⑤ |
| API 文档小节（实现时） | ③④ payload |

---

## 5. 总验收清单

1. ① 联系方式 ≠ 请假卡；L2 请假仍可出类型卡。  
2. ② 中置信查库 →「您是不是想查…」；中置信请假假设 →「您是不是要请假？」。  
3. ③（P0.5）intent_text 再路由且不连环澄清；空提交 422。  
4. ④ 取消 = dismiss，无自动续跑，可再 send。  
5. ⑤ 误判进 fixture；契约测通过。  
6. ⑥ 无 agent → `skill_unbound`；有 agent → PE。  
7. ⑦ 禁卡/leave 线索在 policy+catalog。  

---

## 6. 自我审核记录（2026-08-20 11:46:59）

| 检查项 | 发现 | 修订 |
|---|---|---|
| 占位/含糊 | 「办理 vs 咨询」写「可选」未定期次 | **移出本期 → P1** |
| 占位/含糊 | fixture「文件或 DB」 | **P0 仅代码 fixture** |
| 占位/含糊 | leave 确认后「再出卡或直通」 | **定为：是 → 注入 form=leave 再走 ask_form** |
| 一致性 | ② 验收只写查库 | **补请假确认验收** |
| 一致性 | 「取消/跳过」易与续跑混淆 | **UI 统一称「取消」** |
| 一致性 | ⑥ 是否绑 SYSTEM_AGENT | **明确不绑，避免假技能命中** |
| 一致性 | ⑦ 否定正则 vs 词表双真相 | **正则迁 policy 且短语来自 catalog；与 meta_reply 单一运营** |
| 范围 | 七项一张计划过大 | **强制 P0 / P0.5 / P1 三计划** |
| 歧义 | intent_text 与选项同时提交 | **互斥：有文本忽略选项** |
| 歧义 | 空提交 | **422** |
| 缺失 | API/错误 | **写入 ③④；实现时改 API 文档** |
| 缺失 | kb 确认是否新 kind | **不新增，只改 kb_confirm 文案** |

未发现与「PE 不做意图确认」「无 form 不出卡」相冲突的条款。

---

## 7. 结论

七项短板的修复主轴不变：**form 槽位化、L4 假设确认、开放输入再路由、统一取消、fixture 回归、技能可观测路由、守卫进 policy**。  
自我审核后收口了「办理 vs 咨询 / 管理端 L3 / SYSTEM 冒充技能」等易膨胀点，便于按期交付。
