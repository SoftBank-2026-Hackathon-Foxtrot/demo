"""Stopping the work on the platform's word, for the DB cutover (control-plane docs/app-integration.md).

Every process reports to the platform on its own: each uvicorn worker of the API and each queue
worker. The reply says RUN or HOLD. On HOLD the API holds new requests and chat messages at a
gate, the queue workers take no new batch, and each process reports HELD once nothing of its own
is still running. The platform moves the DB only after every expected process reports HELD.

The app asks the platform, not the other way round: the app VMs take no inbound calls, and the
order cannot travel through the DB or Redis being moved.

Off unless CONTROL_PLANE_URL is set, so the app runs on its own as before.

  CONTROL_PLANE_URL        http://control-plane.internal:8000
  WORKLOAD_TOKEN           the platform's workload token
  WORKLOAD_ACTOR           this process's role in the seed: goods-aws-api, goods-aws-worker, ...
  WORKLOAD_SCOPE           scope:goods
  WORKLOAD_INSTANCE        this container's name, so containers on one host network (each its own
                           PID 1) report as different processes: <host>-<name>-<pid>
  OBJECT_MIGRATION_ID_FILE where the receipt bucket's migration ID is written for objroute

The same answer also says which Redis route to use (redisroute.py), and every report says which
route this process follows.
"""
import asyncio
import json
import logging
import os
import threading
import time
import urllib.request
from contextlib import asynccontextmanager, contextmanager

from .instance import instance_id
from .telemetry import get_telemetry
from .redisroute import router as redis_router

log = logging.getLogger("workload")

URL = os.environ.get("CONTROL_PLANE_URL", "").rstrip("/")
ENABLED = bool(URL)
GATE_LIMIT_S = 60.0     # under Cloudflare's 100 s, so the user gets an answer, not a dropped request
RETRY_S = 1.0


class HoldTimeout(Exception):
    """The hold lasted longer than a request may wait."""


class Workload:
    def __init__(self) -> None:
        self.actor = os.environ.get("WORKLOAD_ACTOR", "")
        self.scope = os.environ.get("WORKLOAD_SCOPE", "scope:goods")
        self.token = os.environ.get("WORKLOAD_TOKEN", "")
        self.id_file = os.environ.get("OBJECT_MIGRATION_ID_FILE")
        self.lock = threading.Lock()
        self.directed = threading.Event()   # set by the first answer
        self.desired = "RUN"
        self.generation = 0
        self.in_flight = 0
        self.active_websockets = 0
        self.migration_id: str | None = None
        self.thread: threading.Thread | None = None
        self.observation_thread: threading.Thread | None = None
        self.observation_stop = threading.Event()

    # ---- the gate ---------------------------------------------------------------------------
    def _enter(self) -> bool:
        """Counted before the check, under one lock with the report: a request either runs
        before the platform hears HELD, or waits."""
        with self.lock:
            if self.directed.is_set() and self.desired == "RUN":
                self.in_flight += 1
                return True
            return False

    def socket_opened(self):
        with self.lock:
            self.active_websockets += 1

    def socket_closed(self):
        with self.lock:
            self.active_websockets -= 1

    def _leave(self) -> None:
        with self.lock:
            self.in_flight -= 1

    @asynccontextmanager
    async def gate(self):
        """For the API: wait while held, at most GATE_LIMIT_S."""
        if not ENABLED:
            with self.lock:
                self.in_flight += 1
            try:
                with get_telemetry("app").operation("APP_WORK"):
                    yield
            finally:
                self._leave()
            return
        deadline = time.monotonic() + GATE_LIMIT_S
        while not self._enter():
            if time.monotonic() > deadline:
                raise HoldTimeout
            await asyncio.sleep(0.02)
        try:
            with get_telemetry("app").operation("APP_WORK"):
                yield
        finally:
            self._leave()

    @contextmanager
    def working(self):
        """For a queue worker: one batch. Blocks while held, with no limit: nobody is waiting."""
        if not ENABLED:
            with self.lock:
                self.in_flight += 1
            try:
                with get_telemetry("app").operation("APP_WORK"):
                    yield
            finally:
                self._leave()
            return
        while not self._enter():
            time.sleep(0.05)
        try:
            with get_telemetry("app").operation("APP_WORK"):
                yield
        finally:
            self._leave()

    @property
    def ready(self) -> bool:
        """A process that has not heard from the platform yet could miss a hold in force."""
        return not ENABLED or self.directed.is_set()

    # ---- the report -------------------------------------------------------------------------
    def start(self) -> None:
        if get_telemetry("app").enabled and not self.observation_thread:
            self.observation_thread = threading.Thread(target=self._observe, name="otel-workload", daemon=True)
            self.observation_thread.start()
        if not ENABLED or self.thread:
            return
        if not self.actor:
            raise RuntimeError("CONTROL_PLANE_URL is set but WORKLOAD_ACTOR is not")
        self.thread = threading.Thread(target=self._run, name="workload", daemon=True)
        self.thread.start()

    def _observe(self):
        telemetry = get_telemetry("app")
        attrs = {"actor.id": self.actor or "unregistered", "environment": os.getenv("SERVED_BY", "unknown")}
        while not self.observation_stop.is_set():
            with self.lock:
                values = {"inflight": self.in_flight, "activewebsockets": self.active_websockets}
            for key, value in values.items():
                telemetry.measure("foxtrot.app." + key, value, attrs)
            telemetry.measure("foxtrot.app.redis_stale_connections",
                              redis_router.report().get("redisStaleConnections"), attrs)
            self.observation_stop.wait(5)

    def stop_observations(self):
        self.observation_stop.set()
        if self.observation_thread:
            self.observation_thread.join(timeout=2)

    def _run(self) -> None:
        instance = instance_id()
        url = f"{URL}/internal/v1/workloads/{self.scope}/heartbeat"
        failing = False
        while True:
            with self.lock:
                if self.desired == "HOLD":
                    state = "HELD" if self.in_flight == 0 else "HOLDING"
                else:
                    state = "RUNNING"
                report = {"actorId": self.actor, "instanceId": instance, "generation": self.generation,
                          "state": state, "inFlight": self.in_flight,
                          "activeWebSockets": self.active_websockets}
            report |= redis_router.report()
            try:
                answer = self._post(url, report)
            except Exception as e:  # noqa: BLE001  keep the last order: a HOLD never lifts itself
                if not failing:
                    log.warning("heartbeat failed, keeping %s: %s", self.desired, e)
                failing = True
                time.sleep(RETRY_S)
                continue
            if failing:
                log.info("heartbeat back")
            failing = False
            with self.lock:
                if answer["desired"] != self.desired:
                    log.info("platform says %s (generation %s)", answer["desired"], answer["generation"])
                self.desired = answer["desired"]
                self.generation = answer["generation"]
            # Before the first `directed`: the first work of a new process already uses the route
            # in force, so a process started during a migration never connects directly.
            redis_router.apply(answer.get("redisRoute"), answer.get("redisEndpoint"),
                               answer.get("redisRouteGeneration", 0))
            self.directed.set()
            self._follow_object_migration(answer.get("objectMigrationId"))
            time.sleep(answer.get("pollAfterMs", 5000) / 1000)

    def _post(self, url: str, body: dict) -> dict:
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}",
                     **get_telemetry("app").headers()})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def _follow_object_migration(self, migration_id: str | None) -> None:
        """objroute reads this file every second and starts following the route."""
        if not migration_id or migration_id == self.migration_id or not self.id_file:
            return
        partial = f"{self.id_file}.{os.getpid()}"
        with open(partial, "w") as f:
            f.write(migration_id + "\n")
        os.replace(partial, self.id_file)
        self.migration_id = migration_id
        log.info("following object migration %s", migration_id)


workload = Workload()
