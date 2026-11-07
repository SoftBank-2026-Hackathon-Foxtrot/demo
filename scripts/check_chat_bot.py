"""Integration check against a running demo; no seed/reset required.

Run: docker compose exec app python scripts/check_chat_bot.py
Creates two temporary sessions and leaves generated chat history for inspection.
"""
import asyncio
import json
import os
import uuid
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect

BASE = os.environ.get("LIVE_URLS", "http://localhost:8000").split(",")[0]


def api(path, sid=None):
    with urlopen(Request(BASE + path, method="POST", headers={"X-Session": sid} if sid else {}), timeout=15) as response:
        return json.load(response)


async def until(ws, kind, mid=None):
    async with asyncio.timeout(10):
        while True:
            data = json.loads(await ws.recv())
            if data["type"] == kind and (mid is None or data.get("id") == mid or data.get("message", {}).get("id") == mid):
                return data


async def control(ws, rate):
    await ws.send(json.dumps({"type": "bot", "rate": rate}))
    return await until(ws, "bot_state")


async def collect(ws, seconds):
    messages = []
    try:
        async with asyncio.timeout(seconds):
            while True:
                data = json.loads(await ws.recv())
                if data["type"] == "message" and data["message"]["user"].startswith("공구봇 "):
                    messages.append(data["message"])
    except TimeoutError:
        return messages


async def main():
    sid = api(f"/api/login/bot-check-{uuid.uuid4().hex[:8]}")["sid"]
    url = BASE.replace("http", "ws", 1) + "/api/live/chat"
    try:
        async with connect(url) as owner, connect(url) as observer:
            for ws in (owner, observer):
                await ws.send(json.dumps({"sid": sid}))
                await until(ws, "ready")
                assert (await until(ws, "bot_state"))["rate"] == 0
            for invalid in (-1, 1001, 1.5, True, "10", None):
                state = await control(owner, invalid)
                assert state["rate"] == 0 and state.get("error"), state
            print("PASS: invalid rates rejected")
            mid = str(uuid.uuid4())
            human = {"id": mid, "text": "봇과 함께 일반 채팅도 확인해요"}
            await owner.send(json.dumps(human))
            await until(owner, "ack", mid)
            assert (await until(observer, "message", mid))["message"]["text"] == human["text"]
            await owner.send(json.dumps(human))
            await until(owner, "ack", mid)
            print("PASS: ordinary chat and idempotent retry still work")
            assert (await control(owner, 5))["rate"] == 5
            slow = await collect(observer, 1.3)
            assert 3 <= len(slow) <= 10, len(slow)
            assert (await control(owner, 30))["rate"] == 30
            fast = await collect(observer, 1.3)
            assert len(fast) > len(slow) * 2, (len(slow), len(fast))
            assert (await control(owner, 0))["rate"] == 0
            await collect(observer, .3)  # allow the in-flight message to finish
            assert not await collect(observer, .5)
            print(f"PASS: Pub/Sub delivery, live rate change ({len(slow)} -> {len(fast)}), stop")
            async with connect(url) as restored:
                await restored.send(json.dumps({"sid": sid}))
                history = (await until(restored, "history"))["messages"]
                assert fast[-1]["id"] in {m["id"] for m in history}
                await until(restored, "ready")
                assert (await until(restored, "bot_state"))["rate"] == 0
            print("PASS: bot messages persisted in PostgreSQL history")
            await control(owner, 10)
            await owner.close()
            await collect(observer, .3)
            assert not await collect(observer, .5)
            print("PASS: disconnect stops bot")
            await control(observer, 10)
            api("/api/logout", sid)
            await observer.wait_closed()
            assert observer.close_code == 4401
            print("PASS: logout stops bot and revokes socket")
    finally:
        api("/api/logout", sid)


if __name__ == "__main__":
    asyncio.run(main())
