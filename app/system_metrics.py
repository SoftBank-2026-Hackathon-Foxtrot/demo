"""Container resource metrics. One exporter per container, never per Uvicorn worker."""

from __future__ import annotations

import atexit
import fcntl
import logging
import os
import socket
import threading
import time
from uuid import uuid4
from pathlib import Path

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

log = logging.getLogger(__name__)


def cgroup_paths(proc: Path) -> dict[str, Path]:
    """Resolve this process's cgroup, including hosts with a shared cgroup mount."""
    result = {}
    try:
        memberships = {}
        for line in (proc / "self/cgroup").read_text().splitlines():
            _, controllers, path = line.split(":", 2)
            for controller in controllers.split(","):
                memberships[controller] = Path(path)
        for line in (proc / "self/mountinfo").read_text().splitlines():
            before, after = line.split(" - ", 1)
            fields, filesystem = before.split(), after.split()
            if filesystem[0] not in {"cgroup", "cgroup2"}:
                continue
            controllers = (
                [""] if filesystem[0] == "cgroup2" else filesystem[2].split(",")
            )
            for controller in controllers:
                if controller not in memberships:
                    continue
                try:
                    relative = memberships[controller].relative_to(Path(fields[3]))
                except ValueError:
                    continue
                if ".." not in relative.parts:
                    result[controller] = Path(fields[4]) / relative
    except (OSError, ValueError, IndexError):
        return {}
    return result


def sample(root: Path | None = None, proc: Path = Path("/proc")) -> dict[str, float]:
    """Omit unavailable counters, including unsupported serverless kernel interfaces."""
    values = {"collection": 1.0}
    paths = cgroup_paths(proc) if root is None else {}
    v2 = "" in paths if root is None else (root / "cgroup.controllers").exists()

    def text(path):
        if root is not None:
            return (root / path).read_text().strip()
        controller, filename = ("", path) if v2 else path.split("/", 1)
        return (paths[controller] / filename).read_text().strip()

    def positive(value):
        number = float(value)
        if not 0 < number < 2**60:
            raise ValueError("unbounded resource")
        return number

    def read(names, function):
        try:
            result = function()
            values.update(zip(names, result, strict=True))
        except (OSError, ValueError, KeyError, IndexError):
            pass

    if v2:
        read(
            ["cpu_seconds"],
            lambda: [
                float(
                    dict(line.split() for line in text("cpu.stat").splitlines())[
                        "usage_usec"
                    ]
                )
                / 1e6
            ],
        )
        read(
            ["cpu_limit"],
            lambda: [
                positive(text("cpu.max").split()[0])
                / positive(text("cpu.max").split()[1])
            ],
        )
        read(["memory_bytes"], lambda: [float(text("memory.current"))])
        read(["memory_limit"], lambda: [positive(text("memory.max"))])

        def disk():
            counters = [
                dict(item.split("=") for item in line.split()[1:])
                for line in text("io.stat").splitlines()
            ]
            if not counters:
                raise ValueError("no disk counters")
            return [
                sum(float(row[key]) for row in counters) for key in ("rbytes", "wbytes")
            ]

        read(["disk_read", "disk_write"], disk)
    else:
        read(["cpu_seconds"], lambda: [float(text("cpuacct/cpuacct.usage")) / 1e9])
        read(
            ["cpu_limit"],
            lambda: [
                positive(text("cpu/cpu.cfs_quota_us"))
                / positive(text("cpu/cpu.cfs_period_us"))
            ],
        )
        read(["memory_bytes"], lambda: [float(text("memory/memory.usage_in_bytes"))])
        read(["memory_limit"], lambda: [positive(text("memory/memory.limit_in_bytes"))])

        def disk_v1():
            rows = [
                line.split()
                for line in text("blkio/blkio.throttle.io_service_bytes").splitlines()
            ]
            if not any(len(row) == 3 for row in rows):
                raise ValueError("no disk counters")
            return [
                sum(
                    float(row[2])
                    for row in rows
                    if len(row) == 3 and row[1] == direction
                )
                for direction in ("Read", "Write")
            ]

        read(["disk_read", "disk_write"], disk_v1)
    try:
        interfaces = [
            line.split(":", 1)
            for line in (proc / "net/dev").read_text().splitlines()[2:]
        ]
        rows = [raw.split() for name, raw in interfaces if name.strip() != "lo"]
        if rows:
            values.update(
                network_receive=sum(float(row[0]) for row in rows),
                network_transmit=sum(float(row[8]) for row in rows),
            )
    except (OSError, ValueError, IndexError):
        pass
    return values


class RuntimeMetrics:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None
        self.provider = None
        self.lock_file = None

    def start(self):
        if (
            self.thread
            or os.getenv("OTEL_SYSTEM_METRICS") != "container"
            or not all(
                os.getenv(key)
                for key in (
                    "OTEL_EXPORTER_OTLP_ENDPOINT",
                    "OTEL_APPLICATION_ID",
                    "OTEL_OWNER_ID",
                    "OTEL_DEPLOYMENT_ID",
                )
            )
            or os.getenv("OTEL_SDK_DISABLED", "").lower() == "true"
        ):
            return
        self.thread = threading.Thread(
            target=self._run, name="otel-system", daemon=True
        )
        self.thread.start()
        atexit.register(self.stop)

    def _run(self):
        # Followers retry so a restarted API worker can take over the exporter.
        try:
            with open("/tmp/foxtrot-system-metrics.lock", "a") as lock:
                while not self.stop_event.is_set():
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        self.stop_event.wait(5)
                if self.stop_event.is_set():
                    return
                instance = socket.gethostname() + "-" + uuid4().hex[:8]
                resource = Resource.create(
                    {
                        "service.name": "foxtrot-app-runtime",
                        "application.id": os.getenv("OTEL_APPLICATION_ID", "goods"),
                        "deployment.environment.name": os.getenv(
                            "OTEL_DEPLOYMENT_ENVIRONMENT",
                            os.getenv("SERVED_BY", "unknown"),
                        ),
                        "service.instance.id": instance,
                        "foxtrot.owner.id": os.environ["OTEL_OWNER_ID"],
                        "deployment.id": os.environ["OTEL_DEPLOYMENT_ID"],
                        "app.role": os.getenv(
                            "OTEL_APP_ROLE", os.getenv("WORKLOAD_ACTOR", "app")
                        ),
                        "measurement.scope": "container",
                        "network.scope": os.getenv("OTEL_NETWORK_SCOPE", "container"),
                    }
                )
                self.provider = MeterProvider(
                    resource=resource,
                    metric_readers=[
                        PeriodicExportingMetricReader(
                            OTLPMetricExporter(timeout=2),
                            export_interval_millis=10000,
                            export_timeout_millis=3000,
                        )
                    ],
                )
                meter = self.provider.get_meter("foxtrot.system", "1")
                # Cache one coherent snapshot per collection cycle.
                cache, at = {}, 0.0

                def observe(name):
                    nonlocal cache, at
                    now = time.monotonic()
                    if now - at > 1:
                        cache, at = sample(), now
                        if (
                            os.getenv("OTEL_NETWORK_SCOPE") == "app-instance"
                            and os.getenv("OTEL_APP_ROLE") != "api"
                        ):
                            cache.pop("network_receive", None)
                            cache.pop("network_transmit", None)
                    return [Observation(cache[name])] if name in cache else []

                counters = {
                    "cpu_seconds",
                    "disk_read",
                    "disk_write",
                    "network_receive",
                    "network_transmit",
                }
                for name in (
                    "cpu_seconds",
                    "cpu_limit",
                    "memory_bytes",
                    "memory_limit",
                    "disk_read",
                    "disk_write",
                    "collection",
                    "network_receive",
                    "network_transmit",
                ):
                    factory = (
                        meter.create_observable_counter
                        if name in counters
                        else meter.create_observable_gauge
                    )
                    factory(
                        "foxtrot.runtime." + name,
                        callbacks=[lambda _, key=name: observe(key)],
                    )
                self.stop_event.wait()
                self.provider.shutdown(timeout_millis=3000)
        except Exception:
            log.warning("Container metrics unavailable")

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=4)


runtime_metrics = RuntimeMetrics()
