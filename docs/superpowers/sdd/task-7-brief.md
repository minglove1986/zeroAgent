# Task 7 Brief

### Task 7: CHECKPOINT + 回归

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`

- [ ] **Step 1: 跑回归**

```powershell
cd D:\HermesWork\zeroAgent
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_kb_admin_api.py tests/test_kb_d13_search.py tests/test_document_ingest.py -q
```

Expected: 全绿

- [ ] **Step 2: 更新 CHECKPOINT**  
  当前断点 = KB 管理闭环第一刀 B 已完成；下一步 = QA/hit_rate 流水线或拖拽/URL  

- [ ] **Step 3: 全量 pytest（可选但推荐）**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest -q
```

---
