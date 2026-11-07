"""The Redis route switch of app/redisroute.py against a real Valkey (run on the host, Docker needed).

  python scripts/check_redis_route.py

Both routes reach one throwaway Valkey, as entering and leaving the proxy do: "direct" logs in with
the direct account, "proxy" with another one, standing in for the proxy. Checks that direct
connections carry the actor's name, that a switch moves new commands at once and leaves no named
connection behind, that a command running on the old pool finishes there and is reported as stale
until it does, and that the worker's Lua script follows the route.
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

PORT = 16421
NAME = "route-check"
DIRECT = f"redis://app-direct:direct-pw@127.0.0.1:{PORT}"
PROXY = f"redis://app-proxy:proxy-pw@127.0.0.1:{PORT}"
os.environ.update(REDIS_URL=DIRECT, REDIS_PROXY_URL=PROXY, REDIS_DIRECT_URLS=f"aws={DIRECT}",
                  WORKLOAD_ACTOR="goods-aws-api")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import redis  # noqa: E402
from redis.commands.core import Script  # noqa: E402

from app.redisroute import router  # noqa: E402

results: list[bool] = []


def report(name: str, ok: bool, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def clients(admin: redis.Redis) -> list[dict]:
    return [c for c in admin.client_list() if c.get("user") in ("app-direct", "app-proxy")]


def main():
    docker("rm", "-f", NAME)
    if docker("run", "-d", "--name", NAME, "-p", f"127.0.0.1:{PORT}:6379", "valkey/valkey:8").returncode:
        raise SystemExit("docker run failed")
    try:
        admin = redis.Redis(port=PORT, decode_responses=True)
        for _ in range(50):
            try:
                admin.ping()
                break
            except redis.ConnectionError:
                time.sleep(0.2)
        for user, pw in (("app-direct", "direct-pw"), ("app-proxy", "proxy-pw")):
            admin.execute_command("ACL", "SETUSER", user, "on", f">{pw}", "~*", "&*", "+@all")

        r = router.client(decode_responses=True, socket_timeout=10)
        script = Script(r, "return redis.call('INCR', KEYS[1])")

        router.apply("DIRECT", "aws", 1)
        r.set("k", "1")
        named = [c["name"] for c in clients(admin) if c["user"] == "app-direct"]
        report("직접 연결은 direct:<actor> 이름을 가짐", named and all(n == "direct:goods-aws-api" for n in named), named)
        report("직접 연결 상태 보고", router.report() == {"redisRoute": "DIRECT", "redisRouteGeneration": 1,
                                                    "staleConnections": 0}, router.report())

        # A command still running on the old pool when the route moves (BLPOP waits 1.5 s).
        blocked = threading.Thread(target=lambda: r.current.blpop("never", timeout=1.5))
        blocked.start()
        time.sleep(0.3)
        router.apply("PROXY", None, 2)
        r.set("k", "2")
        during = router.report()
        report("전환 중 옛 경로에서 실행 중인 명령은 stale로 보고", during["staleConnections"] == 1 and
               during["redisRoute"] == "PROXY", during)
        users = {c["user"] for c in clients(admin) if c["cmd"] == "set"}
        report("새 명령은 바로 새 경로로", users == {"app-proxy"}, users)
        blocked.join()
        after = router.report()
        time.sleep(0.3)   # the server drops a closed connection from CLIENT LIST on its next event loop turn
        named =[c["name"] for c in clients(admin) if c["name"].startswith("direct:")]
        report("옛 명령이 끝나면 stale 0, 이름 붙은 직접 연결도 없음", after["staleConnections"] == 0 and not named,
               (after, named))
        proxied = [c["name"] for c in clients(admin) if c["user"] == "app-proxy"]
        report("프록시 경유 연결에는 이름을 붙이지 않음", all(n == "" for n in proxied), proxied)

        report("Lua 스크립트도 현재 경로에서 실행", script(keys=["n"]) == 1 and
               {c["user"] for c in clients(admin) if c["cmd"] in ("evalsha", "eval")} <= {"app-proxy"})
        with r.pipeline(transaction=True) as p:
            p.incr("n").expire("n", 60)
            report("파이프라인(MULTI/EXEC)도 동작", p.execute()[0] == 2)

        router.apply("PROXY", None, 2)
        report("같은 지시는 다시 옮기지 않음", router.report()["redisRouteGeneration"] == 2)
        router.apply("DIRECT", "gcp", 3)
        report("모르는 환경으로의 지시는 따르지 않음(세대가 그대로)", router.report()["redisRouteGeneration"] == 2)
        router.apply("DIRECT", "aws", 4)
        r.get("k")
        report("다시 직접 연결로", router.report()["redisRoute"] == "DIRECT" and
               any(c["name"] == "direct:goods-aws-api" for c in clients(admin)))
    finally:
        docker("rm", "-f", NAME)
    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
