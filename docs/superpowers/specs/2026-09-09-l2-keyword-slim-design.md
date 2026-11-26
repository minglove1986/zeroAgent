# L2 关键词瘦身与可删种子设计

> 状态：已实现（待热更/迁移验收）  
> 日期：2026-09-09  
> 作者：赵振明  
> 成功标准：**宁可漏给 L3，优先消灭误伤**；L2 只保留几乎不可能误判的规则。

## 1. 背景与问题

当前 `DEFAULT_SEED`（`src/app/modules/intent/l2_seed.py`）大量使用短泛化词 + `contains`，L2 高置信短路会误伤：

- 文档类：`总结` / `不合理` / `审查` 等任意包含即 `doc_analyze`
- 元追问：`从哪里` / `你刚才` / `为什么说` 等强制 `chitchat`
- 搜人动词：`看看` / `查一下` + 2–4 汉字误当人名
- 请假短词：`年假有几天` 等咨询句可能直出请假卡
- 管理端：系统种子禁删，与「运维可删、恢复默认可找回」诉求冲突

## 2. 产品裁定

| 项 | 裁定 |
|---|---|
| 策略 | 方案 2：词表瘦身 + 匹配门禁 |
| 成功标准 | A：宁可少短路、多走 L3 |
| 系统种子删除 | 允许软删；「恢复默认」按当前 `DEFAULT_SEED` 全量重建（已删种子会回来） |
| 文档 / 搜人默认种子 | 清空；分类与规则函数可保留供运营自加 |
| 请假 | 短词仅作**线索**；仅办理金句（或等价办理门禁）才 L2 出卡 |
| 自定义短语 | 不动；运营自加短词自担误伤 |
| 不做 | 多租户、任意正则、内容审核式拦截、本轮不接附件上下文门禁 |

## 3. 默认种子（目标形态）

### 3.1 `explicit_kb`（保留 9 条）

| phrase | match_mode | priority |
|---|---|---|
| 查询知识库 | contains | 10 |
| 检索知识库 | contains | 10 |
| 查一下知识库 | contains | 10 |
| 查知识库 | contains | 10 |
| 知识库里找 | contains | 20 |
| 知识库中找 | contains | 20 |
| 知识库里搜索 | contains | 20 |
| 知识库中搜索 | contains | 20 |
| 知识库搜索 | contains | 20 |

**删除**：`在知识库`、`从知识库`（弱口令，易误伤）。

### 3.2 `leave`

**线索短词**（**不入库**；`LEAVE_CLUE_PHRASES` 常量，供 `leave_intent_allowed` / 否定）：

- 请假、休假、年假、调休、事假、病假

**办理金句**（入库 `leave`，`priority=10`）：

- 我要请假、我想请假、帮我请假、申请请假、请个假、请一天假
- 我要休年假、申请年假、我要调休、申请调休、我要休病假、请病假、请事假

**已从种子剔除（重复/非金句）**：线索短词；`提交请假`/`办理请假`（与申请请假近义）；`请两天假`/`请三天假`（天数枚举）；meta 的 `我没让你总结`/`我没让你概括`（已被 `我没让你` 覆盖）。

咨询口吻对齐 `policy._CONSULT_CUES`：  
`怎么`、`如何`、`制度`、`规定`、`咨询`、`了解`、`问一下`、`政策`。

否定句仍走现有 `leave_intent_allowed`。

### 3.3 `meta_reply`（仅明确纠正）

| phrase | priority |
|---|---|
| 我没让你 / 我没有让你 / 不是让你 / 我没叫你 | 5 |
| 不要总结 / 别总结 / 不要概括 / 别概括 | 5 |
| 别帮我总结 / 不要帮我总结 / 别再总结 | 5 |

**勿入库**（已被短句 contains 覆盖）：`我没让你总结`、`我没让你概括`。

**删除全部来源/元追问弱词**：`从哪里`、`从哪儿`、`怎么知道`、`为什么说`、`你为什么`、`资料从哪`、`你怎么知道`、`我怎么是`、`为什么叫我`、`你刚才`、`刚才你说`、`哪里获取`、`什么地方获取`。

### 3.4 `doc_dump` / `doc_summarize` / `doc_critique`

默认种子 **`[]`**。  
`_match_doc_analyze` 逻辑可保留：运营自加短语时仍可命中。

### 3.5 `person_search_verb`

默认种子 **`[]`**。  
人名检索主要依赖人名词典 `match_lexicon_in_text`；无动词种子则人物正则不装配有效 alt（或跳过该分支）。

## 4. 匹配顺序（`match_l2_rules`）

1. `explicit_kb` → `kb_lookup`  
2. `leave` 办理金句（+ 非否定 + 非咨询）→ `ask_user_form`  
3. `meta_reply` → `chitchat`  
4. `_match_doc_analyze`（默认可空）  
5. 人名词典 → `kb_lookup`  
6. `person_search` 正则（默认可跳过）  
7. 未命中 → `None` → L3  

## 5. 系统种子可删与恢复默认

| 操作 | 行为 |
|---|---|
| DELETE | **取消**「`origin=system` 禁止删除」；自定义与系统种子均可软删 |
| 前端 Tag / 编辑弹窗 | 全部短语可删（二次确认）；去掉 `isL2KeywordDeletable` 对 system 的拦截，或改为恒 true |
| 恢复默认 | 按当前代码 `DEFAULT_SEED`：已有 `seed_code` 行恢复 phrase/mode/priority/enabled 并清除 `deleted_at`；缺失的种子插入；**已从 DEFAULT_SEED 移除的旧系统种子**应软删或禁用，避免残留误伤 |
| 自定义行 | 恢复默认不删除、不改写 `origin=custom` |

部署/迁移：一次同步任务把库中系统种子对齐新 `DEFAULT_SEED`（瘦身删除项必须从运行时 catalog 消失）。

## 6. 金样例验收（L2 only）

| 输入 | 期望 |
|---|---|
| `查知识库：差旅报销` | `kb_lookup` |
| `我要请假` / `帮我请假明天一天` / `申请年假` | `ask_user_form` |
| `别总结赵世龙的简历` / `别帮我总结…` / `我没让你总结…` | `chitchat` |
| `年假有几天` / `请假制度是什么` | L2 不命中 |
| `总结赵世龙的简历` / `这个方案不合理` | L2 不命中 |
| `你怎么知道的` / `刚才你说我是谁` | L2 不命中 |
| `看看天气` / `查一下张三`（无人名词典） | L2 不命中 |
| 软删系统种子「我要请假」后同句 | 不命中 leave；恢复默认后再命中 |

## 7. 测试变更要点

- `test_l2_negation_rules`：正向「总结…」改为 **L2 不命中**（不再断言 `doc_analyze`）  
- `test_chat_routing_hotfix.test_meta_reply_is_l2_chitchat`：弱元追问改为 **L2 不命中**；另补纠正金句仍命中  
- `test_l2_catalog_cache`：断言不再依赖「总结」等已删种子  
- 新增：请假金句命中 / 短词咨询不命中 / 系统种子可删再恢复  
- API：DELETE system 种子期望成功（替换原 400）

## 8. 落点文件（实现时）

- `src/app/modules/intent/l2_seed.py` — 重写 `DEFAULT_SEED`  
- `src/app/modules/intent/rules.py` — leave 办理门禁；person 空动词跳过  
- `src/app/modules/intent/policy.py` — 必要时导出/复用咨询与办理判定  
- `src/app/modules/intent/l2_catalog_store.py` — 允许删系统种子；强化 `reset_default_seeds` 对齐瘦身  
- 迁移或启动同步 — 系统种子与 `DEFAULT_SEED` 对齐  
- `admin-web/.../l2-keywords/deletable.ts` + `page.tsx` — 系统种子可删  
- 相关单测如上  

## 9. 风险与应对

| 风险 | 应对 |
|---|---|
| L3 调用量上升 | 接受（标准 A） |
| 运营自加短词误伤 | 管理端 hint + 试跑 |
| 恢复默认覆盖系统种子手改 | 保持现语义，文案写清 |
| 旧库残留已删种子 | 同步任务强制软删/禁用不在 `DEFAULT_SEED` 的 system 行 |

## 10. 非目标

- 本轮不为 `doc_*` 接附件/文档上下文门禁（TurnState 尚无附件字段）  
- 不把 L2 改造成内容安全审核  
- 不改 L3 prompt 大结构（仅随测例调整期望）
