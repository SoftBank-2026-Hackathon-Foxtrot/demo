"""Live chat during real Redis cutover + normal rollback, isolated migration stack.

docker compose -p chiikawa-live -f docker-compose.yml -f compose.migration.yml exec -T app python -u scripts/check_cutover.py
No /seed, no reconnect, no history replay counted as live delivery.
"""
import asyncio
import json
import uuid
from urllib.request import Request, urlopen

from check_live import api, join


def admin(path, body=None, service="statemig:8090"):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"http://{service}{path}", data=data,
                  headers={"Authorization": "Bearer local-live-admin", "Content-Type": "application/json"})
    with urlopen(req, timeout=40) as response:
        return json.load(response)


async def wait_ready():
    async with asyncio.timeout(60):
        while not (await asyncio.to_thread(admin, "/migrations/current/ready"))["ready"]:
            await asyncio.sleep(.5)


async def main():
    tag = uuid.uuid4().hex[:8]
    sid_a = api("http://app:8000", f"/api/login/cutover-{tag}", method="POST")["sid"]
    sid_b = api("http://app-gcp:8000", f"/api/login/observer-{tag}", method="POST")["sid"]
    a, _, ready_a = await join("http://app:8000", sid_a)
    b, _, ready_b = await join("http://app-gcp:8000", sid_b)
    received = [[], []]
    acked = []

    async def collect(ws, bucket):
        async for raw in ws:
            data = json.loads(raw)
            if data["type"] == "message":
                bucket.append(data["message"]["id"])
            elif data["type"] == "ack":
                acked.append(data["id"])
            elif data["type"] == "error":
                raise AssertionError(data)

    readers = [asyncio.create_task(collect(a, received[0])), asyncio.create_task(collect(b, received[1]))]
    sent = []

    async def publish():
        # Less than 60/min per sender, but overlaps both switches.
        for i in range(40):
            mid = str(uuid.uuid4())
            sent.append(mid)
            await a.send(json.dumps({"id": mid, "text": f"이전 중 채팅 {tag} / {i + 1:02}"}))
            await asyncio.sleep(.25)

    writer = None
    try:
        await asyncio.to_thread(admin, "/migrations", {"target": "gcp", "budget_ms": 5000, "timeout_s": 60})
        await wait_ready()
        writer = asyncio.create_task(publish())
        await asyncio.sleep(1)
        cutover = await asyncio.to_thread(admin, "/migrations/current/cutover", {"budget_ms": 5000})
        print("CUTOVER", cutover)
        await asyncio.sleep(2)
        rollback = await asyncio.to_thread(admin, "/migrations/current/rollback", {"mode": "normal", "budget_ms": 5000})
        print("ROLLBACK", rollback)
        await writer
        async with asyncio.timeout(15):
            while not all(set(sent) <= set(bucket) for bucket in [acked, *received]):
                for task in readers:
                    if task.done():
                        task.result()
                        raise AssertionError("WebSocket closed during the switch")
                await asyncio.sleep(.1)
        for bucket in received:
            ours = [mid for mid in bucket if mid in sent]
            assert len(ours) == len(set(ours)) == len(sent)
        stats = await asyncio.to_thread(admin, "/status", service="proxy:7000")
        assert stats["proxy"]["pubsub_dropped"] == 0
        print("PASS: 40/40 live messages on both app instances, no duplicates, no WebSocket reconnect")
        print("CONNECTIONS", ready_a, ready_b)
        print("PROXY", {k: v for k, v in stats["proxy"].items() if k.startswith("pubsub") or k == "active"})
    finally:
        if writer:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
        for task in readers:
            task.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        await a.close()
        await b.close()
        api("http://app:8000", "/api/logout", sid_a, "POST")
        api("http://app-gcp:8000", "/api/logout", sid_b, "POST")


asyncio.run(main())
