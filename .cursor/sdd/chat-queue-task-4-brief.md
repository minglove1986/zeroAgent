### Task 4: ChatPage 闃熷垪鐘舵€佹満 + 鍋滄 + supersede + 鐒︾偣

**Files:**
- Modify: `web/src/app/chat/page.tsx`
- Modify: `web/src/app/globals.css`锛坄.chat-queue-tag` / `.chat-card-skipped` / `.chat-stopped-hint`锛?
**Interfaces:**
- Consumes: `postSse(..., { signal })`銆乣enqueue/dequeue/...`銆乣apiJson` dismiss锛堝彲閫夛紝浼樺厛 send 甯?supersede锛?- Produces: 鍙繛鍙?UI锛涘仠姝紱鐒︾偣鎭㈠

- [ ] **Step 1: 澧炲姞 refs/state**

```typescript
const abortRef = useRef<AbortController | null>(null);
const [sendQueue, setSendQueue] = useState<QueueItem[]>([]);
const [streamPhase, setStreamPhase] = useState<"idle" | "streaming" | "stopping" | "draining">("idle");
// busy 鍙淳鐢燂細streamPhase !== "idle" || sendQueue.some(s => s.status === "sending")
```

- [ ] **Step 2: `focusComposer` 杈呭姪**

```typescript
function focusComposer() {
  requestAnimationFrame(() => {
    textareaRef.current?.focus();
  });
}
```

- [ ] **Step 3: 閲嶆瀯 `sendText`**

- 鎺ユ敹 `text`锛沗setBusy`/`streamPhase` 绠＄悊  
- body 澧炲姞 `supersede_pending_card: true`  
- 鍒涘缓 `AbortController`锛宍abortRef.current = ac`锛宍postSse(..., { signal: ac.signal })`  
- catch锛氳嫢 `err.name === "AbortError"` 鈫?褰撳墠 assistant 杩藉姞銆屽凡鍋滄銆嶆彁绀猴紝**涓?*褰撳彂閫佸け璐?toast  
- `finally`锛氭竻 abortRef锛涜嫢闃熷垪鏈?`queued` 鈫?`draining` + `dequeueForSend` + 閫掑綊/`void pumpQueue()`锛涘惁鍒?`idle` + `focusComposer()`  
- 鎴愬姛鍑?card 鏃朵粛 `setPendingCard`锛涗笅涓€杞嚭闃?send 鍥?supersede 浼氫綔搴? 

- [ ] **Step 4: 閲嶆瀯 `onSubmit`**

```typescript
// 浼唬鐮?const text = input.trim();
if (!text || loading) return;
if (sendQueue.filter(i => i.status === "queued").length >= CHAT_SEND_QUEUE_MAX && streamPhase !== "idle") {
  setError("鏈€澶氭帓闃?5 鏉★紝璇风瓑寰呮垨鍋滄鍚庡彂閫?);
  return;
}
setInput("");
focusComposer();
// 涔愯鐢ㄦ埛姘旀场锛堝惈鎺掗槦鏍囪锛?if (streamPhase === "idle" && !sendQueue.some(i => i.status === "sending")) {
  void sendText(text);
} else {
  const r = enqueue(sendQueue, text);
  if (!r.ok) { setError("..."); return; }
  setSendQueue(r.items);
  // items 閲岃拷鍔?user 姘旀场锛屾爣璁?queue
}
```

- [ ] **Step 5: 鍋滄鎸夐挳**

娴佸紡涓富鎸夐挳鏂囨銆屽仠姝€嶏細

```typescript
function onStop() {
  abortRef.current?.abort();
  setStreamPhase("stopping");
  focusComposer();
}
```

- [ ] **Step 6: 瑙ｉ櫎 `pendingCard` 瀵硅緭鍏ョ殑纭**

- 杈撳叆妗?/ 鍙戦€侊細鍏佽鍦ㄦ湁鍗℃椂杈撳叆锛涘彂閫佽蛋 supersede  
- 鍗＄墖鎿嶄綔鍖猴細鑻ユ湰鍦版爣璁?`skipped` 鍒欓殣钘忔彁浜? 
- 鍒囦細璇?/ 鏂板璇濓細`abortRef.current?.abort()`锛沗setSendQueue([])`锛沗setStreamPhase("idle")`  
- `streaming` 鏃剁鐢ㄩ€夋ā涓?retry锛?*鍏佽**鍒囦細璇濓紙鍏?abort+娓呴槦鍒楋級

- [ ] **Step 7: 鍗＄墖鎻愪氦鎴愬姛鍚?`focusComposer()`**

- [ ] **Step 8: 鏍峰紡**

鎺掗槦鏍囩銆佸凡璺宠繃鍗°€佸凡鍋滄 hint 鐢ㄧ幇鏈?chat 鍙橀噺鑹诧紝杞婚噺鍗冲彲銆?
- [ ] **Step 9: 鎵嬪姩楠屾敹娓呭崟**

1. 娴佸紡涓繛鍙?3 鏉?鈫?涓茶鍥炲  
2. 鍋滄 鈫?闃熼绔嬪埢鍙戯紱鐒︾偣鍦ㄨ緭鍏ユ  
3. 璇峰亣鍑哄崱鍚庣洿鎺ユ墦瀛楀彂閫?鈫?鍗°€屽凡璺宠繃銆嶄笖鏂板洖鍚堝紑濮? 
4. 鍙戦€佸悗涓嶇偣杈撳叆妗嗗嵆鍙户缁敭鍏? 
5. 闃熷垪婊?5 鏈夋彁绀? 

- [ ] **Step 10: Commit锛堜粎鐢ㄦ埛瑕佹眰鏃讹級**

---
