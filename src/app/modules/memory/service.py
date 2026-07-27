"""短期记忆（Redis）与中长期记忆（MySQL）服务。

@author 赵振明
@date 2026-07-22 09:20:23
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.memory import UserMemory

# Redis 不可用时回落进程内缓存（单测 / 无 Redis）
_LOCAL_SHORT: dict[str, list[dict[str, str]]] = {}
SHORT_TTL_SECONDS = 2 * 3600
SHORT_MAX_TURNS = 20


def _redis_client():  # noqa: ANN202
    settings = get_settings()
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def short_key(user_id: str, conversation_id: str) -> str:
    return f"za:shortmem:{user_id}:{conversation_id}"


def append_short_memory(
    *,
    user_id: str,
    conversation_id: str,
    role: str,
    content: str,
) -> None:
    """写入短期会话上下文（TTL 2h）。"""
    item = {"role": role, "content": content}
    key = short_key(user_id, conversation_id)
    client = _redis_client()
    if client is None:
        buf = _LOCAL_SHORT.setdefault(key, [])
        buf.append(item)
        _LOCAL_SHORT[key] = buf[-SHORT_MAX_TURNS:]
        return
    client.rpush(key, json.dumps(item, ensure_ascii=False))
    client.ltrim(key, -SHORT_MAX_TURNS, -1)
    client.expire(key, SHORT_TTL_SECONDS)


def load_short_memory(*, user_id: str, conversation_id: str) -> list[dict[str, str]]:
    key = short_key(user_id, conversation_id)
    client = _redis_client()
    if client is None:
        return list(_LOCAL_SHORT.get(key, []))
    raw = client.lrange(key, 0, -1) or []
    out: list[dict[str, str]] = []
    for line in raw:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


async def list_long_memories(
    db: AsyncSession,
    user_id: str,
    *,
    memory_access: str = "all",
) -> list[UserMemory]:
    """按 Agent memory_access 过滤中长期记忆。"""
    stmt = select(UserMemory).where(
        UserMemory.user_id == user_id,
        UserMemory.deleted_at.is_(None),
        UserMemory.is_archived == 0,
    )
    rows = (await db.execute(stmt)).scalars().all()
    if memory_access == "none":
        return []
    if memory_access == "preference":
        return [r for r in rows if r.memory_type == "preference"]
    if memory_access == "fact":
        return [r for r in rows if r.memory_type == "fact"]
    # all
    return list(rows)


def build_memory_system_prompt(memories: list[UserMemory]) -> str:
    """注入 System Prompt 的用户记忆块（PRD 15.7）。"""
    if not memories:
        return ""
    prefs = [m for m in memories if m.memory_type == "preference"]
    facts = [m for m in memories if m.memory_type == "fact"]
    summaries = [m for m in memories if m.memory_type == "summary"]
    lines = ["# 用户记忆（跨会话）"]
    if prefs:
        lines.append("## 偏好")
        for m in prefs:
            lines.append(f"- {m.memory_key}: {m.memory_value}")
    if facts:
        lines.append("## 事实")
        for m in facts:
            lines.append(f"- {m.memory_key}: {m.memory_value}")
    if summaries:
        lines.append("## 历史摘要")
        for m in summaries[:5]:
            lines.append(f"- {m.memory_value}")
    return "\n".join(lines)


async def upsert_memory(
    db: AsyncSession,
    *,
    user_id: str,
    memory_type: str,
    memory_key: str,
    memory_value: str,
    source: str = "manual",
    confidence: float = 1.0,
) -> UserMemory:
    """同 user+type+key 更新，否则新建。"""
    stmt = select(UserMemory).where(
        UserMemory.user_id == user_id,
        UserMemory.memory_type == memory_type,
        UserMemory.memory_key == memory_key,
        UserMemory.deleted_at.is_(None),
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if row is None:
        row = UserMemory(
            id=f"mem_{uuid.uuid4().hex[:16]}",
            user_id=user_id,
            memory_type=memory_type,
            memory_key=memory_key,
            memory_value=memory_value,
            source=source,
            confidence=confidence,
        )
        db.add(row)
    else:
        row.memory_value = memory_value
        row.source = source
        row.confidence = confidence
        row.updated_at = now
        row.is_archived = 0
    await db.commit()
    await db.refresh(row)
    return row


def parse_auto_extract_rules(text: str) -> list[dict[str, Any]]:
    """MOCK / 轻量规则抽取（含可选 summary）。"""
    found: list[dict[str, Any]] = []
    if "我叫" in text:
        idx = text.find("我叫")
        name = text[idx + 2 : idx + 20].split("，")[0].split("。")[0].split(" ")[0].strip()
        if name:
            found.append(
                {"memory_type": "fact", "memory_key": "name", "memory_value": name}
            )
    if "以后请" in text or "请用" in text or "习惯" in text:
        found.append(
            {
                "memory_type": "preference",
                "memory_key": "style",
                "memory_value": text.strip()[:200],
            }
        )
    if "我是" in text and "部门" in text:
        idx = text.find("我是")
        dept = text[idx + 2 : idx + 40].split("，")[0].split("。")[0].strip()
        if dept:
            found.append(
                {
                    "memory_type": "fact",
                    "memory_key": "department",
                    "memory_value": dept,
                }
            )
    _maybe_append_summary(text, found)
    return found


def _maybe_append_summary(text: str, found: list[dict[str, Any]]) -> None:
    threshold = get_settings().memory_summary_char_threshold
    if len(text) < threshold:
        return
    if any(i.get("memory_type") == "summary" for i in found):
        return
    digest = text.strip().replace("\n", " ")
    if len(digest) > 200:
        digest = digest[:200] + "…"
    found.append(
        {
            "memory_type": "summary",
            "memory_key": "conv_digest",
            "memory_value": digest,
            "confidence": 0.7,
        }
    )


_EXTRACT_SYSTEM = """你是用户记忆抽取器。从用户话语中提取事实(fact)、偏好(preference)；
当对话很长时也可生成一条摘要(summary，memory_key=conv_digest)。
只输出 JSON 数组，不要 Markdown，不要解释。无信息输出 []。
每项字段：memory_type, memory_key, memory_value, confidence(0~1)。
memory_type 只能是 fact、preference 或 summary。"""


def parse_memory_json(raw: str) -> list[dict[str, Any]]:
    """解析 LLM 返回的记忆 JSON；非法则返回空列表。"""
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        mtype = str(item.get("memory_type") or "").strip()
        if mtype not in {"fact", "preference", "summary"}:
            continue
        key = str(item.get("memory_key") or "").strip()
        value = str(item.get("memory_value") or "").strip()
        if not key or not value:
            continue
        if mtype == "summary" and not key:
            key = "conv_digest"
        conf = item.get("confidence", 0.8)
        try:
            confidence = float(conf)
        except (TypeError, ValueError):
            confidence = 0.8
        out.append(
            {
                "memory_type": mtype,
                "memory_key": key[:100],
                "memory_value": value[:2000],
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
    return out


async def extract_memories_from_transcript(transcript: str) -> list[dict[str, Any]]:
    """编排：Mock 用规则；真模型走 LLM JSON，失败回落规则；补 summary。"""
    text = (transcript or "").strip()
    if not text:
        return []
    settings = get_settings()
    if settings.mock_external:
        return parse_auto_extract_rules(text)

    from app.modules.llm import client as llm_client

    items: list[dict[str, Any]] = []
    try:
        raw = await llm_client.chat_completion_json(
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": text},
            ]
        )
        items = parse_memory_json(raw)
    except Exception:  # noqa: BLE001
        items = []
    if not items:
        items = parse_auto_extract_rules(text)
    else:
        _maybe_append_summary(text, items)
    return items


async def persist_extracted_memories(
    db: AsyncSession,
    *,
    user_id: str,
    items: list[dict[str, Any]],
) -> dict[str, int]:
    """Embedding 去重后写入 MySQL，并 best-effort 写 Milvus。"""
    from app.modules.memory.embedding import cosine_similarity, embed_texts
    from app.modules.memory.milvus_store import search_similar, upsert_memory_vector

    if not items:
        return {"saved": 0, "skipped": 0}

    existing = await list_long_memories(db, user_id, memory_access="all")
    existing_vecs: list[list[float]] = []
    if existing:
        existing_vecs = await embed_texts([m.memory_value for m in existing])

    threshold = get_settings().memory_dedupe_threshold
    saved = 0
    skipped = 0
    for it in items:
        value = str(it.get("memory_value") or "")
        vec = (await embed_texts([value]))[0]

        milvus_hits = search_similar(user_id=user_id, vector=vec, top_k=1)
        if milvus_hits and float(milvus_hits[0].get("score") or 0) > threshold:
            skipped += 1
            continue

        if any(cosine_similarity(vec, ev) > threshold for ev in existing_vecs):
            skipped += 1
            continue

        row = await upsert_memory(
            db,
            user_id=user_id,
            memory_type=str(it["memory_type"]),
            memory_key=str(it["memory_key"]),
            memory_value=value,
            source="auto_sliding_expired",
            confidence=float(it.get("confidence", 0.8)),
        )
        eid = upsert_memory_vector(
            memory_id=row.id,
            user_id=user_id,
            memory_type=row.memory_type,
            vector=vec,
        )
        if eid:
            row.embedding_id = eid
            await db.commit()
            await db.refresh(row)

        existing_vecs.append(vec)
        saved += 1
    return {"saved": saved, "skipped": skipped}


def memory_to_dict(m: UserMemory) -> dict[str, Any]:
    return {
        "id": m.id,
        "user_id": m.user_id,
        "memory_type": m.memory_type,
        "memory_key": m.memory_key,
        "memory_value": m.memory_value,
        "confidence": m.confidence,
        "source": m.source,
        "is_archived": bool(m.is_archived),
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
    }


async def resolve_agent_memory_policy(
    db: AsyncSession,
    agent_id: str | None,
) -> tuple[str, bool]:
    """返回 (memory_access, allow_memory_write)。

    无 Agent 的系统对话：注入 all，允许平台异步抽取。
    有 Agent：按配置；默认 can_modify_memory=false 禁止写入。
    """
    if not agent_id:
        return "all", True
    from app.models.agent import Agent

    agent = await db.get(Agent, agent_id)
    if agent is None:
        return "all", True
    access = agent.memory_access or "all"
    if access not in {"none", "preference", "fact", "all"}:
        access = "all"
    return access, bool(agent.can_modify_memory)
