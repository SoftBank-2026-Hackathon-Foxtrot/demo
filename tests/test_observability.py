import unittest
from unittest.mock import patch

import httpx

from app.workload import Workload


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_is_uncached_and_identifies_the_serving_app(self):
        from app.main import app
        with patch("app.workload.ENABLED", False):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/migration-probe")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertTrue(response.headers["x-served-by"])

    async def test_probe_still_answers_when_the_web_build_is_served(self):
        # The image serves web/dist at "/"; a route registered after that mount would be
        # swallowed by it and answer 404.
        import importlib
        import shutil
        from pathlib import Path

        import app.main as main

        dist = Path(main.__file__).parent.parent / "web" / "dist"
        created = not dist.exists()
        if created:
            dist.mkdir(parents=True)
            (dist / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
        try:
            served = importlib.reload(main).app
            with patch("app.workload.ENABLED", False):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=served), base_url="http://test") as client:
                    probe = await client.get("/api/migration-probe")
                    page = await client.get("/")
            self.assertEqual(probe.status_code, 200)
            self.assertEqual(probe.json(), {"ok": True})
            self.assertEqual(page.status_code, 200)
        finally:
            if created:
                shutil.rmtree(dist)
            importlib.reload(main)

    def test_websockets_do_not_keep_business_hold_open(self):
        workload = Workload()
        workload.socket_opened()
        workload.socket_opened()
        self.assertEqual(workload.active_websockets, 2)
        self.assertEqual(workload.in_flight, 0)
        workload.socket_closed()
        workload.socket_closed()
        self.assertEqual(workload.active_websockets, 0)
