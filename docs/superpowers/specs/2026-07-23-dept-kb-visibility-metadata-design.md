# 部门化知识库 · 可见性 · 通用分类 Metadata 方案

> **日期**：2026-07-23 14:51:38（东八区）  
> **状态**：P0–P2 已落地（待浏览器联调）；P3 未做  
> **作者**：赵振明  
> **权威对齐**：单租户（禁 `tenant_id`）；KB 权限**并集** D13；现有 `departments` / `kb_permissions`；意图漏斗设计  

---

## 0. 人话版（先看这段）

要做四件事：

1. **两个部门**：人力资源部、IT 部。  
2. **知识库挂部门 + 公开/部门私有**。  
3. **文档可选多个分类**（跨类文档很常见）——例如同时挂 `人事资料/简历` + `IT资料/架构`；上传至少选一个，其中一个可标为**主分类**。  
4. **Metadata 按主分类（及附属分类）套字段模板**；意图识别时按 **分类（任一命中）+ 字段** 过滤。

举例：问「唐亮是谁」→ 意图=`kb_lookup` + 过滤 `category∈{hr.resume}` + `person_name≈唐亮` → 凡挂了 `hr.resume` 的文档都进候选（即使还挂了别的类）。

---

## 1. 目标与非目标

### 目标

| # | 目标 |
|---|---|
| G1 | 种子：人力资源部、IT 部 |
| G2 | KB：`owner_department_id` + `visibility`（public/department）+ 自动 `kb_permissions` |
| G3 | **文档分类体系**（可配置树）+ 上传多选分类（≥1）+ 主分类 |
| G4 | **通用 Metadata**：多分类关联 + `metadata_json`（由 schema 驱动） |
| G5 | **意图漏斗输出检索过滤条件**；分类过滤用 **OR（任一命中）** |
| G6 | 前端：建库选部门与可见性；上传多选分类与可见性覆盖 |

### 非目标

- 多租户；交集鉴权；外网公开链接  
- 一次做完所有行业分类  
- 用 Metadata 替代全文切块  

---

## 2. 核心设计：分类树 + 多对多 + 字段模板

```text
文档分类 DocCategory（树）
  id / code / name / parent_id / schema_code

字段模板 MetadataSchema
  code / fields[]

文档 Document
  ├─ document_categories[]   ← 多对多（≥1）
  │     category_id
  │     is_primary           ← 有且仅有一个 true（驱动主抽取）
  ├─ metadata_json           ← 合并后的 KV
  └─ visibility_override
```

### 2.1 为什么要多分类

| 场景 | 挂类 |
|---|---|
| 技术岗简历 | `hr.resume` + `it`（或 `it.architecture`） |
| 入职须知里夹运维账号规范 | `hr.onboarding` + `it.runbook` |
| 公司公告兼制度 | `common.notice` + `hr.policy` |

单分类会逼用户「二选一」，检索要么漏、要么硬塞错桶。

### 2.2 种子分类（示例）

| code | 名称 | 建议归属 | schema |
|---|---|---|---|
| `hr` | 人事资料 | dept_hr | —（目录，一般不挂文档） |
| `hr.resume` | 简历库 | dept_hr | `schema_resume` |
| `hr.policy` | 人事制度 | dept_hr | `schema_policy` |
| `hr.onboarding` | 入职材料 | dept_hr | `schema_generic` |
| `it` | IT资料 | dept_it | — |
| `it.runbook` | 运维手册 | dept_it | `schema_runbook` |
| `it.architecture` | 架构文档 | dept_it | `schema_generic` |
| `common.notice` | 公司公告 | 可选 | `schema_notice` |

> **分类与知识库解耦**。KB 可设 `default_category_ids`（数组，上传预勾；用户可改、可加）。

### 2.3 字段模板（Schema Registry）

简历：

```json
{
  "code": "schema_resume",
  "fields": [
    {"key": "person_name", "type": "string", "label": "姓名", "filterable": true},
    {"key": "email", "type": "string", "label": "邮箱", "filterable": true},
    {"key": "years_experience", "type": "number", "label": "年限", "filterable": true},
    {"key": "target_title", "type": "string", "label": "意向岗位", "filterable": true},
    {"key": "expected_city", "type": "string", "label": "城市", "filterable": true},
    {"key": "skills", "type": "string[]", "label": "技能", "filterable": true}
  ]
}
```

制度：`topic` / `keywords` / `effective_date`。  
运维手册：`system_name` / `severity` / `severity`。  
通用：`title` / `keywords`。

### 2.4 多分类下 Metadata 怎么抽

1. **主分类**决定「主 schema」与 UI 摘要优先展示（如简历优先显示姓名）。  
2. **附属分类**的 schema 字段做 **并集合并**进同一份 `metadata_json`（同名字段：主分类优先，附属不覆盖）。  
3. 抽取失败不阻断入库。

约束建议：

- 至少 1 个分类；主分类必填（默认=所选第一个或 KB 默认第一个）。  
- 上传上限建议 ≤5，避免标签爆炸。  
- 只允许挂**叶子分类**（或允许父级但检索时展开子树——第一刀建议只挂叶子）。

### 2.5 文档上存什么

| 存储 | 说明 |
|---|---|
| `document_categories` | `(document_id, category_id, is_primary)` |
| `metadata_json` | 合并后的业务字段 |
| `metadata_status` | pending / ready / failed |
| `visibility_override` | 继承或覆盖 KB |

Milvus（P3）：可冗余 `category_codes`（数组标量）或仍用 MySQL 先缩 `document_id`。

---

## 3. 与意图识别如何配合

```json
{
  "intent": "kb_lookup",
  "query": "唐亮",
  "filters": {
    "category_codes": ["hr.resume"],
    "category_match": "any",
    "metadata": [
      {"key": "person_name", "op": "eq", "value": "唐亮"}
    ]
  },
  "confidence": 0.9,
  "funnel_layer": "L2"
}
```

### 3.1 分类匹配语义

| 模式 | 含义 | 默认 |
|---|---|---|
| `any`（OR） | 文档挂的分类与过滤集合**有交集**即入选 | **是** |
| `all`（AND） | 文档必须同时挂上过滤集合里全部类 | 暂不默认 |

意图只给一个类（如只要简历）时用 `any`：跨类文档只要挂了简历就会进候选——这正是多分类的价值。

### 3.2 规则示例（L2）

| 用户说法 | 意图过滤 |
|---|---|
| 「唐亮是谁 / 找唐亮简历」 | `category any∈{hr.resume}` + `person_name=唐亮` |
| 「差旅报销怎么报」 | `any∈{hr.policy}` + topic/keywords |
| 「Nginx 怎么配」 | `any∈{it.runbook}` + query |
| 「查知识库：…」无类线索 | 不强制 category |

### 3.3 检索流水线

```text
1. 并集算权 → 可访问 kb_ids
2. 按 category_codes + any/all 缩文档集合（经 document_categories）
3. 按 metadata 谓词再缩
4. 非空则仅在这些 document_id 上 hybrid
5. 空则降级：strict / soft（默认，保分类放宽字段）/ none
```

---

## 4. 部门 · 可见性

| visibility | 含义 | 自动权限 |
|---|---|---|
| `public` | **公司内**全员可读 | `role=employee` + 可选主管部门 + 创建者 |
| `department` | 仅归属部门 | `department=owner_department_id` + 创建者 |

- 文档可 `visibility_override`（null=继承 KB）。  
- KB：`default_category_ids`（JSON 数组，上传预勾）。  

种子：`dept_hr` 人力资源部、`dept_it` IT部。

---

## 5. 上传体验

1. 选知识库（部门、可见性、默认分类预勾）  
2. **多选文档分类**（树形勾选；至少 1；指定主分类）  
3. 可选：本篇公开/私有覆盖  
4. 上传 → OSS → Celery：切块 + 按主+附属 schema 抽 Metadata  

库设置示例：「默认分类 = 人事资料-简历」，仍可临时加挂「IT-架构」。

---

## 6. 表结构

### 新增

**`doc_categories`**：`id`, `code`(unique), `name`, `parent_id`, `schema_code`, `sort`, `enabled`  

**`document_categories`**（多对多）：

| 列 | 说明 |
|---|---|
| `document_id` | 文档 |
| `category_id` | 分类 |
| `is_primary` | 是否主分类 |
| UNIQUE(`document_id`,`category_id`) | |
| 约束 | 同一 `document_id` 有且仅有一个 `is_primary=1`（应用层或生成列/触发器保证） |

**`metadata_schemas`**（或代码注册）：`code`, `name`, `fields_json`

### 变更

**`knowledge_bases`**：`owner_department_id`, `visibility`, `default_category_ids`(JSON)  

**`documents`**：`visibility_override`, `metadata_json`, `metadata_status`, `metadata_updated_at`  

> **不要**在 `documents` 上放单个 `category_id`；分类一律走关联表。

---

## 7. API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/departments` | 部门列表 |
| GET | `/api/v1/doc-categories` | 分类树 |
| POST | `/knowledge-bases` | 增部门/可见性/`default_category_ids` |
| POST | `/documents/upload` | `category_ids[]` + `primary_category_id` + `visibility_override` |
| PATCH | `/documents/{id}/categories` | 事后改挂类（P3 可做） |
| GET | `/documents` | 返回 `categories[]`（含 is_primary）、metadata、有效可见性 |

---

## 8. 前端（`/knowledge`）

1. 建库：部门、可见性、默认分类（可多选预勾）。  
2. 上传：**分类多选** + 主分类单选；展示已选标签。  
3. 文档表：多标签展示（主分类高亮）+ Metadata 摘要。  

---

## 9. 鉴权矩阵（读）

| 角色 | public KB | department KB（本部门） | department KB（他部门） |
|---|---|---|---|
| platform_admin | ✅ | ✅ | ✅ |
| 本部门员工 | ✅ | ✅ | ❌ |
| 他部门员工 | ✅ | ❌ | ❌ |

---

## 10. 迁移与兼容

1. Alembic：KB/文档新列 + `doc_categories` + `document_categories`。  
2. 旧 KB：回填 `visibility=public` + `role=employee`。  
3. 旧文档：无分类行；检索不强制 category 时仍可全文命中；可批量补挂。  
4. 种子部门 + 分类树。  

---

## 11. 分期落地

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P0** | 部门 + KB 可见性/归属 + 自动权限 | IT 私有库 HR 不可见 |
| **P1** | 分类树 + **多对多挂类** + 上传多选/主分类 | 一篇文档可挂简历+IT |
| **P2** | Schema 抽取（主+并集）；意图 filters；any 过滤 | 「唐亮是谁」走 hr.resume |
| **P3** | 改挂类、Milvus 标量、手工改 Metadata | 闭环 |

---

## 12. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 挂太多类导致过滤变宽 | 上限 ≤5；UI 提示主分类 |
| 多 schema 字段冲突 | 主分类优先 |
| 旧库无权限 | 回填 public + employee |
| 分类选错过窄 | soft 降级 |

---

## 13. 请确认

1. 同意文档 **多分类（OR 命中）+ 唯一主分类**？  
2. Metadata：**主 schema 优先，附属字段并集合并**？  
3. 意图检索默认降级 **soft**？  
4. 种子分类先要：`hr.resume` / `hr.policy` / `it.runbook` / `it.architecture`？  
5. 公开 = 公司内全员；旧库回填 public + employee；按 **P0→P1→P2** 开工？  

确认后出实现计划并动手。
