"""Redis design 3-8 end to end, locally: direct → proxy → cutover → direct to the target, under load.

  1. start this (it serves the workload heartbeat on :18600 with control-plane's coordinator)
       uv run --project ../control-plane --with websockets --with redis python scripts/e2e_redis_route.py
  2. it waits for the stack of compose.direct.yml, which it does not start itself:
       docker compose -p redis-direct -f docker-compose.yml -f compose.migration.yml -f compose.direct.yml up -d --build

The heartbeat endpoint is control-plane's route logic around its real WorkloadCoordinator (memory
store); the Redis steps are statemig's own API, in the order the orchestrator sends them. Chat
clients, a chat bot and HTTP users run the whole time. At the end every received chat message is
checked for loss and duplicates, the queue for unprocessed requests, and the sessions for survival.
"""
import asyncio
import json
import random
import sys
import time
import uuid
from collections import Counter

import httpx
import redis.asyncio as aioredis
import uvicorn
import websockets
from fastapi import FastAPI, Header, HTTPException

from control_plane.api.schemas import DirectiveView, Heartbeat
from control_plane.clock import SystemClock
from control_plane.domain.models import RedisRoute
from control_plane.seed import Seed
from control_plane.store.repository import Repository
from control_plane.store.table import MemoryTable
from control_plane.workload.coordinator import WorkloadCoordinator

APP = "http://127.0.0.1:18800"
WS = "ws://127.0.0.1:18800/api/live/chat"
STATEMIG = "http://127.0.0.1:18900"
STATEMIG_TOKEN = "local-live-admin"
REDIS = {"aws": 16501, "gcp": 16502}
TOKEN = "e2e-workload-token"
CHAT_CLIENTS, CHAT_EVERY_S, BOT_RATE, HTTP_USERS = 8, 1.1, 10, 4

SEED = {
    "application": "goods", "scope": "scope:goods",
    "environments": {
        "aws": {"appUrl": "http://app:8000", "trafficPool": "aws",
                "actors": {"goods-aws-api": 4, "goods-aws-worker": 2}},
        "gcp": {"appUrl": "http://app-gcp:8000", "trafficPool": "gcp", "actors": {"goods-gcp-api": 0}},
    },
    "resources": {
        "database": {"sourceRef": "db:a", "targetRef": "db:b",
                     "policy": {"rollbackMode": "BEFORE_TARGET_WRITE", "maxQuiesceSeconds": 30},
                     "catalog": {"databases": {"db:a": {}, "db:b": {}}, "tables": ["public.t"], "alias": "appdb",
                                 "appRef": "app:goods"}},
        "redis": {"sourceRef": "resource:aws", "targetRef": "resource:gcp", "bindingRef": "binding:redis-proxy",
                  "policy": {"rollbackMode": "REVERSE_REQUIRED", "maxQuiesceSeconds": 1.8},
                  "directWhenIdle": True},
        "object": {"sourceRef": "resource:a", "targetRef": "resource:b", "bindingRef": "binding:o",
                   "expectedApps": 1, "policy": {"rollbackMode": "REVERSE_REQUIRED", "maxQuiesceSeconds": 30}},
    },
    "adapters": {k: {"url": "http://unused", "tokenSecret": "env:X"} for k in ("database", "redis", "object")},
    "probe": {"groupbuyId": 1},
}

seed = Seed.model_validate(SEED)
coordinator = WorkloadCoordinator(Repository(MemoryTable()), seed, SystemClock())
platform = FastAPI()
results: list[tuple[str, bool, str]] = []
timeline: list[tuple[float, str]] = []
T0 = time.monotonic()


def mark(what: str) -> None:
    timeline.append((time.monotonic() - T0, what))
    print(f"[{time.monotonic() - T0:7.2f}s] {what}", flush=True)


def check(name: str, ok: bool, detail="") -> None:
    results.append((name, ok, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


@platform.post("/internal/v1/workloads/{scope}/heartbeat")
async def heartbeat(scope: str, body: Heartbeat, authorization: str = Header("")) -> DirectiveView:
    """control-plane's route, minus its auth wiring: the same checks and the same coordinator."""
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401)
    if scope != seed.scope or body.actor_id not in seed.all_actors():
        raise HTTPException(422, "unknown")
    d = await coordinator.heartbeat(
        actor_id=body.actor_id, instance_id=body.instance_id, generation=body.generation, state=body.state,
        in_flight=body.in_flight, redis_route=body.redis_route,
        redis_route_generation=body.redis_route_generation, stale_connections=body.stale_connections)
    return DirectiveView(desired=d.desired, generation=d.generation, object_migration_id=d.object_migration_id,
                         poll_after_ms=d.poll_after_ms, redis_route=d.redis_route, redis_endpoint=d.redis_endpoint,
                         redis_route_generation=d.redis_route_generation)


# ---- what the orchestrator does ------------------------------------------------------------
async def order(route: RedisRoute, endpoint: str | None, timeout_s: float = 120, stable_s: float = 10) -> float:
    """Route order, then wait as the engine does: every process follows, no old connection, for stable_s."""
    hold = await coordinator.request_redis_route("e2e", route, endpoint)
    started = time.monotonic()
    stable_since = None
    while time.monotonic() - started < timeout_s:
        ok, waiting = await coordinator.route_followed(hold.redis_route_generation, route)
        if ok:
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= stable_s:
                return stable_since - started
        else:
            stable_since = None
        await asyncio.sleep(0.2)
    raise RuntimeError(f"route {route} not followed: {waiting}")


async def statemig(http: httpx.AsyncClient, method: str, path: str, body: dict | None = None):
    r = await http.request(method, STATEMIG + path, json=body, timeout=120,
                           headers={"Authorization": f"Bearer {STATEMIG_TOKEN}"})
    return r.status_code, (r.json() if r.content else {})


async def clients_on(env: str) -> Counter:
    c = aioredis.Redis(port=REDIS[env], password="adminpw", decode_responses=True)
    try:
        out = Counter()
        for cl in await c.client_list():
            if cl.get("user") in ("app-direct", "app"):
                out[f"{cl['user']}:{cl.get('name') or '(unnamed)'}"] += 1
        return out
    finally:
        await c.aclose()


async def direct_account(env: str) -> str:
    c = aioredis.Redis(port=REDIS[env], password="adminpw", decode_responses=True)
    try:
        return "on" if "on" in (await c.acl_getuser("app-direct"))["flags"] else "off"
    finally:
        await c.aclose()


# ---- load ----------------------------------------------------------------------------------
class Load:
    def __init__(self) -> None:
        self.stop = asyncio.Event()
        self.sent: dict[str, float] = {}           # acked human message id → send time
        self.received: list[Counter] = []
        self.ready_at: list[float] = []
        self.bot_seq: list[list[int]] = []
        self.http = Counter()
        self.chat_errors = Counter()
        self.ws_closed: list[str] = []
        self.sessions: list[str] = []

    async def login(self, http: httpx.AsyncClient, uid: str) -> str:
        return (await http.post(f"{APP}/api/login/{uid}")).json()["sid"]

    async def chat(self, index: int, sid: str, bot: bool) -> None:
        received = Counter()
        seq: list[int] = []
        self.received.append(received)
        self.bot_seq.append(seq)
        async with websockets.connect(WS, max_size=2**22) as ws:
            await ws.send(json.dumps({"sid": sid}))
            while json.loads(await ws.recv())["type"] != "ready":
                pass
            self.ready_at.append(time.monotonic())
            if bot:
                await ws.send(json.dumps({"type": "bot", "rate": BOT_RATE}))

            async def reader():
                async for raw in ws:
                    frame = json.loads(raw)
                    if frame["type"] == "message":
                        m = frame["message"]
                        received[m["id"]] += 1
                        if m["user"].startswith("공구봇") and "·" in m["text"]:
                            seq.append(int(m["text"].rsplit("·", 1)[1]))
                    elif frame["type"] == "ack":
                        self.sent[frame["id"]] = time.monotonic()
                    elif frame["type"] == "error":
                        self.chat_errors[frame.get("message", "?")] += 1
                    elif frame["type"] == "bot_state" and frame.get("error"):
                        self.chat_errors["bot: " + frame["error"]] += 1

            async def writer():
                n = 0
                while not self.stop.is_set():
                    n += 1
                    await ws.send(json.dumps({"id": str(uuid.uuid4()), "text": f"e2e {index}-{n}"}))
                    await asyncio.sleep(CHAT_EVERY_S)
                if bot:
                    await ws.send(json.dumps({"type": "bot", "rate": 0}))
                await asyncio.sleep(3)     # let the last messages arrive

            read = asyncio.create_task(reader())
            try:
                await writer()
            finally:
                read.cancel()
        if not self.stop.is_set():
            self.ws_closed.append(f"client {index}")

    async def users(self, http: httpx.AsyncClient, sid: str) -> None:
        h = {"X-Session": sid}
        while not self.stop.is_set():
            for method, path in (("GET", "/api/me"), ("GET", "/api/groupbuys/1"), ("POST", "/api/groupbuys/1/join")):
                headers = h | ({"Idempotency-Key": uuid.uuid4().hex} if method == "POST" else {})
                try:
                    r = await http.request(method, APP + path, headers=headers, timeout=30)
                    self.http[r.status_code] += 1
                except httpx.HTTPError as e:
                    self.http[type(e).__name__] += 1
            await asyncio.sleep(0.1 + random.random() * 0.1)


async def wait_app(http: httpx.AsyncClient) -> None:
    for _ in range(600):
        try:
            if (await http.get(f"{APP}/readyz", timeout=2)).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    raise RuntimeError("the app never became ready")


async def scenario() -> None:
    async with httpx.AsyncClient() as http:
        mark("waiting for the app (start the compose stack now)")
        await wait_app(http)
        await http.post(f"{APP}/seed", params={"groupbuys": 3, "stock": 1_000_000, "close_in_s": 3600})
        await order(RedisRoute.DIRECT, "aws", stable_s=3)
        mark("every process on the aws Redis directly")
        before = await clients_on("aws")
        check("평소: 앱 연결이 모두 direct:<actor> 이름으로 aws에 직접", before and all(k.startswith("app-direct:direct:")
              for k in before), dict(before))

        load = Load()
        sids = [await load.login(http, f"e2e-chat-{i}") for i in range(CHAT_CLIENTS)]
        user_sids = [await load.login(http, f"e2e-user-{i}") for i in range(HTTP_USERS)]
        load.sessions = sids + user_sids
        tasks = [asyncio.create_task(load.chat(i, sid, bot=i == 0)) for i, sid in enumerate(sids)]
        tasks += [asyncio.create_task(load.users(http, sid)) for sid in user_sids]
        await asyncio.sleep(8)
        mark("load running")

        code, body = await statemig(http, "POST", "/migrations", {"target": "gcp", "timeout_s": 600})
        check("진입 전 PREPARE: 원본에 직접 연결이 있어 거부", code == 409 and "direct connections" in str(body),
              str(body)[:160])

        took = await order(RedisRoute.PROXY, None)
        mark(f"entry confirmed (every process followed after {took:.1f}s, then 10s stable)")
        on_aws = await clients_on("aws")
        check("진입 뒤: aws에 직접 연결 0개", not any(k.startswith("app-direct") for k in on_aws), dict(on_aws))

        code, body = await statemig(http, "POST", "/migrations", {"target": "gcp", "timeout_s": 600})
        check("진입 뒤 PREPARE 통과", code == 200, str(body)[:160] if code != 200 else "")
        check("원본(aws) 직접 연결 계정이 꺼짐", await direct_account("aws") == "off")
        for _ in range(600):
            if (await statemig(http, "GET", "/migrations/current/ready"))[1].get("ready"):
                break
            await asyncio.sleep(0.5)
        mark("sync ready")
        await asyncio.sleep(3)
        code, body = await statemig(http, "POST", "/migrations/current/cutover", {"budget_ms": 1800})
        check("컷오버", code == 200, body.get("paused_ms") if code == 200 else str(body)[:200])
        mark(f"cutover, writes paused {body.get('paused_ms')} ms")
        for _ in range(600):
            state = (await statemig(http, "GET", "/status"))[1]["migration"]["state"]
            if state == "CUTOVER":
                break
            await asyncio.sleep(0.5)
        mark("queue drain done")
        await asyncio.sleep(5)
        code, body = await statemig(http, "POST", "/migrations/current/commit")
        check("확정(commit)", code == 200, "" if code == 200 else str(body)[:160])
        check("남은 쪽(gcp) 직접 연결 계정이 켜짐", await direct_account("gcp") == "on")

        took = await order(RedisRoute.DIRECT, "gcp")
        mark(f"exit confirmed (every process on gcp directly after {took:.1f}s)")
        on_gcp, on_aws = await clients_on("gcp"), await clients_on("aws")
        check("이탈 뒤: 앱 연결이 모두 gcp에 direct:<actor> 이름으로",
              on_gcp and all(k.startswith("app-direct:direct:") for k in on_gcp), dict(on_gcp))
        check("이탈 뒤: aws에 앱 연결 없음", not any(k.startswith("app-direct") for k in on_aws), dict(on_aws))
        proxy = (await statemig(http, "GET", "/status"))[1]["proxy"]
        check("이탈 뒤: 프록시에 남은 앱 연결 0개", proxy.get("clients") == 0, f"clients={proxy.get('clients')}")

        await asyncio.sleep(5)
        load.stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        mark("load stopped")
        await judge(http, load)


async def judge(http: httpx.AsyncClient, load: Load) -> None:
    start = max(load.ready_at)
    expected = {mid for mid, at in load.sent.items() if at > start + 1}
    missing = [len(expected - set(r)) for r in load.received]
    dup = [sum(1 for n in r.values() if n > 1) for r in load.received]
    check(f"채팅: 사람 메시지 {len(load.sent)}건, 모든 클라이언트가 전부 받음", not any(missing), f"missing per client {missing}")
    check("채팅: 같은 메시지를 두 번 받은 클라이언트 없음", not any(dup), f"duplicates per client {dup}")
    gaps = []
    for seq in load.bot_seq:
        s = sorted(set(seq))
        gaps.append(sum(b - a - 1 for a, b in zip(s, s[1:])))
    check(f"채팅 봇: 연속 번호 빠짐 없음 (봇 {max(map(len, load.bot_seq))}건)", not any(gaps), f"gaps {gaps}")
    check("채팅: WebSocket이 끊긴 클라이언트 없음", not load.ws_closed, load.ws_closed)
    check("채팅: 오류 응답 없음", not load.chat_errors, dict(load.chat_errors))
    bad = {k: v for k, v in load.http.items() if k != 200}
    check(f"HTTP: 요청 {sum(load.http.values())}건 모두 200", not bad, dict(load.http))
    alive = [(await http.get(f"{APP}/api/me", headers={"X-Session": s})).status_code for s in load.sessions]
    check("세션: 이전 전에 만든 로그인이 모두 유지", set(alive) == {200}, Counter(alive))
    for _ in range(30):
        report = (await http.get(f"{APP}/report")).json()
        queued = sum(1 for r in report["requests"] if r[1] == "QUEUED")
        if not queued:
            break
        await asyncio.sleep(1)
    check(f"큐: 참여 요청 {len(report['requests'])}건 모두 처리 (QUEUED 0)", not queued, f"queued={queued}")


async def main() -> None:
    server = uvicorn.Server(uvicorn.Config(platform, host="0.0.0.0", port=18600, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    try:
        await scenario()
    finally:
        server.should_exit = True
        await serving
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
