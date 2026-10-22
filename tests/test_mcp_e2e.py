"""End-to-end: real server process, real Streamable HTTP, official MCP client."""
import asyncio
import os
import socket
import subprocess
import sys
import time

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

LATENCY_BUDGET_S = 0.5  # Alexa+ requires < 500 ms round trip for MCP servers


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url(tmp_path_factory):
    port = _free_port()
    env = {**os.environ, "ZW_PORT": str(port),
           "ZW_DB": str(tmp_path_factory.mktemp("db") / "t.db")}
    proc = subprocess.Popen([sys.executable, "-m", "zerowaste.server"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("server did not start")
    yield f"http://127.0.0.1:{port}/mcp"
    proc.terminate()


def test_protocol_and_tool_flow(server_url):
    async def run():
        async with streamablehttp_client(server_url) as (r, w, _):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                assert init.protocolVersion == "2025-11-25"

                names = {t.name for t in (await s.list_tools()).tools}
                assert names == {"add_items", "whats_expiring", "use_items",
                                 "shopping_gap", "waste_report"}

                timings = {}

                async def call(name, args):
                    t0 = time.perf_counter()
                    res = await s.call_tool(name, args)
                    timings[name] = time.perf_counter() - t0
                    assert not res.isError, res
                    return res.structuredContent

                added = await call("add_items", {"items": [
                    {"name": "chicken", "price": 200}, {"name": "spinach", "price": 40},
                    {"name": "yogurt"}]})
                assert "Soonest to expire: chicken" in added["summary"]

                exp = await call("whats_expiring", {"within_days": 3})
                assert exp["items"][0]["name"] == "chicken"

                gap = await call("shopping_gap",
                                 {"ingredients": ["chicken", "spinach", "cream", "garlic"]})
                assert gap["have"] == ["chicken", "spinach"]
                assert gap["missing"] == ["cream", "garlic"]

                used = await call("use_items", {"names": ["spinach"]})
                assert used["done"] == ["spinach"]

                rep = await call("waste_report", {"days": 7})
                assert rep["used_before_expiry"] == 1 and rep["money_saved"] == 40

                slow = {k: v for k, v in timings.items() if v > LATENCY_BUDGET_S}
                assert not slow, f"over 500 ms budget: {slow}"
                return timings

    timings = asyncio.run(run())
    print({k: f"{v*1000:.0f} ms" for k, v in timings.items()})
