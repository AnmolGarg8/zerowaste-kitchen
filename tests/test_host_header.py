"""Test that deployed hostnames (e.g. Lambda Function URLs) are accepted when ZW_HOST=0.0.0.0."""
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url(tmp_path_factory):
    port = _free_port()
    env = {
        **os.environ,
        "ZW_PORT": str(port),
        "ZW_HOST": "0.0.0.0",
        "ZW_DB": str(tmp_path_factory.mktemp("db") / "t.db"),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "zerowaste.server"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
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
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_deployed_host_header_accepted(server_url):
    """Assert that a request with a deployed Host header is NOT rejected with 421 or 403."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
        "Host": "abc123.lambda-url.us-east-1.on.aws",
    }
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test-host-header", "version": "0.1"},
        },
    }

    res = httpx.post(server_url, json=init_req, headers=headers)
    assert res.status_code not in (421, 403), (
        f"Request was rejected with transport security error {res.status_code}: {res.text}"
    )
    assert res.status_code == 200, f"Expected 200 OK, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["result"]["serverInfo"]["name"] == "ZeroWaste Kitchen"
