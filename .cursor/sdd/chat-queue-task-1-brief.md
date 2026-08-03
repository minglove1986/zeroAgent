### Task 1: 鍚庣 cancel_pending_cards + dismiss-card + supersede

**Files:**
- Modify: `src/app/modules/conversation/runtime.py`锛坄has_pending_required_card` 闄勮繎锛?- Modify: `src/app/api/v1/messages.py`锛坄MessageSend`銆乣send_message`銆佹柊澧炶矾鐢憋級
- Test: `tests/test_dismiss_card.py`锛堟柊寤猴級
- Modify: `docs/01-浜у搧闇€姹?API鎺ュ彛瑙勮寖.md` 搂10

**Interfaces:**
- Consumes: `MessageCard`锛宍has_pending_required_card`锛岀幇鏈?`fail`/`ok`/`get_actor`
- Produces:
  - `async def cancel_pending_cards(db, *, conversation_id: str, card_id: str | None = None) -> list[str]`
  - `POST /api/v1/messages/dismiss-card` 鈫?`{ dismissed_ids: string[] }`
  - `MessageSend.supersede_pending_card: bool = False`

- [ ] **Step 1: 鍐欏け璐ュ崟娴?*

鍒涘缓 `tests/test_dismiss_card.py`锛堝鐢?`test_message_sse.py` 鐨?client fixture / `_parse_sse` 妯″紡锛涘彲澶嶅埗 fixture锛夛細

```python
"""dismiss-card / supersede_pending_card銆?
@author 璧垫尟鏄?@date <涓滃叓鍖哄疄鏃?
"""

@pytest.mark.asyncio
async def test_send_blocked_without_supersede(client):
    # 鍚岀幇鏈夛細璇峰亣瑙﹀彂鍗″悗鐩存帴 send 鈫?42213
    ...

@pytest.mark.asyncio
async def test_supersede_allows_send_and_cancels_card(client):
    conv = await client.post("/api/v1/conversations", json={"title": "璇峰亣"})
    cid = conv.json()["data"]["id"]
    await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "鎴戣璇峰亣"})
    ok = await client.post(
        "/api/v1/messages/send",
        json={
            "conversation_id": cid,
            "content": "鏀归棶鍒殑",
            "supersede_pending_card": True,
        },
    )
    assert ok.status_code == 200
    detail = await client.get(f"/api/v1/conversations/{cid}")
    pending = detail.json()["data"].get("pending_cards") or []
    assert pending == []

@pytest.mark.asyncio
async def test_dismiss_card_idempotent(client):
    conv = await client.post("/api/v1/conversations", json={"title": "璇峰亣"})
    cid = conv.json()["data"]["id"]
    first = await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "鎴戣璇峰亣"})
    # 浠?SSE 鍙?card_id锛屾垨 dismiss 鐪佺暐 card_id
    r1 = await client.post(
        "/api/v1/messages/dismiss-card",
        json={"conversation_id": cid},
    )
    assert r1.status_code == 200
    assert len(r1.json()["data"]["dismissed_ids"]) >= 1
    r2 = await client.post(
        "/api/v1/messages/dismiss-card",
        json={"conversation_id": cid},
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["dismissed_ids"] == []
```

- [ ] **Step 2: 璺戞祴纭澶辫触**

Run: `& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_dismiss_card.py -v --tb=short`  
Expected: FAIL锛堣矾鐢?瀛楁涓嶅瓨鍦級

- [ ] **Step 3: 瀹炵幇 `cancel_pending_cards`**

鍦?`runtime.py`锛?
```python
async def cancel_pending_cards(
    db: AsyncSession,
    *,
    conversation_id: str,
    card_id: str | None = None,
) -> list[str]:
    """灏?pending 鍗℃爣涓?cancelled锛涜繑鍥炲疄闄呬綔搴熺殑 id 鍒楄〃銆?""
    stmt = select(MessageCard).where(
        MessageCard.conversation_id == conversation_id,
        MessageCard.status == "pending",
    )
    if card_id:
        stmt = stmt.where(MessageCard.id == card_id)
    rows = list((await db.execute(stmt)).scalars().all())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ids: list[str] = []
    for row in rows:
        row.status = "cancelled"
        row.submitted_at = now
        row.result = json.dumps(
            {"dismissed": True, "reason": "user_supersede"},
            ensure_ascii=False,
        )
        ids.append(row.id)
    if ids:
        await db.commit()
    return ids
```

- [ ] **Step 4: 瀹炵幇 API**

`messages.py`锛?
```python
class MessageSend(BaseModel):
    conversation_id: str
    content: str
    supersede_pending_card: bool = False

class DismissCardBody(BaseModel):
    conversation_id: str
    card_id: str | None = None
```

`send_message` 涓浛鎹?42213 鍧楋細

```python
if await has_pending_required_card(db, body.conversation_id):
    if body.supersede_pending_card:
        await cancel_pending_cards(db, conversation_id=body.conversation_id)
    else:
        return JSONResponse(
            status_code=422,
            content=fail(42213, "pending required card; submit card-action first"),
        )
```

鏂板锛?
```python
@router.post("/messages/dismiss-card")
async def dismiss_card(body: DismissCardBody, request: Request, db: AsyncSession = Depends(get_db)):
    actor = get_actor(request)
    conv = await db.get(Conversation, body.conversation_id)
    if conv is None:
        return JSONResponse(status_code=404, content=fail(40401, "conversation not found"))
    if conv.user_id != actor.user_id and not is_platform_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "forbidden"))
    dismissed = await cancel_pending_cards(
        db, conversation_id=body.conversation_id, card_id=body.card_id
    )
    return ok({"dismissed_ids": dismissed})
```

`retry` 璺緞鑻ヤ篃妫€鏌?42213锛氫繚鎸佸師鏍凤紙閲嶈瘯涓?supersede锛夛紝闄ら潪浜у搧瑕佹眰鈥斺€?*鏈湡涓嶆敼 retry**銆?
- [ ] **Step 5: 鏇存柊 API 瑙勮寖**

鍦?搂10 琛ㄦ牸澧炲姞 `POST /messages/dismiss-card`锛沗MessageSend` 澧炲姞 `supersede_pending_card`锛?2213 璇存槑锛氭湭 supersede 鏃朵粛杩斿洖銆?
- [ ] **Step 6: 璺戞祴閫氳繃**

Run: 鍚屼笂 pytest  
Expected: PASS锛涘苟璺?`tests/test_message_sse.py::test_send_blocked_when_pending_required_card` 浠?PASS銆?
- [ ] **Step 7: Commit锛堜粎鐢ㄦ埛瑕佹眰鏃讹級**

```bash
git add src/app/modules/conversation/runtime.py src/app/api/v1/messages.py tests/test_dismiss_card.py "docs/01-浜у搧闇€姹?API鎺ュ彛瑙勮寖.md"
git commit -m "feat: dismiss pending cards and supersede on send"
```

---
