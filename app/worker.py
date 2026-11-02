"""Queue worker for the group-buy app. Talks to Redis only through the central proxy.

  q:join     confirm or sell out, inside one DB transaction guarded by status=QUEUED,
             so a message delivered twice changes stock once. A confirmed order then gets its receipt
  q:notify   record each notification once (ref is the primary key)
  q:delayed  due jobs are moved to q:notify by one Lua script (atomic, safe with many workers)
  pending    messages a dead worker left un-acked are taken over with XAUTOCLAIM
  dead       a message that keeps failing moves to <stream>:dead, so it cannot block a drain
  reconciler (--reconciler) re-enqueues requests that stayed QUEUED too long: covers an app
             crash between INSERT and XADD, and a queue lost with a failed Redis. It also
             puts back q:delayed jobs of group-buys that are still open, and stores receipts
             that storage could not take when the order was confirmed

  python -m app.worker --name w1 [--reconciler]
"""
import argparse
import json
import logging
import os
import time

import psycopg
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from . import receipts
from .db import bump, close_job, connect

log = logging.getLogger("worker")
GROUP = "workers"
REQUEUE_AFTER_MS = 10_000
MAX_DELIVERIES = 3

MOVE_DUE = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], 0, ARGV[1], 'LIMIT', 0, 50)
for _, job in ipairs(due) do
  redis.call('XADD', KEYS[2], '*', 'job', job)
  redis.call('ZREM', KEYS[1], job)
end
return #due
"""


def now_ms() -> int:
    return int(time.time() * 1000)


class Worker:
    def __init__(self, name: str, reconciler: bool):
        self.name, self.reconciler = name, reconciler
        self.r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True,
                                      retry=Retry(NoBackoff(), 0), socket_timeout=10)
        self.move_due = self.r.register_script(MOVE_DUE)

    @property
    def db(self) -> psycopg.Connection:
        return connect()    # a connection lost in a DB cutover is replaced here

    def handle_join(self, rid: str) -> bool:
        db = self.db
        with db.transaction():
            row = db.execute("SELECT status, groupbuy_id, user_id, qty FROM join_requests WHERE request_id=%s FOR UPDATE",
                             (rid,)).fetchone()
            if row is None or row[0] != "QUEUED":
                if row is not None:
                    bump(db, "duplicate_deliveries")
                return False
            _, gb, uid, qty = row
            sold = db.execute("UPDATE groupbuys SET stock=stock-%s WHERE id=%s AND stock>=%s AND closed_ms IS NULL "
                              "RETURNING title, price", (qty, gb, qty)).fetchone()
            status = "CONFIRMED" if sold else "SOLD_OUT"
            if sold:
                db.execute("INSERT INTO orders(request_id, groupbuy_id, user_id, qty, title, price, confirmed_ms) "
                           "VALUES (%s,%s,%s,%s,%s,%s,%s)", (rid, gb, uid, qty, sold[0], sold[1], now_ms()))
            db.execute("UPDATE join_requests SET status=%s, processed_ms=%s WHERE request_id=%s AND status='QUEUED'",
                       (status, now_ms(), rid))
        self.r.xadd("q:notify", {"job": json.dumps({"type": status.lower(), "ref": rid})})
        if sold:
            self.store_receipt(rid, uid, qty, sold[0], sold[1])
        return True

    def store_receipt(self, rid: str, uid: str, qty: int, title: str, price: int) -> bool:
        """Object first, DB row after. A failure leaves the order confirmed and the reconciler retries."""
        try:
            key = receipts.put(rid, {"request_id": rid, "user": uid, "title": title, "price": price, "qty": qty,
                                     "total": price * qty})
        except Exception as e:  # noqa: BLE001  storage must not stop orders
            log.warning("receipt %s not stored: %s", rid, e)
            return False
        self.db.execute("UPDATE orders SET receipt_key=%s WHERE request_id=%s", (key, rid))
        return True

    def fill_receipts(self):
        rows = self.db.execute("SELECT request_id, user_id, qty, title, price FROM orders "
                               "WHERE receipt_key IS NULL LIMIT 100").fetchall()
        for row in rows:
            if not self.store_receipt(*row):
                break

    def handle_notify(self, job: dict):
        ref = job.get("ref") or f"{job['type']}:{job.get('groupbuy_id')}"
        db = self.db
        with db.transaction():
            if job["type"] == "close":
                db.execute("UPDATE groupbuys SET closed_ms=%s WHERE id=%s AND closed_ms IS NULL",
                           (now_ms(), job["groupbuy_id"]))
            cur = db.execute("INSERT INTO notifications(ref, kind, sent_ms) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                             (ref, job["type"], now_ms()))
            if cur.rowcount == 0:
                bump(db, "duplicate_notifications")

    def consume(self, stream: str, msgs, reclaimed: bool = False):
        for mid, fields in msgs:
            if reclaimed and self.delivered(stream, mid) > MAX_DELIVERIES:
                self.bury(stream, mid, fields)
                continue
            try:
                if stream == "q:join":
                    self.handle_join(fields["request_id"])
                else:
                    self.handle_notify(json.loads(fields["job"]))
            except (redis.RedisError, OSError, psycopg.OperationalError):
                raise
            except Exception as e:  # noqa: BLE001  left pending: XAUTOCLAIM retries it
                log.warning("message %s on %s failed: %r", mid, stream, e)
                continue
            self.r.xack(stream, GROUP, mid)

    def delivered(self, stream: str, mid: str) -> int:
        rows = self.r.xpending_range(stream, GROUP, min=mid, max=mid, count=1)
        return rows[0]["times_delivered"] if rows else 0

    def bury(self, stream: str, mid: str, fields: dict):
        self.r.xadd(f"{stream}:dead", {**fields, "source_id": mid})
        self.r.xack(stream, GROUP, mid)
        bump(self.db, "dead_letters")
        log.warning("message %s on %s moved to %s:dead", mid, stream, stream)

    def requeue_stale(self):
        cutoff = now_ms() - REQUEUE_AFTER_MS
        db = self.db
        rows = db.execute("SELECT request_id FROM join_requests WHERE status='QUEUED' "
                          "AND COALESCE(enqueued_ms, created_ms) < %s LIMIT 500", (cutoff,)).fetchall()
        for (rid,) in rows:
            self.r.xadd("q:join", {"request_id": rid})
            db.execute("UPDATE join_requests SET enqueued_ms=%s, requeued=requeued+1 WHERE request_id=%s", (now_ms(), rid))
        if rows:
            bump(db, "requeued", len(rows))
            log.info("requeued %d stale requests", len(rows))

    def restore_scheduled(self):
        """The DB owns closing times: a job lost with a Redis comes back (NX keeps existing ones)."""
        rows = self.db.execute("SELECT id, close_at_ms FROM groupbuys WHERE closed_ms IS NULL "
                               "AND close_at_ms IS NOT NULL").fetchall()
        if rows:
            self.r.zadd("q:delayed", {close_job(gb): at for gb, at in rows}, nx=True)

    def ensure_groups(self):
        for stream in ("q:join", "q:notify"):
            try:
                self.r.xgroup_create(stream, GROUP, id="0", mkstream=True)
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

    def run(self):
        last_claim = last_due = last_requeue = last_restore = 0.0
        self.ensure_groups()
        while True:
            try:
                for stream in ("q:join", "q:notify"):   # one stream per call: the proxy routes per command
                    res = self.r.xreadgroup(GROUP, self.name, {stream: ">"}, count=50, block=500)
                    for s, msgs in res or []:
                        self.consume(s, msgs)
                t = time.time()
                if t - last_claim > 5:
                    last_claim = t
                    for stream in ("q:join", "q:notify"):
                        _, msgs, _ = self.r.xautoclaim(stream, GROUP, self.name, min_idle_time=5000, count=50)
                        self.consume(stream, msgs, reclaimed=True)
                if t - last_due > 1:
                    last_due = t
                    self.move_due(keys=["q:delayed", "q:notify"], args=[now_ms()])
                if self.reconciler and t - last_requeue > 3:
                    last_requeue = t
                    self.requeue_stale()
                    self.fill_receipts()
                if self.reconciler and t - last_restore > 5:
                    last_restore = t
                    self.restore_scheduled()
            except (redis.RedisError, OSError, psycopg.Error) as e:
                log.warning("store error: %s", e)
                try:
                    bump(self.db, "worker_redis_errors" if isinstance(e, (redis.RedisError, OSError)) else "worker_db_errors")
                except psycopg.Error:
                    pass
                time.sleep(0.2)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--reconciler", action="store_true")
    a = ap.parse_args()
    for _ in range(60):   # wait for /seed to create the schema
        try:
            connect().execute("SELECT 1 FROM join_requests LIMIT 1")
            break
        except psycopg.Error:
            time.sleep(1)
    Worker(a.name, a.reconciler).run()


if __name__ == "__main__":
    main()
