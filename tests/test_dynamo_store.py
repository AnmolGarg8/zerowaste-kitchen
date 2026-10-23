"""Tests for DynamoDBStore using moto."""
from datetime import date, timedelta
import os
import boto3
from moto import mock_aws
import pytest

from zerowaste.dynamo_store import DynamoDBStore
from zerowaste.server import build_server

TODAY = date(2026, 10, 21)


@pytest.fixture
def store():
    with mock_aws():
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        s = DynamoDBStore(table_name="test-kitchen-table", household="household-1")
        yield s


def test_add_and_expiring_order(store):
    store.add("spinach", today=TODAY)
    store.add("chicken", today=TODAY)
    store.add("onion", today=TODAY)

    rows = store.expiring(3, today=TODAY)
    assert [r["name"] for r in rows] == ["chicken"]

    rows = store.expiring(6, today=TODAY)
    assert [r["name"] for r in rows] == ["chicken", "spinach"]


def test_expired_items_are_reported_first(store):
    store.add("milk", today=TODAY - timedelta(days=9))  # expired 2 days ago
    store.add("spinach", today=TODAY)

    rows = store.expiring(3, today=TODAY)
    assert rows[0]["name"] == "milk" and rows[0]["days_left"] == -2


def test_use_marks_soonest_and_reports_missing(store):
    store.add("tomato", today=TODAY, price=30)
    out = store.close(["tomatoes", "caviar"], "used", today=TODAY)
    assert out == {"done": ["tomato"], "not_found": ["caviar"]}
    assert store.available("tomato", today=TODAY) is None


def test_available_ignores_expired(store):
    store.add("milk", today=TODAY - timedelta(days=30))
    assert store.available("milk", today=TODAY) is None


def test_report_counts_saved_and_wasted(store):
    store.add("spinach", today=TODAY, price=40)
    store.add("chicken", today=TODAY, price=200)
    store.add("milk", today=TODAY - timedelta(days=10), price=60)  # expired unused
    store.close(["spinach"], "used", today=TODAY)
    store.close(["chicken"], "wasted", today=TODAY)

    r = store.report(7, today=TODAY)
    assert r["used_before_expiry"] == 1 and r["money_saved"] == 40
    assert r["wasted"] == 2 and r["money_wasted"] == 260


def test_build_server_dynamodb_mode(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.setenv("ZW_STORE", "dynamodb")
        monkeypatch.setenv("ZW_TABLE", "test-server-table")
        monkeypatch.setenv("ZW_HOUSEHOLD", "server-household")

        server = build_server()
        assert server.name == "ZeroWaste Kitchen"
