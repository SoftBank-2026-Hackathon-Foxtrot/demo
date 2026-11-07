import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.system_metrics import RuntimeMetrics, sample


class SystemMetricsTests(unittest.TestCase):
    def test_cgroup_v2_and_namespace_counters(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, value in {
                "cgroup.controllers": "cpu memory io",
                "cpu.stat": "usage_usec 1234000\n",
                "cpu.max": "200000 100000",
                "memory.current": "1024",
                "memory.max": "4096",
                "io.stat": "8:0 rbytes=11 wbytes=22\n8:1 rbytes=10 wbytes=20",
            }.items():
                (root / name).write_text(value)
            (root / "net").mkdir()
            (root / "net/dev").write_text(
                "header\nheader\nlo: 100 0 0 0 0 0 0 0 100 0\neth0: 123 0 0 0 0 0 0 0 456 0\n"
            )
            result = sample(root, root)
            self.assertEqual(result["cpu_seconds"], 1.234)
            self.assertEqual(result["cpu_limit"], 2)
            self.assertEqual(result["memory_limit"], 4096)
            self.assertEqual(result["disk_read"], 21)
            self.assertEqual(result["network_receive"], 123)
            (root / "cpu.max").write_text("max 100000")
            (root / "memory.max").write_text("max")
            result = sample(root, root)
            self.assertNotIn("cpu_limit", result)
            self.assertNotIn("memory_limit", result)
            self.assertEqual(result["memory_bytes"], 1024)
            self.assertNotIn("disk_used", result)
            self.assertNotIn("disk_limit", result)

    def test_missing_counters_are_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            result = sample(Path(folder), Path(folder))
            for name in ("cpu_seconds", "memory_bytes", "disk_read", "network_receive"):
                self.assertNotIn(name, result)

    def test_disabled_without_explicit_container_scope(self):
        with patch.dict(
            "os.environ",
            {
                "OTEL_SYSTEM_METRICS": "host",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
            },
        ):
            collector = RuntimeMetrics()
            collector.start()
            self.assertIsNone(collector.thread)

    def test_requires_owner_and_deployment_identity(self):
        with patch.dict(
            "os.environ",
            {
                "OTEL_SYSTEM_METRICS": "container",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
                "OTEL_APPLICATION_ID": "goods",
            },
            clear=True,
        ):
            collector = RuntimeMetrics()
            collector.start()
            self.assertIsNone(collector.thread)

    def test_resolves_process_cgroup_without_reading_host_totals(self):
        from app.system_metrics import cgroup_paths

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "self").mkdir()
            (root / "self/cgroup").write_text("0::/docker/app-one\n")
            (root / "self/mountinfo").write_text(
                "1 2 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n"
            )
            self.assertEqual(
                cgroup_paths(root)[""], Path("/sys/fs/cgroup/docker/app-one")
            )
            (root / "self/mountinfo").write_text(
                "1 2 0:1 /docker/app-one /sys/fs/cgroup rw - cgroup2 cgroup rw\n"
            )
            self.assertEqual(cgroup_paths(root)[""], Path("/sys/fs/cgroup"))
            (root / "self/cgroup").write_text("0::/docker/app-other\n")
            self.assertEqual(cgroup_paths(root), {})
