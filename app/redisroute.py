"""Which Redis this process talks to, switched while it runs (Redis design 3-8).

Outside a migration the app reaches Redis directly. Before a Redis migration the platform tells every
process, through the workload heartbeat, to go through the central proxy, and after it to go back to
a direct connection on the side that stays. Both ways the two routes reach the same Redis, so moving
is about connections, not data:

  - commands: new ones use a new pool at once; the old pool is closed once nothing on it is in use
  - Pub/Sub (chat.py): subscribe on the new route first, then leave the old one; overlapping messages
    are dropped by their id
  - queue consumers: the same consumer name on the new route; un-acked messages stay pending in the
    same Redis and are read again

Every heartbeat reports the route in use, the order it follows and the connections still open on the
route it left. The platform starts the Redis migration only when every process reports none.

Off unless REDIS_DIRECT_URLS is set: the app then uses REDIS_URL alone, as before.

  REDIS_URL          the default: the direct Redis of this environment (or the proxy, when off)
  REDIS_PROXY_URL    the central proxy, with this process's proxy account
  REDIS_DIRECT_URLS  aws=redis://app-direct:pw@...,gcp=redis://app-direct:pw@...  per environment
"""
import asyncio
import logging
import os
import threading
from collections.abc import Callable
from typing import Any

import redis
import redis.asyncio as aioredis

log = logging.getLogger("redisroute")

DEFAULT_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
PROXY_URL = os.environ.get("REDIS_PROXY_URL", "")
DIRECT_URLS = dict(item.split("=", 1) for item in os.environ.get("REDIS_DIRECT_URLS", "").split(",") if "=" in item)
ENABLED = bool(DIRECT_URLS)
if ENABLED and not PROXY_URL:
    raise RuntimeError("REDIS_DIRECT_URLS is set but REDIS_PROXY_URL is not")


class Router:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.route: str | None = None        # None until the platform says: REDIS_URL
        self.endpoint: str | None = None
        self.generation = 0                  # the route order applied
        self.clients: list[RoutedRedis] = []
        self.watchers: list[Callable[[], None]] = []
        self.async_stale: dict[int, int] = {}   # chat session -> connections left on the old route

    # ---- where to connect -------------------------------------------------------------------
    def url(self) -> str:
        with self.lock:
            return self._url(self.route, self.endpoint)

    def _url(self, route: str | None, endpoint: str | None) -> str:
        if route == "PROXY":
            return PROXY_URL
        if route == "DIRECT" and endpoint:
            return DIRECT_URLS[endpoint]
        return DEFAULT_URL

    def client_name(self) -> str | None:
        """Direct connections carry the actor's name: the platform counts them on the source.
        Never through the proxy, which would pass the name on to its own upstream."""
        with self.lock:
            if not ENABLED or self.route == "PROXY":
                return None
        return f"direct:{os.environ.get('WORKLOAD_ACTOR') or 'app'}"

    def state(self) -> tuple[int, str]:
        """(route order applied, url) read together, for a session deciding whether to move."""
        with self.lock:
            return self.generation, self._url(self.route, self.endpoint)

    # ---- the platform's order ----------------------------------------------------------------
    def apply(self, route: str | None, endpoint: str | None, generation: int) -> None:
        """Called by the heartbeat thread with each answer."""
        if not ENABLED or route is None:
            return
        if route == "DIRECT" and endpoint and endpoint not in DIRECT_URLS:
            # Reported as not followed: the platform waits, then stops the migration.
            log.error("no direct Redis URL for %s; staying on %s", endpoint, self.route)
            return
        with self.lock:
            if generation == self.generation:
                return
            moved = (route, endpoint) != (self.route, self.endpoint)
            self.route, self.endpoint, self.generation = route, endpoint, generation
            clients, watchers = list(self.clients), list(self.watchers)
        if moved:
            log.info("redis route %s %s (order %s)", route, endpoint or "", generation)
            for client in clients:
                client.switch()
            for wake in watchers:
                wake()

    def report(self) -> dict[str, Any]:
        """What the heartbeat says about Redis. Nothing while off: this process does not switch."""
        if not ENABLED:
            return {}
        for client in list(self.clients):
            client.reap()
        with self.lock:
            stale = sum(client.stale() for client in self.clients) + sum(self.async_stale.values())
            return {"redisRoute": self.route or "DIRECT", "redisRouteGeneration": self.generation,
                    "staleConnections": stale}

    # ---- clients ----------------------------------------------------------------------------
    def client(self, **kwargs: Any) -> "RoutedRedis":
        c = RoutedRedis(self, kwargs)
        with self.lock:
            self.clients.append(c)
        return c

    def watch(self, wake: Callable[[], None]) -> Callable[[], None]:
        """For an async session: `wake` runs on the heartbeat thread when the route moves."""
        with self.lock:
            self.watchers.append(wake)

        def forget() -> None:
            with self.lock:
                self.watchers.remove(wake)
        return forget

    def async_client(self, **kwargs: Any) -> aioredis.Redis:
        return aioredis.Redis.from_url(self.url(), client_name=self.client_name(), **kwargs)

    def mark_stale(self, key: int, count: int) -> None:
        """An async session's connections left on the old route; 0 once they are closed."""
        with self.lock:
            if count:
                self.async_stale[key] = count
            else:
                self.async_stale.pop(key, None)


class RoutedRedis:
    """A redis.Redis whose pool follows the route. Attribute access goes to the current client, so a
    pipeline or a script started on the old route finishes there."""

    def __init__(self, router: Router, kwargs: dict[str, Any]) -> None:
        self._router, self._kwargs = router, kwargs
        self._lock = threading.Lock()
        self._current = self._make()
        self._retired: list[redis.Redis] = []

    def _make(self) -> redis.Redis:
        return redis.Redis.from_url(self._router.url(), client_name=self._router.client_name(), **self._kwargs)

    @property
    def current(self) -> redis.Redis:
        return self._current

    def __getattr__(self, name: str) -> Any:
        return getattr(self._current, name)

    def switch(self) -> None:
        new = self._make()
        with self._lock:
            old, self._current = self._current, new
            self._retired.append(old)
        self.reap()

    def reap(self) -> None:
        """Closes what the old pools no longer use; drops a pool once nothing on it is in use."""
        with self._lock:
            retired = list(self._retired)
        for old in retired:
            pool = old.connection_pool
            pool.disconnect(inuse_connections=False)
            if not pool._in_use_connections:   # noqa: SLF001  no public count in redis-py
                pool.disconnect()
                with self._lock:
                    self._retired.remove(old)

    def stale(self) -> int:
        with self._lock:
            return sum(len(old.connection_pool._in_use_connections) for old in self._retired)  # noqa: SLF001


router = Router()


async def close_when_idle(client: aioredis.Redis, limit_s: float = 5.0) -> None:
    """An old async client is closed once its commands have finished, or after `limit_s`."""
    pool = client.connection_pool
    for _ in range(int(limit_s / 0.05)):
        if not pool._in_use_connections:   # noqa: SLF001
            break
        await asyncio.sleep(0.05)
    await client.aclose()
