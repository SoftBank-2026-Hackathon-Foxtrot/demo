import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app import chat, order_demo


def test_stock_bounds_and_product_defaults():
    assert order_demo.OrderBatch(count=1).product_id == order_demo.PRODUCT_ID
    for value in (0, -1, 1_000_001, 1.5):
        with pytest.raises(ValueError):
            order_demo.StockSetup(stock=value)


def test_setup_retry_uses_the_same_product_and_does_not_overwrite_stock():
    from unittest.mock import MagicMock
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (123,)
    with patch.dict("os.environ", {"ENABLE_ORDER_DEMO": "1"}), patch.object(order_demo, "connect", return_value=db), patch.object(order_demo, "snapshot", side_effect=lambda product_id, **kwargs: {"product_id": product_id}):
        first = order_demo.prepare(25, "tester", "same-key")
        second = order_demo.prepare(25, "tester", "same-key")
        other = order_demo.prepare(25, "tester", "new-key")
    assert first == second
    assert first != other
    assert all("DO NOTHING" in call.args[0] for call in db.execute.call_args_list)


def test_disabled_api_reports_configuration_instead_of_silent_numbers():
    from app import main
    async def check():
        with patch.dict("os.environ", {"ENABLE_ORDER_DEMO": "0"}), patch.object(main, "user_of", return_value="tester"):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url="http://test") as client:
                response = await client.get("/api/live/orders")
                assert response.status_code == 404
                assert "disabled" in response.json()["detail"]
    import asyncio
    asyncio.run(check())


def test_message_source_is_server_assigned_not_inferred_from_name():
    import asyncio
    async def check():
        client = AsyncMock()
        with patch.object(chat, "save_message", return_value={"id":"m","user":"공구봇 1","text":"안녕","at":1}), patch("app.workload.ENABLED", False):
            await chat.publish_message(client, "m", "공구봇 1", "안녕")
            assert json.loads(client.publish.call_args.args[1])["source"] == "human"
            await chat.publish_message(client, "m", "공구봇 1", "안녕", is_bot=True)
            assert json.loads(client.publish.call_args.args[1])["source"] == "bot"
    asyncio.run(check())
