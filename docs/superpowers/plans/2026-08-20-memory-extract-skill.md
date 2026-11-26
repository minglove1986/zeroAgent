# 记忆抽取整块 Skill Implementation Plan

> **For agentic workers:** 按 Task 顺序 TDD；本会话由主 Agent 直接执行。

**Goal:** 旁路 `memory_candidate` + 一整块记忆抽取 Skill；Catalog 扩字段零改代码；废止按字段堆规则驱动即时入队。

**Architecture:** chitchat 主路径不变；`memory_signal` 标注 candidate；scheduler 立即入队；`extract_skill` 门面跑 Catalog→LLM→落库。

**Tech Stack:** FastAPI / Celery / pytest / 现有 intent funnel

## Global Constraints

- 单租户；无 OpenIM；抽取不阻塞 SSE  
- L3 契约字符串不因个案无限膨胀（信号用后处理）  
- `@author 赵振明`；时间东八区实时  

---

### Task 1: memory_signal + 单测

**Files:**
- Create: `src/app/modules/intent/memory_signal.py`
- Test: `tests/test_memory_candidate_signal.py`
- Modify: `src/app/modules/intent/funnel.py`（分类后 annotate）
- Modify: `src/app/modules/intent/l3_fixtures.py`（contact fixture 带 feature）

- [ ] 测试：邮箱自称 → candidate；纯天气 → 否；fixture contact → 含 feature  
- [ ] 实现 annotate + catalog 词元匹配  

### Task 2: extract_skill 门面 + scheduler 即时

**Files:**
- Create: `src/app/modules/memory/extract_skill.py`
- Modify: `src/app/modules/memory/extract_scheduler.py`
- Modify: `src/app/workers/tasks/extract_memories.py`
- Modify: `src/app/modules/conversation/subgraphs/memory_schedule.py`
- Test: `tests/test_memory_extract_whitelist.py`

- [ ] 即时条件改为 explicit | memory_candidate，不再依赖 rule_hit  
- [ ] Celery 调 Skill 门面  

### Task 3: 清理字段硬编码叙事 + 保留格式兜底

**Files:**
- Modify: `src/app/modules/memory/service.py`
- Modify: `tests/test_memory_extract_whitelist.py`

- [ ] 注释标明格式兜底仅 Mock/失败；扩展靠 Catalog+LLM  
- [ ] 调整测试与 scheduler 用例  

### Task 4: 人格禁止空口已记录

**Files:**
- Modify: `src/app/modules/system/persona_seed.py`
- Test: 轻量断言种子文案含约束（或既有 persona 测）

### Task 5: 全量相关测 + CHECKPOINT

- [ ] pytest 相关文件全绿  
- [ ] 更新 CHECKPOINT  
