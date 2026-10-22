"""SQLite-backed pantry store. Deterministic and fast (no network, no LLM)."""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, timedelta
from typing import Any

from .shelf_life import lookup, normalize

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    norm TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    price REAL,
    added_on TEXT NOT NULL,
    expires_on TEXT NOT NULL,
    estimated INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',   -- active | used | wasted
    closed_on TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status, expires_on);
"""


def _match(item_norm: str, query_norm: str) -> bool:
    """'baby spinach' matches 'spinach'; 'spinach' matches 'baby spinach'."""
    if item_norm == query_norm:
        return True
    iw, qw = set(item_norm.split()), set(query_norm.split())
    return qw <= iw or iw <= qw


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    # -- writes -----------------------------------------------------------
    def add(self, name: str, quantity: float = 1, days_until_expiry: int | None = None,
            price: float | None = None, today: date | None = None) -> dict[str, Any]:
        today = today or date.today()
        if days_until_expiry is None:
            days, estimated = lookup(name)
        else:
            days, estimated = days_until_expiry, False
        expires = today + timedelta(days=days)
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO items(name,norm,quantity,price,added_on,expires_on,estimated)"
                " VALUES (?,?,?,?,?,?,?)",
                (name.strip(), normalize(name), quantity, price, today.isoformat(),
                 expires.isoformat(), int(estimated)),
            )
        return {"id": cur.lastrowid, "name": name.strip(), "quantity": quantity,
                "expires_on": expires.isoformat(), "days_left": days, "estimated": estimated}

    def close(self, names: list[str], outcome: str, today: date | None = None) -> dict[str, list[str]]:
        """Mark the soonest-expiring active item for each name as used/wasted."""
        assert outcome in ("used", "wasted")
        today = today or date.today()
        done: list[str] = []
        missing: list[str] = []
        with self._lock, self._db:
            for q in names:
                qn = normalize(q)
                rows = self._db.execute(
                    "SELECT id, norm, name FROM items WHERE status='active' ORDER BY expires_on, id"
                ).fetchall()
                hit = next((r for r in rows if _match(r["norm"], qn)), None)
                if hit is None:
                    missing.append(q)
                    continue
                self._db.execute("UPDATE items SET status=?, closed_on=? WHERE id=?",
                                 (outcome, today.isoformat(), hit["id"]))
                done.append(hit["name"])
        return {"done": done, "not_found": missing}

    # -- reads ------------------------------------------------------------
    def expiring(self, within_days: int = 3, today: date | None = None) -> list[dict[str, Any]]:
        """Active items expiring within N days (already-expired items come first)."""
        today = today or date.today()
        limit = (today + timedelta(days=within_days)).isoformat()
        rows = self._db.execute(
            "SELECT * FROM items WHERE status='active' AND expires_on<=? ORDER BY expires_on, id",
            (limit,),
        ).fetchall()
        return [self._row(r, today) for r in rows]

    def available(self, name: str, today: date | None = None) -> dict[str, Any] | None:
        """Soonest-expiring unexpired active item matching `name`, or None."""
        today = today or date.today()
        qn = normalize(name)
        rows = self._db.execute(
            "SELECT * FROM items WHERE status='active' AND expires_on>=? ORDER BY expires_on, id",
            (today.isoformat(),),
        ).fetchall()
        hit = next((r for r in rows if _match(r["norm"], qn)), None)
        return self._row(hit, today) if hit else None

    def report(self, days: int = 7, today: date | None = None) -> dict[str, Any]:
        today = today or date.today()
        since = (today - timedelta(days=days)).isoformat()
        q = self._db.execute
        used = q("SELECT COUNT(*) c FROM items WHERE status='used' AND closed_on>=?", (since,)).fetchone()
        saved = q("SELECT COUNT(*) c, COALESCE(SUM(price),0) p FROM items WHERE status='used' AND closed_on>=? AND closed_on<=expires_on", (since,)).fetchone()
        wasted = q("SELECT COUNT(*) c, COALESCE(SUM(price),0) p FROM items WHERE status='wasted' AND closed_on>=?", (since,)).fetchone()
        # Items still sitting in the pantry past their date count as waste too.
        expired = q("SELECT COUNT(*) c, COALESCE(SUM(price),0) p FROM items WHERE status='active' AND expires_on<? AND expires_on>=?", (today.isoformat(), since)).fetchone()
        return {
            "days": days,
            "used": used["c"], "used_before_expiry": saved["c"], "money_saved": saved["p"],
            "wasted": wasted["c"] + expired["c"], "money_wasted": wasted["p"] + expired["p"],
            "expired_unused": expired["c"],
        }

    @staticmethod
    def _row(r: sqlite3.Row, today: date) -> dict[str, Any]:
        exp = date.fromisoformat(r["expires_on"])
        return {"id": r["id"], "name": r["name"], "quantity": r["quantity"],
                "expires_on": r["expires_on"], "days_left": (exp - today).days,
                "estimated": bool(r["estimated"]), "price": r["price"]}
