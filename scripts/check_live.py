"""Actual HTTP/WebSocket checks. Run inside the app container, no extra dependencies.

docker compose exec -T app python /srv/scripts/check_live.py
LIVE_URLS=http://app:8000,http://app-gcp:8000 tests cross-instance delivery.
Creates only uniquely named test users/messages/orders; never calls /seed.
"""
import asyncio
import json
import os
import uuid
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect

URLS = os.environ.get("LIVE_URLS", "http://localhost:8000,http://localhost:8000").split(",")
BACKLOG = {}


def api(base, path, sid=None, method="GET", key=None):
    headers = {"X-Session": sid} if sid else {}
    if key:
        headers["Idempotency-Key"] = key
    with urlopen(Request(base + path, headers=headers, method=method), timeout=15) as response:
        return json.load(response)


async def event(ws, kind, mid=None):
    def matches(result):
        return result["type"] == kind and (mid is None or result.get("message", {}).get("id") == mid or result.get("id") == mid)
    queued = BACKLOG.setdefault(ws, [])
    for i, result in enumerate(queued):
        if matches(result):
            return queued.pop(i)
    async with asyncio.timeout(15):
        while True:
            result = json.loads(await ws.recv())
            if matches(result):
                return result
            queued.append(result)


async def join(base, sid):
    ws = await connect(base.replace("http", "ws", 1) + "/api/live/chat")
    await ws.send(json.dumps({"sid": sid}))
    past = await event(ws, "history")
    ready = await event(ws, "ready")
    return ws, past, ready


async def main():
    suffix = uuid.uuid4().hex[:8]
    a, b = URLS[0], URLS[-1]
    sid_a = api(a, f"/api/login/check-a-{suffix}", method="POST")["sid"]
    sid_b = api(b, f"/api/login/check-b-{suffix}", method="POST")["sid"]
    sockets = []
    try:
        first, _, ready_a = await join(a, sid_a)
        second, _, ready_b = await join(b, sid_b)
        sockets += [first, second]
        mid = str(uuid.uuid4())
        payload = {"id": mid, "text": "라이브 채팅 연결 확인 ♡"}
        await first.send(json.dumps(payload))
        got_a = await event(first, "message", mid)
        await event(first, "ack", mid)
        got_b = await event(second, "message", mid)
        assert got_a == got_b
        print("PASS: two sockets receive the same Redis-published message", ready_a, ready_b)
        await first.send(json.dumps(payload))
        await event(first, "ack", mid)
        third, past, _ = await join(b, sid_b)
        sockets.append(third)
        assert sum(m["id"] == mid for m in past["messages"]) == 1
        print("PASS: retry persists once; reconnect restores history")
        await third.send(json.dumps({"id": str(uuid.uuid4()), "text": " "}))
        await event(third, "error")
        await third.send("[]")
        await event(third, "error")
        print("PASS: malformed and empty messages rejected")
        async with connect(a.replace("http", "ws", 1) + "/api/live/chat") as unauth:
            await unauth.send(json.dumps({"sid": "invalid"}))
            await unauth.wait_closed()
            assert unauth.close_code == 4401
        print("PASS: invalid session rejected")
        api(a, "/api/logout", sid_a, "POST")
        await first.send(json.dumps({"id": str(uuid.uuid4()), "text": "expired"}))
        await first.wait_closed()
        assert first.close_code == 4401
        print("PASS: logout revokes an existing socket")
        goods = api(b, "/api/groupbuys", sid_b)
        item = next(g for g in goods if not g["closed"] and g["stock"] > 0)
        key = uuid.uuid4().hex
        order = api(b, f"/api/groupbuys/{item['id']}/join?qty=1", sid_b, "POST", key)
        retry = api(b, f"/api/groupbuys/{item['id']}/join?qty=1", sid_b, "POST", key)
        assert order["request_id"] == retry["request_id"]
        async with asyncio.timeout(25):
            while True:
                orders = api(b, "/api/me/requests", sid_b)
                matched = next(o for o in orders if o["id"] == order["request_id"])
                if matched["status"] == "CONFIRMED" and matched["receipt"]:
                    break
                await asyncio.sleep(.5)
        receipt = api(b, f"/api/me/receipts/{order['request_id']}", sid_b)
        assert receipt["qty"] == 1 and receipt["total"] == item["price"]
        print("PASS: existing order, idempotency, worker and S3 receipt")
    finally:
        await asyncio.gather(*(ws.close() for ws in sockets))
        api(b, "/api/logout", sid_b, "POST")


if __name__ == "__main__":
    asyncio.run(main())
