# Review package Task 4
## Report summary
# Task 4 鎶ュ憡锛欳hatPage 闃熷垪鐘舵€佹満 + 鍋滄 + supersede + 鐒︾偣  **瀹屾垚鏃堕棿锛堜笢鍏尯锛?*锛?026-07-30 14:55:09   **浣滆€?*锛氳档鎸槑   **鐘舵€?*锛氣渽 宸插畬鎴? ## 鍙樻洿鎽樿  | 鏂囦欢 | 鎿嶄綔 | |------|------| | `web/src/app/chat/page.tsx` | 闃熷垪鐘舵€佹満銆丄bort 鍋滄銆乻upersede銆佺劍鐐规仮澶嶃€乁I | | `web/src/app/globals.css` | `.chat-queue-tag` / `.chat-card-skipped` / `.chat-stopped-hint` / `.send-btn-stop` |  **鏈?commit**锛堟寜绾︽潫锛夈€? ## 瀹炵幇瑕佺偣  1. **鐘舵€?*锛歚streamPhase`锛坄idle|streaming|stopping|draining`锛? `sendQueue`锛沗busy = streamPhase !== "idle"`銆?2. **鍙戦€?*锛歚messages/send` 濮嬬粓甯?`supersede_pending_card: true`锛沗AbortController` 缁?`postSse(..., { signal })`銆?3. **鍏ラ槦**锛氭祦寮忎腑 Enter/鎻愪氦璧?`enqueue`锛堜笂闄?5锛屼粎璁?`queued`锛夛紱鐢ㄦ埛姘旀场鏍囥€屾帓闃熶腑銆嶃€?4. **鍋滄**锛氫富鎸夐挳鍒囥€屽仠姝€嶁啋 `abort`锛沗AbortError` 淇濈暀鍗婃埅鍔╂墜骞舵爣銆屽凡鍋滄銆嶏紝**涓?* toast锛沗settleAfterStream` 鍑洪槦缁彂銆?5. **鍗＄墖**锛氭湁 pending 鏃朵粛鍙緭鍏ワ紱鍙戦€?鍑洪槦鍓嶆湰鍦扮伆鏄俱€屽凡璺宠繃銆嶏紱闅愯棌鎻愪氦鍖恒€?6. **鐒︾偣**锛氬叆闃?鐩村彂娓呯┖鍚庛€乣idle` 鍥炶惤銆佸垏浼氳瘽/鏂板璇濄€佸崱鐗囨彁浜?settle 鍚?`focusComposer()`銆?7. **鍒囦細璇?*锛歚resetStreamSession()`锛坄sessionGenRef++` + abort + `clearQueue`锛夛紝鍏佽娴佸紡涓垏鎹紱`streaming` 绂佺敤閫夋ā涓?retry銆? ## 鎵嬪姩娓呭崟锛堣嚜妫€锛? | # | 鍦烘櫙 | 缁撹 | |---|------|------| | 1 | 娴佸紡涓繛鍙?3 鏉?鈫?涓茶 | 鉁?浠ｇ爜璺緞鍏峰锛堝叆闃?+ settle 鍑洪槦锛?| | 2 | 鍋滄 鈫?闃熼绔嬪埢鍙戯紱鐒︾偣杈撳叆妗?| 鉁?| | 3 | 鍑哄崱鍚庣洿鎺ュ彂瀛?鈫?宸茶烦杩?+ 鏂板洖鍚?| 鉁?supersede + 鏈湴 skipped | | 4 | 鍙戦€佸悗鏃犻渶鐐瑰嚮鍗冲彲閿叆 | 鉁?focusComposer | | 5 | 闃熷垪婊?5 鎻愮ず | 鉁?|  > 鏈仛娴忚鍣ㄥ疄鏈鸿仈璋冿紱閫昏緫涓庤璁″榻愶紝寰呬汉宸ョ偣楠屻€? ## 楠岃瘉  | 椤?| 鍛戒护 | 缁撴灉 | |----|------|------| | 绫诲瀷妫€鏌?| `cd web; npx tsc --noEmit` | 鉁?PASS锛坋xit 0锛?|  ## 椋庨櫓 / 鍏虫敞鐐? 1. **浠呭鎴风 Abort**锛氭湇鍔＄/LiteLLM 鍙兘鐭殏缁х画鐢熸垚锛涘崐鎴煭璁板繂鍙帴鍙楋紙璁捐宸茶瀹氾級銆?2. **鍒锋柊涓㈤槦鍒?*锛氭湰鍦?FIFO 涓嶆寔涔呭寲銆?3. **鍑洪槦涓庡嚭鍗＄珵鎬?*锛氬嚭闃熷墠鏈湴 skip + send supersede锛涗緷璧栨湇鍔＄鏉′欢鏇存柊 `pending鈫抍ancelled`銆?4. **sessionGen**锛氬垏浼氳瘽 abort 鍚庢棫娴?`finally` 涓嶅啀娉甸槦鍒楋紝閬垮厤涓蹭細璇濄€? ## Git  鎸夌害鏉燂細**鏈?commit**銆?
## Diff page.tsx (stat + hunks may be large — key greps below)
 web/src/app/chat/page.tsx | 906 +++++++++++++++++++++++++++++++++++++++-------
 web/src/app/globals.css   | 219 ++++++++++-
 2 files changed, 984 insertions(+), 141 deletions(-)

## Key symbol grep

3:* 支持流式中排队发送、停止生成、supersede pending 卡与焦点恢复。
34:CHAT_SEND_QUEUE_MAX,
36:dequeueForSend,
40:} from "@/lib/chatSendQueue";
45:type StreamPhase = "idle" | "streaming" | "stopping" | "draining";
175:* 将本轮未落库助手气泡标为已停止（保留半截正文）。
243:const [streamPhase, setStreamPhase] = useState<StreamPhase>("idle");
244:const [sendQueue, setSendQueue] = useState<QueueItem[]>([]);
268:const abortRef = useRef<AbortController | null>(null);
269:const sendQueueRef = useRef<QueueItem[]>([]);
270:const streamPhaseRef = useRef<StreamPhase>("idle");
274:const busy = streamPhase !== "idle";
280:sendQueueRef.current = next;
281:setSendQueue(next);
287:function focusComposer() {
301:streamPhaseRef.current = "idle";
302:setStreamPhase("idle");
306:* 本地将指定 pending 卡标为已跳过（服务端由 supersede 作废）。
327:streamPhaseRef.current = streamPhase;
328:}, [streamPhase]);
579:focusComposer();
584:if (streamPhaseRef.current !== "idle") return;
651:focusComposer();
660:* 流结束后：有排队则出队串行发送，否则回到 idle 并聚焦输入框。
674:let next = sendQueueRef.current;
692:const deq = dequeueForSend(next);
699:streamPhaseRef.current = "draining";
700:setStreamPhase("draining");
709:streamPhaseRef.current = "idle";
710:setStreamPhase("idle");
711:focusComposer();
715:* 发起 messages/send（始终 supersede_pending_card）；支持 Abort 与出队续发。
723:streamPhaseRef.current = "streaming";
724:setStreamPhase("streaming");
743:const ac = new AbortController();
756:supersede_pending_card: true,
859:function onStop() {
860:if (streamPhaseRef.current === "idle") return;
861:streamPhaseRef.current = "stopping";
862:setStreamPhase("stopping");
864:focusComposer();
872:const phase = streamPhaseRef.current;
873:const queuedCount = sendQueueRef.current.filter(
876:if (queuedCount >= CHAT_SEND_QUEUE_MAX && phase !== "idle") {
877:setError("最多排队 5 条，请等待或停止后发送");
882:focusComposer();
891:!sendQueueRef.current.some((i) => i.status === "sending");
898:const r = enqueue(sendQueueRef.current, text);
900:setError("最多排队 5 条，请等待或停止后发送");
925:if (!pendingCard || !conversationId || streamPhaseRef.current !== "idle") {
930:streamPhaseRef.current = "streaming";
931:setStreamPhase("streaming");
935:const ac = new AbortController();
1039:if (streamPhaseRef.current !== "idle" || pendingCardRef.current) return;
1042:streamPhaseRef.current = "streaming";
1043:setStreamPhase("streaming");
1046:const ac = new AbortController();
1312:<span className="chat-queue-tag">排队中</span>
1361:<div className="chat-stopped-hint">已停止</div>
1456:<p className="card-block-tip">已跳过</p>
1517:? "输入后 Enter 加入排队…"
1569:? `Enter 排队${
1570:sendQueue.filter((i) => i.status === "queued").length
1571:? `（${sendQueue.filter((i) => i.status === "queued").length}）`
1580:onClick={onStop}

## CSS related

900:.chat-queue-tag {
912:.chat-queue-tag.is-failed {
917:.chat-card-skipped {
923:.chat-stopped-hint {

Full diffs: chat-queue-task-4-page.diff , chat-queue-task-4-css.diff


## Post-fix key greps
39:removeQueued,
661:* 取消仍为 queued 的排队项：调用 removeQueued，并移除对应乐观用户气泡。
665:function onRemoveQueued(localId: string) {
667:const next = removeQueued(before, localId);
686:* 失败项重试：标回 queued；空闲则立即泵送，流式中则等待 settle 出队，不堵后续。
690:function onRetryFailedQueue(localId: string) {
1184:setError(err instanceof Error ? err.message : "重试失败");
1389:aria-label="取消排队"
1390:onClick={() => onRemoveQueued(item.queueLocalId!)}
1404:aria-label="重试发送"
1405:onClick={() => onRetryFailedQueue(item.queueLocalId!)}
1407:重试
1503:title="重试"

