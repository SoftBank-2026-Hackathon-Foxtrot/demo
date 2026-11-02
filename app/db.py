"""PostgreSQL is the source of truth, reached only through PgBouncer's fixed address.

Connections are autocommit: PgBouncer runs in transaction pooling, so a transaction left
open would hold a server connection and stretch a DB cutover's PAUSE. Multi-statement work
uses `with db.transaction():`. Server-side prepared statements are off for the same pooling.
"""
import json
import os
import threading

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:apppw@db-proxy.internal:6432/appdb")
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS groupbuys(id INTEGER PRIMARY KEY, title TEXT, price INTEGER, stock INTEGER,
                                     initial INTEGER, closed_ms BIGINT, close_at_ms BIGINT);
CREATE TABLE IF NOT EXISTS join_requests(request_id TEXT PRIMARY KEY, groupbuy_id INTEGER, user_id TEXT,
                                         qty INTEGER, status TEXT, created_ms BIGINT, enqueued_ms BIGINT,
                                         processed_ms BIGINT, requeued INTEGER DEFAULT 0,
                                         idempotency_key TEXT, UNIQUE (user_id, idempotency_key));
CREATE TABLE IF NOT EXISTS orders(request_id TEXT PRIMARY KEY, groupbuy_id INTEGER, user_id TEXT, qty INTEGER,
                                  title TEXT, price INTEGER, confirmed_ms BIGINT, receipt_key TEXT);
CREATE TABLE IF NOT EXISTS notifications(ref TEXT PRIMARY KEY, kind TEXT, sent_ms BIGINT);
CREATE TABLE IF NOT EXISTS stats(name TEXT PRIMARY KEY, value BIGINT);
CREATE INDEX IF NOT EXISTS jr_status ON join_requests(status, enqueued_ms);
CREATE INDEX IF NOT EXISTS jr_user ON join_requests(user_id, created_ms);
"""


def close_job(groupbuy_id: int) -> str:
    """The q:delayed member for a group-buy's closing: one job per group-buy, however often it is added."""
    return json.dumps({"type": "close", "groupbuy_id": groupbuy_id})


def connect() -> psycopg.Connection:
    """One connection per thread, reused; a broken one is replaced on the next call."""
    db = getattr(_local, "db", None)
    if db is None or db.closed or db.broken:
        db = psycopg.connect(DATABASE_URL, autocommit=True, prepare_threshold=None, connect_timeout=5)
        _local.db = db
    return db


def init_schema(db: psycopg.Connection, reset: bool = False):
    with db.transaction():
        db.execute(SCHEMA)
        if reset:
            db.execute("TRUNCATE groupbuys, join_requests, orders, notifications, stats")


def bump(db: psycopg.Connection, name: str, n: int = 1):
    db.execute("INSERT INTO stats(name, value) VALUES (%s, %s) ON CONFLICT(name) DO UPDATE SET value=stats.value+%s",
               (name, n, n))
