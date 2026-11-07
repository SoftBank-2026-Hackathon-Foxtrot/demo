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

    def test_websockets_do_not_keep_business_hold_open(self):
        workload = Workload()
        workload.socket_opened()
        workload.socket_opened()
        self.assertEqual(workload.active_websockets, 2)
        self.assertEqual(workload.in_flight, 0)
        workload.socket_closed()
        workload.socket_closed()
        self.assertEqual(workload.active_websockets, 0)
