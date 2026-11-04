"""The app storage module of object-migration, in Python (docs/app-storage.md there; the Go
reference is its client package).

While a migration of the receipt bucket runs, the migration server decides where this process
writes and in which order it reads. The route is asked for about every second with the
generation in use; the server moves on only once every live app reports the new one. A route
not refreshed for the lease (5 s, at most half the server's APP_TTL) fails requests: other apps
may have moved on. Once the migration is over the route no longer changes and needs no lease.

Which migration: OBJECT_MIGRATION_ID, or the first line of OBJECT_MIGRATION_ID_FILE, read again
every second so a migration created while the app runs is picked up. The app must be following
it before the switch: the server does not wait for an app it has never heard from.

The app never deletes receipts, so the delete half of the protocol is not here.
"""
import json
import logging
import os
import socket
import threading
import time
import urllib.parse
import urllib.request

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

log = logging.getLogger("objroute")

INTERVAL_S = 1.0
RETRY_S = 0.2
LEASE_S = 5.0
TERMINAL = {"COMPLETED", "ROLLED_BACK", "ABORTED", "FAILED"}
# A request started inside the lease must end before the server stops waiting (APP_TTL, 10 s):
# 5 s lease + at most 1 s connect + 2 s read.
_BUCKET_CONFIG = Config(signature_version="s3v4", s3={"addressing_style": "path"}, connect_timeout=1,
                        read_timeout=2, retries={"max_attempts": 1})


class StaleRoute(Exception):
    """The route could not be refreshed for longer than the lease while a migration runs."""


class NotFound(Exception):
    pass


def _env(kind: str, name: str) -> str | None:
    return os.environ.get(f"STORAGE_{kind.upper()}_{name}")


def open_bucket(e: dict):
    """A boto3 client for one route endpoint, with this app's own credentials.

    s3: the endpoint's region; STORAGE_S3_ENDPOINT overrides the URL (local tests).
    gcs: the S3-compatible XML API with HMAC keys (STORAGE_GCS_ACCESS_KEY_ID / _SECRET_ACCESS_KEY).
    seaweedfs: the endpoint's url, keys in STORAGE_SEAWEEDFS_ACCESS_KEY_ID / _SECRET_ACCESS_KEY.
    Without STORAGE_<KIND>_ACCESS_KEY_ID the SDK's default chain is used.
    """
    kind = e["kind"]
    url = _env(kind, "ENDPOINT") or {"gcs": "https://storage.googleapis.com", "seaweedfs": e.get("url")}.get(kind)
    keys = {}
    if _env(kind, "ACCESS_KEY_ID"):
        keys = {"aws_access_key_id": _env(kind, "ACCESS_KEY_ID"),
                "aws_secret_access_key": _env(kind, "SECRET_ACCESS_KEY")}
    return boto3.client("s3", endpoint_url=url or None, region_name=e.get("region") or "us-east-1",
                        config=_BUCKET_CONFIG, **keys)


def _key(e: dict) -> tuple:
    return e["kind"], e["bucket"], e.get("region", ""), e.get("url", "")


class Store:
    """Follows one migration's route in a background thread. Thread-safe."""

    def __init__(self, server: str, app: str | None = None, opener=open_bucket):
        self.server = server.rstrip("/")
        self.app = app or f"{socket.gethostname()}-{os.getpid()}"
        self.opener = opener
        self.mu = threading.Lock()
        self.migration: str | None = None
        self.route: dict | None = None
        self.buckets: dict = {}
        self.in_flight: dict[int, int] = {}   # requests running, by the generation they use
        self.lease_until = 0.0
        self.last_error = ""
        self._thread: threading.Thread | None = None

    # ---- following the route ------------------------------------------------------
    def start(self):
        with self.mu:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="objroute", daemon=True)
                self._thread.start()

    def _run(self):
        while True:
            try:
                self.refresh()
                wait = INTERVAL_S
            except Exception as e:  # noqa: BLE001  the server away: keep asking, the lease decides
                with self.mu:
                    if str(e) != self.last_error:
                        log.warning("route refresh failed: %s", e)
                    self.last_error = str(e)
                wait = RETRY_S
            time.sleep(wait)

    def _migration_id(self) -> str | None:
        if mid := os.environ.get("OBJECT_MIGRATION_ID"):
            return mid
        path = os.environ.get("OBJECT_MIGRATION_ID_FILE")
        if path:
            try:
                with open(path) as f:
                    return f.readline().strip() or None
            except FileNotFoundError:
                return None
        return None

    def applied(self) -> int:
        """The oldest generation a running request still uses: until it ends, it may write where
        that route said."""
        with self.mu:
            gen = self.route["generation"] if self.route else 0
            return min([gen, *[g for g, n in self.in_flight.items() if n > 0]])

    def refresh(self):
        mid = self._migration_id()
        if not mid:
            with self.mu:
                self.migration, self.route = None, None
            return
        with self.mu:
            new = mid != self.migration
        for _ in range(2):   # a new generation is reported at once, not a second later
            sent = time.monotonic()
            # A new migration takes over only once its first route is in hand: until then
            # requests keep using what they used.
            r = self._fetch(mid, 0 if new else self.applied())
            for e in [r["write"], *r["read"]]:   # a route is used only once all its buckets can be
                if _key(e) not in self.buckets:
                    self.buckets[_key(e)] = self.opener(e)
            ttl = (r.get("appTtlMs") or 0) / 1000
            lease = min(LEASE_S, ttl / 2) if ttl > 0 else LEASE_S
            with self.mu:
                if new:
                    self.migration, self.route = mid, None
                    new = False
                changed = not self.route or self.route["generation"] != r["generation"]
                if changed:
                    log.info("object route gen %s (%s): write %s, read %s", r["generation"], r["phase"],
                             r["write"]["bucket"], [e["bucket"] for e in r["read"]])
                self.route, self.lease_until, self.last_error = r, sent + lease, ""
            if not changed:
                return

    def _fetch(self, mid: str, applied: int) -> dict:
        q = urllib.parse.urlencode({"app": self.app, "applied": applied})
        url = f"{self.server}/v1/migrations/{urllib.parse.quote(mid, safe='')}/routing?{q}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            r = json.load(resp)
        if not r.get("read") or not (r.get("write") or {}).get("bucket"):
            raise ValueError("routing: incomplete route")
        return r

    # ---- requests -----------------------------------------------------------------
    def following(self) -> bool:
        """Whether a migration route is in force (otherwise the caller uses its own buckets)."""
        with self.mu:
            return self.migration is not None

    def _begin(self) -> dict:
        with self.mu:
            r = self.route
            if r is None or (r["phase"] not in TERMINAL and time.monotonic() > self.lease_until):
                raise StaleRoute(self.last_error or "no route yet")
            self.in_flight[r["generation"]] = self.in_flight.get(r["generation"], 0) + 1
            return r

    def _end(self, r: dict):
        with self.mu:
            g = r["generation"]
            self.in_flight[g] -= 1
            if self.in_flight[g] == 0:
                del self.in_flight[g]

    def put(self, key: str, body: bytes, content_type: str = "application/octet-stream") -> str:
        """Writes to the route's write bucket; returns that bucket's name."""
        r = self._begin()
        try:
            e = r["write"]
            self.buckets[_key(e)].put_object(Bucket=e["bucket"], Key=key, Body=body, ContentType=content_type)
            return e["bucket"]
        finally:
            self._end(r)

    def get(self, key: str) -> tuple[bytes, str]:
        """The object and the bucket it came from, trying the route's read buckets in order."""
        r = self._begin()
        try:
            for e in r["read"]:
                try:
                    obj = self.buckets[_key(e)].get_object(Bucket=e["bucket"], Key=key)
                    return obj["Body"].read(), e["bucket"]
                except ClientError as err:
                    if err.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
                        continue   # not copied there yet: the next bucket
                    raise
            raise NotFound(key)
        finally:
            self._end(r)
