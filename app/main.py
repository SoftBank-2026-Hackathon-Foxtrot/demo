"""치이카와 공구앱 (demo): the app being migrated. It only knows three fixed addresses: the central
Redis proxy (REDIS_URL), PgBouncer (DATABASE_URL) and object storage (S3_ENDPOINT).

Source of truth is PostgreSQL. Redis holds what the design moves:
  session:{sid}          login session, TTL 30 min (must survive a cutover)
  cache:groupbuy:{id}    cache-aside group-buy detail, TTL 5 min
  rl:{uid}:{minute}      join rate limit, TTL 1 min (not migrated)
  q:join, q:notify       Streams with consumer group "workers"
  q:delayed              ZSET of scheduled jobs (score = due time)
Object storage holds order receipts under keys that never change.

Join flow: INSERT join_requests(status=QUEUED) → XADD q:join → "accepted".
The worker decides CONFIRMED / SOLD_OUT inside one DB transaction, then stores the receipt.
"""
import asyncio
import json
import os
import signal
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from redis.backoff import NoBackoff
from redis.retry import Retry

from .telemetry import TraceMiddleware, get_telemetry
from . import chat, metrics, receipts, order_demo
from .db import close_job, connect, init_schema
from .redisroute import router as redis_router
from .workload import HoldTimeout, workload

SESSION_TTL, CACHE_TTL, RL_WINDOW, RL_LIMIT = 1800, 300, 60, 1000
GOODS = ["치이카와 봉제 인형", "하치와레 키링", "우사기 머그컵", "치이카와 미니 백팩", "하치와레 노트",
         "우사기 스티커 세트", "치이카와 선물 상자", "모몬가 쿠키 틴", "쿠리만주 배지", "라코 티셔츠"]

# No client-side retries: any error the proxy lets through must show up in the load test.
# The pool follows the Redis route the platform orders (redisroute.py); REDIS_URL alone when off.
r = redis_router.client(decode_responses=True, retry=Retry(NoBackoff(), 0), max_connections=200,
                        socket_timeout=10)
SERVED_BY = os.environ.get("SERVED_BY", "local")
DRAIN_S = float(os.environ.get("DRAIN_S", "6"))    # time to leave the load balancer; see README
_stopping = threading.Event()
_ready = threading.Event()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """SIGTERM: /readyz turns 503 at once, and the server only starts stopping after the drain."""
    await asyncio.to_thread(lambda: init_schema(connect()))
    workload.start()
    previous = signal.getsignal(signal.SIGTERM)

    def on_term(signum, frame):
        _stopping.set()
        threading.Timer(DRAIN_S, previous, (signum, frame)).start()

    if callable(previous):
        signal.signal(signal.SIGTERM, on_term)
    try:
        yield
    finally:
        await asyncio.to_thread(workload.stop_observations)
        await asyncio.to_thread(get_telemetry("app").close)


app = FastAPI(title="chiikawa group-buy", lifespan=lifespan)
app.include_router(chat.router)
api = APIRouter()      # what the screen calls, served at /api


@app.middleware("http")
async def hold_gate(request: Request, call_next):
    """During a DB cutover the platform holds the work: requests wait here, at most 60 s.
    /readyz does not wait: a held environment must stay in the load balancer."""
    if request.url.path == "/readyz":
        return await call_next(request)
    try:
        async with workload.gate():
            return await call_next(request)
    except HoldTimeout:
        return JSONResponse({"detail": "migrating, try again"}, status_code=503,
                            headers={"Retry-After": "5"})


@app.middleware("http")   # added last, so it runs outermost and marks gate answers too
async def served_by(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Served-By"] = SERVED_BY
    return response


@app.get("/readyz")
def readyz(response: Response):
    """Latched after the first success: a DB or Redis PAUSE during a cutover must not take this
    environment out of the load balancer. A store that really fails is the orchestrator's call."""
    if _stopping.is_set():
        response.status_code = 503
        return {"ready": False, "reason": "stopping"}
    if not workload.ready:
        response.status_code = 503
        return {"ready": False, "reason": "waiting for the platform"}
    if not _ready.is_set():
        try:
            connect().execute("SELECT 1")
            r.ping()
            _ready.set()
        except Exception as e:  # noqa: BLE001
            response.status_code = 503
            return {"ready": False, "reason": type(e).__name__}
    return {"ready": True}


def user_of(sid: str | None) -> str:
    uid = r.get(f"session:{sid}") if sid else None
    if uid is None:
        raise HTTPException(401, "login first")
    r.expire(f"session:{sid}", SESSION_TTL)
    return uid


@app.post("/seed")
def seed(groupbuys: int = 10, stock: int = 1_000_000, close_in_s: int = 30):
    db = connect()
    init_schema(db, reset=True)
    receipts.ensure_buckets()
    now = int(time.time() * 1000)
    closes = {i: now + close_in_s * 1000 + i * 1000 for i in range(groupbuys)}
    with db.transaction(), db.cursor() as cur:
        cur.executemany("INSERT INTO groupbuys(id, title, price, stock, initial, close_at_ms) VALUES (%s,%s,%s,%s,%s,%s)",
                        [(i, GOODS[i] if i < len(GOODS) else f"치이카와 굿즈 #{i}", 12000 + i * 100, stock, stock, closes[i])
                         for i in range(groupbuys)])
    r.zadd("q:delayed", {close_job(i): at for i, at in closes.items()})
    return {"groupbuys": groupbuys, "stock": stock}


@api.post("/login/{uid}")
def login(uid: str):
    sid = uuid.uuid4().hex
    r.set(f"session:{sid}", uid, ex=SESSION_TTL)
    return {"sid": sid}


@api.post("/logout")
def logout(x_session: str | None = Header(None)):
    r.delete(f"session:{x_session}")
    return {"ok": True}


@api.get("/me")
def me(x_session: str | None = Header(None)):
    return {"uid": user_of(x_session)}


@api.get("/live/baseline")
def live_baseline(x_session: str | None = Header(None)):
    user_of(x_session)
    return metrics.snapshot() | {"served_by": SERVED_BY}


@api.post("/live/metrics")
def live_metrics(measurement: metrics.Measurement, x_session: str | None = Header(None)):
    user_of(x_session)
    return metrics.inspect(measurement) | {"served_by": SERVED_BY}


@api.get("/me/requests")
def my_requests(x_session: str | None = Header(None)):
    uid = user_of(x_session)
    rows = connect().execute(
        "SELECT r.request_id, g.title, r.qty, r.status, r.created_ms, o.receipt_key IS NOT NULL FROM join_requests r "
        "JOIN groupbuys g ON g.id = r.groupbuy_id LEFT JOIN orders o ON o.request_id = r.request_id "
        "WHERE r.user_id=%s ORDER BY r.created_ms DESC LIMIT 50", (uid,)).fetchall()
    return [{"id": x[0], "title": x[1], "qty": x[2], "status": x[3], "created_ms": x[4], "receipt": x[5]} for x in rows]


@api.post("/live/orders/prepare")
def prepare_order_demo(x_session: str | None = Header(None)):
    user_of(x_session)
    return order_demo.prepare()


@api.get("/live/orders")
def order_demo_snapshot(x_session: str | None = Header(None)):
    user_of(x_session)
    return order_demo.snapshot()


@api.post("/live/orders")
def submit_order_demo(batch: order_demo.OrderBatch, x_session: str | None = Header(None),
                      idempotency_key: str = Header(..., min_length=1, max_length=96)):
    return order_demo.submit(user_of(x_session), batch.count, idempotency_key, r)


@api.get("/me/receipts/{request_id}")
def my_receipt(request_id: str, x_session: str | None = Header(None)):
    uid = user_of(x_session)
    row = connect().execute("SELECT receipt_key FROM orders WHERE request_id=%s AND user_id=%s", (request_id, uid)).fetchone()
    if row is None or row[0] is None:
        raise HTTPException(404, "no receipt yet")
    try:
        receipt, bucket = receipts.get(row[0])
    except receipts.ReceiptMissing as e:
        raise HTTPException(404, "no receipt yet") from e
    except Exception as e:  # noqa: BLE001  storage unreachable: the order itself is still safe
        raise HTTPException(503, "receipt storage unavailable") from e
    return receipt | {"bucket": bucket}


@api.get("/groupbuys")
def list_gb(x_session: str | None = Header(None)):
    user_of(x_session)
    rows = connect().execute("SELECT id, title, price, stock, closed_ms, close_at_ms FROM groupbuys ORDER BY id").fetchall()
    return [{"id": x[0], "title": x[1], "price": x[2], "stock": x[3], "closed": x[4] is not None, "close_at_ms": x[5]}
            for x in rows]


@api.get("/groupbuys/{gb}")
def get_gb(gb: int, x_session: str | None = Header(None)):
    user_of(x_session)
    key = f"cache:groupbuy:{gb}"
    if (hit := r.get(key)) is not None:
        return json.loads(hit) | {"cache": "hit"}
    row = connect().execute("SELECT id, title, price, stock FROM groupbuys WHERE id=%s", (gb,)).fetchone()
    if row is None:
        raise HTTPException(404)
    val = {"id": row[0], "title": row[1], "price": row[2]}
    r.set(key, json.dumps(val), ex=CACHE_TTL)
    return val | {"cache": "miss"}


@app.post("/groupbuys/{gb}/price")
def set_price(gb: int, price: int):
    connect().execute("UPDATE groupbuys SET price=%s WHERE id=%s", (price, gb))
    r.delete(f"cache:groupbuy:{gb}")   # cache-aside: invalidate after commit
    return {"ok": True}


@api.post("/groupbuys/{gb}/join")
def join(gb: int, qty: int = 1, x_session: str | None = Header(None),
         idempotency_key: str | None = Header(None, max_length=128)):
    uid = user_of(x_session)
    rl = f"rl:{uid}:{int(time.time()) // RL_WINDOW}"
    with r.pipeline(transaction=True) as p:     # MULTI/EXEC through the proxy
        p.incr(rl)
        p.expire(rl, RL_WINDOW)
        n, _ = p.execute()
    if n > RL_LIMIT:
        raise HTTPException(429, "slow down")
    rid = uuid.uuid4().hex
    now = int(time.time() * 1000)
    db = connect()
    created = db.execute("INSERT INTO join_requests(request_id, groupbuy_id, user_id, qty, status, created_ms, idempotency_key) "
                         "VALUES (%s,%s,%s,%s, 'QUEUED', %s, %s) ON CONFLICT (user_id, idempotency_key) DO NOTHING "
                         "RETURNING request_id", (rid, gb, uid, qty, now, idempotency_key)).fetchone()
    if created is None:      # a retry of a request already taken: same answer, no second order
        row = db.execute("SELECT request_id, status FROM join_requests WHERE user_id=%s AND idempotency_key=%s",
                         (uid, idempotency_key)).fetchone()
        return {"request_id": row[0], "status": row[1]}
    r.xadd("q:join", {"request_id": rid})
    db.execute("UPDATE join_requests SET enqueued_ms=%s WHERE request_id=%s", (int(time.time() * 1000), rid))
    return {"request_id": rid, "status": "QUEUED"}


@app.get("/report")
def report():
    db = connect()
    rows = db.execute("SELECT request_id, status, qty, groupbuy_id, enqueued_ms, processed_ms, requeued "
                      "FROM join_requests").fetchall()
    gbs = db.execute("SELECT id, initial, stock FROM groupbuys").fetchall()
    orders = db.execute("SELECT groupbuy_id, COUNT(*), SUM(qty) FROM orders GROUP BY groupbuy_id").fetchall()
    stats = dict(db.execute("SELECT name, value FROM stats").fetchall())
    notified = db.execute("SELECT kind, COUNT(*) FROM notifications GROUP BY kind").fetchall()
    missing = db.execute("SELECT COUNT(*) FROM orders WHERE receipt_key IS NULL").fetchone()[0]
    return {"requests": [list(x) for x in rows], "groupbuys": [list(x) for x in gbs],
            "orders": [list(x) for x in orders], "stats": stats, "notifications": dict(notified),
            "receipts_missing": missing}


@app.get("/cache-check")
def cache_check():
    """Every cached group-buy must equal the DB row (cache-aside invariant)."""
    bad, checked = [], 0
    for gb, title, price in connect().execute("SELECT id, title, price FROM groupbuys").fetchall():
        hit = r.get(f"cache:groupbuy:{gb}")
        if hit is None:
            continue
        checked += 1
        v = json.loads(hit)
        if v["price"] != price or v["title"] != title:
            bad.append({"gb": gb, "cache": v, "db_price": price})
    return {"checked": checked, "mismatched": bad, "ok": not bad}


@app.get("/api/migration-probe")
def migration_probe(response: Response):
    """Read-only ingress sample; the normal workload gate still applies.

    This measures reachability and HOLD latency. Business probes verify stores.
    """
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {"ok": True}


app.include_router(api, prefix="/api")
app.include_router(api)    # scripts and the load generator call these directly

# The user screen. Mounted last: every route above takes priority.
WEB_DIST = Path(__file__).parent.parent / "web" / "dist"
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")


# Outer middleware includes migration HOLD wait in request duration.
app.add_middleware(TraceMiddleware, telemetry=get_telemetry("app"))
