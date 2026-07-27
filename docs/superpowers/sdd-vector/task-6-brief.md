### Task 6: CHECKPOINT + 全量回归

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`

- [ ] **Step 1: 更新断点** — 向量完善 DONE；下一步「kb_lookup 接稠密检索 / Hybrid」；启动备忘加：

```powershell
cd D:\HermesWork\zeroAgent\deploy
docker compose --env-file .env --profile full up -d etcd minio-milvus milvus
# MILVUS_URI=http://127.0.0.1:19530
```

- [ ] **Step 2: 全量** — `pytest -q` 期望全绿

- [ ] **Step 3: 对照规格验收清单勾选**

---
