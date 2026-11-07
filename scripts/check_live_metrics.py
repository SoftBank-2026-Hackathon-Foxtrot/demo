"""Read-only retention checks plus temporary bot traffic; does not delete or reset data.

Run: docker compose exec -T app python scripts/check_live_metrics.py
"""
import asyncio
import json
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect

BASE = "http://localhost:8000"


def api(path, sid=None, body=None, method="GET"):
    headers = {"Content-Type": "application/json"}
    if sid:
        headers["X-Session"] = sid
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(BASE + path, data=data, method=method, headers=headers), timeout=15) as response:
        return json.load(response)


def rejected(path, sid, body, status):
    try:
        api(path, sid, body, "POST")
    except HTTPError as exc:
        assert exc.code == status, exc.code
    else:
        raise AssertionError(f"Expected {status}")


async def main():
    sid = api(f"/api/login/metrics-check-{uuid.uuid4().hex[:8]}", method="POST")["sid"]
    try:
        snapshot = api("/api/live/baseline", sid)
        assert snapshot["served_by"] and all(len(ids) <= 500 for ids in snapshot["ids"].values())
        measured = api("/api/live/metrics", sid, {"since_ms": 0, "baseline": snapshot["ids"]}, "POST")
        assert measured["served_by"] == snapshot["served_by"]
        assert all(row["retained"] == row["expected"] for row in measured["retention"].values())
        baseline = snapshot["ids"] | {"orders": ["missing-" + uuid.uuid4().hex]}
        missing = api("/api/live/metrics", sid, {"since_ms": 0, "baseline": baseline}, "POST")
        assert missing["retention"]["orders"] == {"retained": 0, "expected": 1}
        assert len(measured["chat_ids"]) <= 1000
        print("PASS: environment, bounded baseline, retained IDs and missing IDs")
        empty = api("/api/live/metrics", sid, {"since_ms": 9999999999999}, "POST")
        assert empty["retention"] is None and not empty["chat_ids"]
        rejected("/api/live/metrics", None, {"since_ms": 0}, 401)
        rejected("/api/live/metrics", sid, {"since_ms": -1}, 422)
        rejected("/api/live/metrics", sid, {"since_ms": 0, "baseline": {"chat": ["x"] * 501}}, 422)
        print("PASS: no fabricated empty percentage; authentication and bounds checked")
        received = set()
        async with connect(BASE.replace("http", "ws", 1) + "/api/live/chat") as ws:
            await ws.send(json.dumps({"sid": sid}))

            async def until(kind):
                async with asyncio.timeout(10):
                    while True:
                        event = json.loads(await ws.recv())
                        if event["type"] == "message":
                            received.add(event["message"]["id"])
                        if event["type"] == kind:
                            return event

            ready = await until("ready")
            since = ready["measurement_since_ms"]
            await until("bot_state")
            await ws.send(json.dumps({"type": "bot", "rate": 5}))
            await until("bot_state")
            for _ in range(5):
                await until("message")
            await ws.send(json.dumps({"type": "bot", "rate": 0}))
            await until("bot_state")
            early = api("/api/live/metrics", sid, {"since_ms": since}, "POST")
            assert not early["chat_ids"], early
            await asyncio.sleep(2.2)
            final = api("/api/live/metrics", sid, {"since_ms": since}, "POST")
            assert len(final["chat_ids"]) >= 5 and set(final["chat_ids"]) <= received
            print("PASS: live Pub/Sub IDs match stored sample; 2-second delivery grace respected")
    finally:
        api("/api/logout", sid, method="POST")


if __name__ == "__main__":
    asyncio.run(main())
