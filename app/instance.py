"""The name one process gives itself to the platform: the control plane's workload reports and the
object-migration route both count processes by it."""
import os
import socket


def instance_id() -> str:
    """Host, container (WORKLOAD_INSTANCE) and PID. Two worker containers on the same host network
    both run as PID 1, so the PID alone repeats."""
    parts = [socket.gethostname(), os.environ.get("WORKLOAD_INSTANCE", ""), str(os.getpid())]
    return "-".join(part for part in parts if part)
