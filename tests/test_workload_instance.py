"""Every reporting process has its own instance ID, also when containers share a host network."""

from app import workload


def test_instance_id_names_the_container(monkeypatch):
    monkeypatch.setattr(workload.socket, "gethostname", lambda: "vm-1")
    monkeypatch.setattr(workload.os, "getpid", lambda: 1)
    monkeypatch.setenv("WORKLOAD_INSTANCE", "app-worker-1")
    first = workload.instance_id()
    monkeypatch.setenv("WORKLOAD_INSTANCE", "app-worker-2")
    assert first == "vm-1-app-worker-1-1"
    assert workload.instance_id() == "vm-1-app-worker-2-1"


def test_instance_id_without_a_container_name(monkeypatch):
    monkeypatch.setattr(workload.socket, "gethostname", lambda: "vm-1")
    monkeypatch.setattr(workload.os, "getpid", lambda: 42)
    monkeypatch.delenv("WORKLOAD_INSTANCE", raising=False)
    assert workload.instance_id() == "vm-1-42"
