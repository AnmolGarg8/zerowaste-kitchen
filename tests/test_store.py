from datetime import date, timedelta

from zerowaste.shelf_life import lookup, normalize
from zerowaste.store import Store

TODAY = date(2026, 10, 21)


def test_normalize_and_lookup():
    assert normalize("Tomatoes") == "tomato"
    assert normalize("Berries") == "berry"
    assert normalize("Hummus") == "hummus"
    assert lookup("baby spinach") == (5, False)
    assert lookup("dragonfruit") == (7, True)  # unknown -> flagged estimate


def test_add_and_expiring_order():
    s = Store()
    s.add("spinach", today=TODAY)
    s.add("chicken", today=TODAY)
    s.add("onion", today=TODAY)
    rows = s.expiring(3, today=TODAY)
    assert [r["name"] for r in rows] == ["chicken"]
    rows = s.expiring(6, today=TODAY)
    assert [r["name"] for r in rows] == ["chicken", "spinach"]


def test_expired_items_are_reported_first():
    s = Store()
    s.add("milk", today=TODAY - timedelta(days=9))  # expired 2 days ago
    s.add("spinach", today=TODAY)
    rows = s.expiring(3, today=TODAY)
    assert rows[0]["name"] == "milk" and rows[0]["days_left"] == -2


def test_use_marks_soonest_and_reports_missing():
    s = Store()
    s.add("tomato", today=TODAY, price=30)
    out = s.close(["tomatoes", "caviar"], "used", today=TODAY)
    assert out == {"done": ["tomato"], "not_found": ["caviar"]}
    assert s.available("tomato", today=TODAY) is None


def test_available_ignores_expired():
    s = Store()
    s.add("milk", today=TODAY - timedelta(days=30))
    assert s.available("milk", today=TODAY) is None


def test_report_counts_saved_and_wasted():
    s = Store()
    s.add("spinach", today=TODAY, price=40)
    s.add("chicken", today=TODAY, price=200)
    s.add("milk", today=TODAY - timedelta(days=10), price=60)  # expired unused
    s.close(["spinach"], "used", today=TODAY)
    s.close(["chicken"], "wasted", today=TODAY)
    r = s.report(7, today=TODAY)
    assert r["used_before_expiry"] == 1 and r["money_saved"] == 40
    assert r["wasted"] == 2 and r["money_wasted"] == 260
