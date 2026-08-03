### Task 4锛氭敹灏?CHECKPOINT + 瑙勬牸鐘舵€?

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`
- Modify: `docs/superpowers/specs/2026-07-27-context-source-boundary-design.md`锛堢姸鎬佹敼涓恒€屽凡鎵瑰噯 / 宸插疄鐜般€嶏級

- [ ] **Step 1: 鍏ㄩ噺鏈垁鍥炲綊**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_context_source_boundary.py tests/test_plan_execute_graph.py tests/test_chat_routing_hotfix.py tests/test_route_clarify_p2.py -q --tb=line
```

Expected: PASS

- [ ] **Step 2: 鏇存柊 CHECKPOINT**

椤堕儴銆屽綋鍓嶆柇鐐广€嶈鐩栦负锛氫笂涓嬫枃鍒嗘爮宸茶惤鍦帮紱涓嬩竴姝ユ柊寮€瀵硅瘽楠岃瘉绉板懠涓庤蹇嗗亸濂姐€? 
搴曢儴銆屾柇鐐规棩蹇椼€嶈拷鍔犱竴鏉★紙涓滃叓鍖哄疄鏃舵椂闂达紱绂佹瀵嗛挜锛夈€?

- [ ] **Step 3: 瑙勬牸鏂囬鐘舵€佹敼涓哄凡瀹炵幇**

---

## Spec coverage锛堣嚜妫€锛?

| 瑙勬牸鏉＄洰 | Task |
|---|---|
| 姣忚疆鍔犺浇闀挎湡璁板繂 / 淇?`_ = memory_access` | Task 2 |
| 韬唤 / 璁板繂 / 鐭蹇?/ 杈圭晫鍒嗘爮 | Task 1鈥? |
| 韬唤浠?users 琛?| Task 1 |
| `memory_access=none` 璺宠繃璁板繂 | Task 1 |
| RAG/鎶€鑳界涓変汉鍓嶇紑 | Task 1鈥? |
| 鏇挎崲鐥囩姸寮?respond/identity guard | Task 2鈥? |
| 娴嬭瘯瑕佺偣 1鈥? | Task 1鈥? + 鐑慨鍥炲綊 |
| CHECKPOINT | Task 4 |

璁板繂鍐欏叆闂搁棬锛氳鏍煎啓銆岃嫢鐜版湁鎶藉彇宸插彧鐪嬬敤鎴峰師璇濆垯涓嶅姩銆嶁€斺€旀湰璁″垝涓嶆敼鎶藉彇銆?

## Placeholder scan

鏃?TBD /銆岀被浼?Task N銆嶅崰浣嶃€?
