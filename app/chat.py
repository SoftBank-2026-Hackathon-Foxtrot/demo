"""Live room: PostgreSQL history, Redis Pub/Sub delivery, no process-local fan-out.

Each browser owns a dedicated subscription on the Redis route in force (redisroute.py). The migrator
can move that subscription while the browser's WebSocket stays open, and so can this session when
the platform moves the app between a direct connection and the proxy: it subscribes on the new route
first, then leaves the old one, and drops the messages that arrive on both. Publishing and session
checks use other pooled connections (also required by RESP2).
"""
import asyncio
import json
import os
import time
import uuid
from collections import deque
from contextlib import suppress

import redis.asyncio as redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.backoff import NoBackoff
from redis.retry import Retry

from .db import connect
from .redisroute import close_when_idle
from .redisroute import router as redis_router
from .workload import HoldTimeout, workload

router = APIRouter()
ROOM = "chiikawa-live"
CHANNEL = "live:chiikawa-live"
BOT_MAX_RATE = 1000
BOT_LINES = ("치이카와 너무 귀여워요 ♡", "하치와레 키링 같이 모아요!", "우사기도 데려가고 싶어요!", "오늘 공구도 응원해요 ✦")
CLIENT_OPTIONS = dict(decode_responses=True, protocol=2, health_check_interval=0, socket_connect_timeout=5,
                      retry=Retry(NoBackoff(), 0))
MOVE_LIMIT_S = 5


async def subscribed(client: redis.Redis):
    """A subscription on `client`, returned once Redis has confirmed it, with what came first."""
    sub = client.pubsub()
    await sub.subscribe(CHANNEL)
    early = []
    async with asyncio.timeout(10):
        while True:
            event = await sub.get_message(timeout=1)
            if event and event["type"] == "subscribe":
                return sub, early
            if event and event["type"] == "message":
                early.append(event)


class Link:
    """This session's Redis: the client for commands and the subscription, moved together."""

    def __init__(self) -> None:
        self.url = redis_router.url()
        self.client = redis_router.async_client(**CLIENT_OPTIONS)
        self.sub = None


async def publish_message(client, mid, uid, text):
    # Bots use the same persistence, cutover gate and Redis delivery as people.
    async with workload.gate():
        message = await asyncio.to_thread(save_message, mid, uid, text)
    await client.publish(CHANNEL, json.dumps(message, ensure_ascii=False))


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
    if not workload.ready:
        # Until the platform has answered, this process does not know the Redis route in force.
        await ws.close(code=1013)
        return
    link = Link()
    key = id(link)
    loop = asyncio.get_running_loop()
    moved = asyncio.Event()

    def wake():
        # On the heartbeat thread, before the next report: this session counts as not moved yet.
        redis_router.mark_stale(key, 1)
        loop.call_soon_threadsafe(moved.set)
    forget = redis_router.watch(wake)
    tasks = []
    write_lock = asyncio.Lock()
    bot_rate = 0
    bot_changed = asyncio.Event()

    async def send(data):
        async with write_lock:
            await asyncio.wait_for(ws.send_json(data), 5)

    workload.socket_opened()
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
        uid = await link.client.get(f"session:{sid}")
        if uid is None:
            await ws.close(code=4401)
            return
        # Read the actual confirmation before history, so live events buffer
        # during the history query. Clients deduplicate the overlapping IDs.
        link.sub, early = await subscribed(link.client)
        await send({"type": "history", "messages": await asyncio.to_thread(history)})
        await send({"type": "ready", "connection_id": uuid.uuid4().hex,
                    "served_by": os.environ.get("SERVED_BY", "local"), "pid": os.getpid(),
                    "measurement_since_ms": int(time.time() * 1000)})
        await send({"type": "bot_state", "rate": 0})
        recent: deque[str] = deque(maxlen=2000)

        async def forward(event):
            message = json.loads(event["data"])
            if message.get("id") in recent:     # delivered on both routes while moving
                return
            recent.append(message.get("id"))
            await send({"type": "message", "message": message})

        for event in early:
            await forward(event)

        async def move():
            """New route first, then leave the old one: nothing published meanwhile is missed."""
            moved.clear()
            url = redis_router.url()
            if url == link.url:
                redis_router.mark_stale(key, 0)
                return
            old_client, old_sub = link.client, link.sub
            new_client = redis_router.async_client(**CLIENT_OPTIONS)
            new_sub, pending = await subscribed(new_client)
            await old_sub.unsubscribe(CHANNEL)
            # Redis answers the unsubscribe after every message already sent on that connection.
            with suppress(TimeoutError):
                async with asyncio.timeout(MOVE_LIMIT_S):
                    while True:
                        event = await old_sub.get_message(timeout=1)
                        if event and event["type"] == "message":
                            await forward(event)
                        elif event and event["type"] == "unsubscribe":
                            break
            link.client, link.sub, link.url = new_client, new_sub, url
            for event in pending:
                await forward(event)
            await old_sub.aclose()
            await close_when_idle(old_client)
            if redis_router.url() == link.url:
                redis_router.mark_stale(key, 0)

        async def bot():
            nonlocal bot_rate
            sequence = 0
            while True:
                bot_changed.clear()
                if not bot_rate:
                    await bot_changed.wait()
                    continue
                started = asyncio.get_running_loop().time()
                try:
                    if await link.client.get(f"session:{sid}") != uid:
                        await ws.close(code=4401)
                        return
                    sequence += 1
                    await publish_message(link.client, str(uuid.uuid4()), f"공구봇 {(sequence - 1) % 8 + 1}",
                                          f"{BOT_LINES[(sequence - 1) % len(BOT_LINES)]} · {sequence}")
                except Exception:
                    bot_rate = 0
                    await send({"type": "bot_state", "rate": 0,
                                "error": "봇 메시지를 전달하지 못해 멈췄어요. 다시 시작해 주세요."})
                    continue
                # No catch-up burst after a slow DB write or a cutover hold.
                if bot_rate:
                    delay = max(0, 1 / bot_rate - (asyncio.get_running_loop().time() - started))
                    with suppress(TimeoutError):
                        await asyncio.wait_for(bot_changed.wait(), delay)

        async def relay():
            while True:
                if moved.is_set():
                    await move()
                    continue
                event = await link.sub.get_message(ignore_subscribe_messages=True, timeout=1)
                if event and event["type"] == "message":
                    await forward(event)

        async def receive():
            nonlocal bot_rate
            while True:
                try:
                    data = await ws.receive_json()
                except json.JSONDecodeError:
                    await send({"type": "error", "message": "메시지 형식을 확인해 주세요."})
                    continue
                if isinstance(data, dict) and data.get("type") == "bot":
                    if await link.client.get(f"session:{sid}") != uid:
                        await ws.close(code=4401)
                        return
                    rate = data.get("rate")
                    if type(rate) is not int or not 0 <= rate <= BOT_MAX_RATE:
                        await send({"type": "bot_state", "rate": bot_rate,
                                    "error": f"봇 트래픽은 초당 1~{BOT_MAX_RATE}개로 입력해 주세요."})
                        continue
                    bot_rate = rate
                    bot_changed.set()
                    await send({"type": "bot_state", "rate": bot_rate})
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
                if await link.client.get(f"session:{sid}") != uid:
                    await ws.close(code=4401)
                    return
                rl_key = f"rl:chat:{uid}:{int(time.time()) // 60}"
                async with link.client.pipeline(transaction=True) as pipe:
                    pipe.incr(rl_key).expire(rl_key, 60)
                    count, _ = await pipe.execute()
                if count > 60:
                    await send({"type": "error", "id": mid, "message": "잠시 쉬었다가 보내 주세요. 분당 60개까지 보낼 수 있어요."})
                    continue
                try:
                    # A retry republishes the same persisted ID. Receivers dedupe;
                    # PostgreSQL history does not turn Pub/Sub into a replay log.
                    await publish_message(link.client, mid, uid, text.strip())
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
                if await link.client.get(f"session:{sid}") != uid:
                    await ws.close(code=4401)
                    return
                await link.client.expire(f"session:{sid}", 1800)
                await send({"type": "heartbeat"})

        tasks = [asyncio.create_task(fn()) for fn in (relay, receive, heartbeat, bot)]
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
        workload.socket_closed()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        forget()
        if link.sub is not None:
            with suppress(Exception):
                await link.sub.aclose()
        await link.client.aclose()
        redis_router.mark_stale(key, 0)
