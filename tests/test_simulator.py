"""Tests for the browser-based Alexa+ simulator web endpoints."""
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
def base_url(tmp_path_factory):
    port = _free_port()
    env = {
        **os.environ,
        "ZW_PORT": str(port),
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
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_simulator_page_and_healthz(base_url):
    with httpx.Client(base_url=base_url) as client:
        # GET /healthz
        res_health = client.get("/healthz")
        assert res_health.status_code == 200
        assert res_health.json() == {"ok": True}

        # GET /
        res_page = client.get("/")
        assert res_page.status_code == 200
        assert "text/html" in res_page.headers.get("content-type", "")
        html = res_page.text
        assert "Simulated Alexa+" in html
        assert "Protocol inspector" in html
