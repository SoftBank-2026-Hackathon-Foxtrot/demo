"""Live room: PostgreSQL history, Redis Pub/Sub delivery, no process-local fan-out.

Each browser owns a dedicated subscription through REDIS_URL. The migrator can
move that subscription while the browser's WebSocket stays open. Publishing and
session checks use other pooled connections (also required by RESP2).
"""
import asyncio
import json
import os
import time
import uuid
from contextlib import suppress

import redis.asyncio as redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.backoff import NoBackoff
from redis.retry import Retry

from .db import connect
from .workload import HoldTimeout, workload

router = APIRouter()
ROOM = "chiikawa-live"
CHANNEL = "live:chiikawa-live"


def history():
    rows = connect().execute(
        "SELECT id, user_id, body, created_ms FROM chat_messages WHERE room=%s "
        "ORDER BY created_ms DESC, id DESC LIMIT 100", (ROOM,)).fetchall()
    return [dict(id=r[0], user=r[1], text=r[2], at=r[3]) for r in reversed(rows)]


def save_message(mid, uid, text):
    db = connect()
    row = db.execute(
        "INSERT INTO chat_messages(id, room, user_id, body, created_ms) VALUES (%s,%s,%s,%s,%s) "
        "ON CONFLICT DO NOTHING RETURNING id, user_id, body, created_ms",
        (mid, ROOM, uid, text, int(time.time() * 1000))).fetchone()
    if row is None:
        row = db.execute("SELECT id, user_id, body, created_ms FROM chat_messages WHERE id=%s AND room=%s",
                         (mid, ROOM)).fetchone()
        if row is None or row[1] != uid or row[2] != text:
            raise ValueError("다른 메시지와 같은 ID를 사용할 수 없어요.")
    return dict(id=row[0], user=row[1], text=row[2], at=row[3])


@router.websocket("/api/live/chat")
async def chat(ws: WebSocket):
    # First-frame authentication keeps the session token out of URLs/access logs.
    origin = ws.headers.get("origin")
    if origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).netloc != ws.headers.get("host"):
            await ws.close(code=1008)
            return
    await ws.accept()
    client = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"),
                                  decode_responses=True, protocol=2, health_check_interval=0,
                                  socket_connect_timeout=5, retry=Retry(NoBackoff(), 0))
    tasks = []
    write_lock = asyncio.Lock()

    async def send(data):
        async with write_lock:
            await asyncio.wait_for(ws.send_json(data), 5)

    try:
        try:
            auth = await asyncio.wait_for(ws.receive_json(), 5)
        except (json.JSONDecodeError, KeyError):
            await ws.close(code=4401)
            return
        sid = auth.get("sid") if isinstance(auth, dict) else None
        if not isinstance(sid, str) or len(sid) > 128:
            await ws.close(code=4401)
            return
        uid = await client.get(f"session:{sid}")
        if uid is None:
            await ws.close(code=4401)
            return
        async with client.pubsub() as sub:
            await sub.subscribe(CHANNEL)
            # Read the actual confirmation before history, so live events buffer
            # during the history query. Clients deduplicate the overlapping IDs.
            async with asyncio.timeout(10):
                while True:
                    event = await sub.get_message(timeout=1)
                    if event and event["type"] == "subscribe":
                        break
            await send({"type": "history", "messages": await asyncio.to_thread(history)})
            await send({"type": "ready", "connection_id": uuid.uuid4().hex,
                        "served_by": os.environ.get("SERVED_BY", "local"), "pid": os.getpid()})

            async def relay():
                while True:
                    event = await sub.get_message(ignore_subscribe_messages=True, timeout=1)
                    if event and event["type"] == "message":
                        await send({"type": "message", "message": json.loads(event["data"])})

            async def receive():
                while True:
                    try:
                        data = await ws.receive_json()
                    except json.JSONDecodeError:
                        await send({"type": "error", "message": "메시지 형식을 확인해 주세요."})
                        continue
                    mid = data.get("id") if isinstance(data, dict) else None
                    text = data.get("text") if isinstance(data, dict) else None
                    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 300:
                        await send({"type": "error", "message": "채팅은 1~300자로 입력해 주세요."})
                        continue
                    try:
                        mid = str(uuid.UUID(mid))
                    except (ValueError, TypeError, AttributeError):
                        await send({"type": "error", "message": "메시지 ID가 올바르지 않아요."})
                        continue
                    if await client.get(f"session:{sid}") != uid:
                        await ws.close(code=4401)
                        return
                    key = f"rl:chat:{uid}:{int(time.time()) // 60}"
                    async with client.pipeline(transaction=True) as pipe:
                        pipe.incr(key).expire(key, 60)
                        count, _ = await pipe.execute()
                    if count > 60:
                        await send({"type": "error", "id": mid, "message": "잠시 쉬었다가 보내 주세요. 분당 60개까지 보낼 수 있어요."})
                        continue
                    try:
                        async with workload.gate():   # the message is a DB write
                            message = await asyncio.to_thread(save_message, mid, uid, text.strip())
                        # A retry republishes the same persisted ID. Receivers dedupe;
                        # PostgreSQL history does not turn Pub/Sub into a replay log.
                        await client.publish(CHANNEL, json.dumps(message, ensure_ascii=False))
                        await send({"type": "ack", "id": mid})
                    except HoldTimeout:
                        await send({"type": "error", "id": mid, "message": "잠시 점검 중이에요. 같은 메시지를 다시 보내 주세요."})
                    except ValueError as exc:
                        await send({"type": "error", "id": mid, "message": str(exc)})
                    except Exception:
                        await send({"type": "error", "id": mid, "message": "전달을 확인하지 못했어요. 같은 메시지를 다시 보내 주세요."})

            async def heartbeat():
                while True:
                    await asyncio.sleep(15)
                    if await client.get(f"session:{sid}") != uid:
                        await ws.close(code=4401)
                        return
                    await client.expire(f"session:{sid}", 1800)
                    await send({"type": "heartbeat"})

            tasks = [asyncio.create_task(fn()) for fn in (relay, receive, heartbeat)]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                # Stop readers before closing their subscription connection.
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except (WebSocketDisconnect, OSError, RuntimeError, TimeoutError, redis.RedisError):
        with suppress(Exception):
            await ws.close(code=1013)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.aclose()
