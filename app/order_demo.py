"""Local demo traffic uses the real order table, Redis stream and queue workers."""
import os
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .db import connect

PRODUCT_ID = 9000001


class OrderBatch(BaseModel):
    count: int = Field(ge=1, le=100)


def enabled():
    if os.environ.get("ENABLE_ORDER_DEMO") != "1":
        raise HTTPException(404, "order demo is disabled")


def prepare():
    enabled()
    now = int(time.time() * 1000)
    connect().execute(
        "INSERT INTO groupbuys(id,title,price,stock,initial,close_at_ms) "
        "VALUES (%s,%s,12000,100000,100000,%s) ON CONFLICT (id) DO NOTHING",
        (PRODUCT_ID, "치이카와 봉제 인형", now + 86400000),
    )
    return snapshot()


def snapshot():
    enabled()
    now = int(time.time() * 1000)
    row = connect().execute(
        "SELECT g.stock,g.initial,g.title,COUNT(r.request_id),COUNT(o.request_id),"
        "COUNT(r.request_id) FILTER(WHERE r.status='QUEUED'),"
        "COUNT(r.request_id) FILTER(WHERE r.status='SOLD_OUT'),"
        "COALESCE(SUM(o.qty),0),"
        "COUNT(o.request_id) FILTER(WHERE o.confirmed_ms >= %s) "
        "FROM groupbuys g LEFT JOIN join_requests r ON r.groupbuy_id=g.id "
        "LEFT JOIN orders o ON o.request_id=r.request_id "
        "WHERE g.id=%s GROUP BY g.id", (now - 5000, PRODUCT_ID),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "prepare demo product first")
    return dict(stock=row[0], initial=row[1], title=row[2], accepted=row[3], confirmed=row[4],
                pending=row[5], sold_out=row[6], confirmed_qty=row[7], confirmed_per_second=row[8] / 5,
                at=now, product_id=PRODUCT_ID)


def submit(uid: str, count: int, key: str, redis):
    enabled()
    now = int(time.time() * 1000)
    db = connect()
    keys = [f"demo:{key}:{i}" for i in range(count)]
    ids = [uuid.uuid5(uuid.NAMESPACE_URL, f"order-demo:{uid}:{item}").hex for item in keys]
    with db.transaction():
        product = db.execute("SELECT stock,closed_ms,close_at_ms FROM groupbuys WHERE id=%s", (PRODUCT_ID,)).fetchone()
        if product is None or product[0] <= 0 or product[1] is not None or product[2] <= now:
            raise HTTPException(409, "demo product is closed")
        db.execute(
            "INSERT INTO join_requests(request_id,groupbuy_id,user_id,qty,status,created_ms,idempotency_key) "
            "SELECT rid,%s,%s,1,'QUEUED',%s,idem FROM unnest(%s::text[],%s::text[]) AS batch(rid,idem) "
            "ON CONFLICT(user_id,idempotency_key) DO NOTHING", (PRODUCT_ID,uid,now,ids,keys),
        )
        queued = db.execute("SELECT request_id FROM join_requests WHERE user_id=%s AND idempotency_key=ANY(%s) AND status='QUEUED'", (uid,keys)).fetchall()
    # A lost response retries the same keys. A repeated queue message is safe in Worker.handle_join.
    with redis.pipeline(transaction=False) as pipe:
        for (rid,) in queued:
            pipe.xadd("q:join", {"request_id":rid})
        pipe.execute()
    if queued:
        db.execute("UPDATE join_requests SET enqueued_ms=%s WHERE request_id=ANY(%s)", (now,[row[0] for row in queued]))
    return {"accepted":len(ids)}
