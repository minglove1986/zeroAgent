### Task 2: postSse 鏀寔 AbortSignal

**Files:**
- Modify: `web/src/lib/sse.ts`
- Test: 鍙€夋墜宸ワ紱鑻ユ湁鍓嶇鍗曟祴妗嗘灦鍒欏姞锛屽惁鍒欑敤 Chat 鑱旇皟楠屾敹

**Interfaces:**
- Consumes: 鐜版湁 `postSse(path, body, onEvent)`
- Produces: `postSse(path, body, onEvent, options?: { signal?: AbortSignal })`锛沘bort 鏃舵姏鍑?`DOMException`/`Error` name=`AbortError`

- [ ] **Step 1: 鏀圭鍚嶅苟浼犲叆 fetch**

```typescript
export async function postSse(
  path: string,
  body: unknown,
  onEvent: SseHandler,
  options?: { signal?: AbortSignal },
): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    cache: "no-store",
    signal: options?.signal,
  });
  // ... 璇绘祦寰幆涓嶅彉锛涜嫢 signal abort锛宺eader.read 浼氭姏 AbortError锛屽悜涓婃姏鍑?}
```

- [ ] **Step 2: 纭鎵€鏈夎皟鐢ㄦ柟鍏煎**锛堢 4 鍙傛暟鍙€夛紝鐜版湁 `postSse(a,b,c)` 鏃犻渶鏀癸級

- [ ] **Step 3: Commit锛堜粎鐢ㄦ埛瑕佹眰鏃讹級**

---
