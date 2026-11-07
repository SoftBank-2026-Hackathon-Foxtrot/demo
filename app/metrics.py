"""Read-only demo measurements. Baselines live in the browser, outside migrated stores."""
import time
from typing import Annotated

from pydantic import BaseModel, Field

from .db import connect

TABLES = {"chat": ("chat_messages", "id"), "orders": ("orders", "request_id"),
          "requests": ("join_requests", "request_id"), "goods": ("groupbuys", "id")}
SAMPLE_LIMIT = 500
RecordId = Annotated[str, Field(max_length=128)]


class Baseline(BaseModel):
    chat: list[RecordId] = Field(default_factory=list, max_length=SAMPLE_LIMIT)
    orders: list[RecordId] = Field(default_factory=list, max_length=SAMPLE_LIMIT)
    requests: list[RecordId] = Field(default_factory=list, max_length=SAMPLE_LIMIT)
    goods: list[RecordId] = Field(default_factory=list, max_length=SAMPLE_LIMIT)


class Measurement(BaseModel):
    since_ms: int = Field(ge=0)
    baseline: Baseline | None = None


def snapshot():
    db = connect()
    # One consistent snapshot across all tables; never seed or mutate app data.
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        ids = {key: [str(row[0]) for row in db.execute(
            f"SELECT {column} FROM {table} ORDER BY {column} LIMIT %s", (SAMPLE_LIMIT,)).fetchall()]
            for key, (table, column) in TABLES.items()}
    return {"at": int(time.time() * 1000), "ids": ids, "limit_per_table": SAMPLE_LIMIT}


def inspect(measurement: Measurement):
    db = connect()
    cutoff = int(time.time() * 1000) - 2000  # allow delivery to finish before judging it
    rows = db.execute("SELECT id FROM chat_messages WHERE room=%s AND created_ms >= %s AND created_ms <= %s "
                      "ORDER BY created_ms DESC, id DESC LIMIT 1000",
                      ("chiikawa-live", measurement.since_ms, cutoff)).fetchall()
    retention = None
    if measurement.baseline is not None:
        retention = {}
        for key, (table, column) in TABLES.items():
            ids = list(set(getattr(measurement.baseline, key)))
            if key == "goods":
                # Goods use integer keys. Invalid IDs simply fail the existence check.
                ids = [int(value) for value in ids if value.isascii() and value.isdigit() and len(value) < 10]
            retained = db.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ANY(%s)", (ids,)).fetchone()[0]
            retention[key] = {"retained": retained, "expected": len(set(getattr(measurement.baseline, key)))}
    return {"at": int(time.time() * 1000), "chat_ids": [row[0] for row in rows],
            "chat_sample_limit": 1000, "delivery_grace_ms": 2000, "retention": retention}
