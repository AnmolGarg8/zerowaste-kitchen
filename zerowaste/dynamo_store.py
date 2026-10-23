"""DynamoDB-backed pantry store for AWS serverless deployment.

Implements the same public methods and return shapes as `Store` in `zerowaste/store.py`:
  - add(name, quantity, days_until_expiry, price, today)
  - close(names, outcome, today)
  - expiring(within_days, today)
  - available(name, today)
  - report(days, today)

Uses single-table DynamoDB design:
  - Table: named by env ZW_TABLE (default 'zerowaste-kitchen')
  - Partition key: 'household' (string, default from ZW_HOUSEHOLD 'default')
  - Sort key: 'sk' (string, e.g. 'ITEM#<id>')
  - On-demand billing (PAY_PER_REQUEST)
  - Queries on the household partition key (never scans whole table)
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from .shelf_life import lookup, normalize
from .store import _match


class DynamoDBStore:
    def __init__(
        self,
        table_name: str | None = None,
        household: str | None = None,
        dynamodb_resource: Any | None = None,
    ) -> None:
        self.table_name = table_name or os.environ.get("ZW_TABLE", "zerowaste-kitchen")
        self.household = household or os.environ.get("ZW_HOUSEHOLD", "default")
        self._dynamodb = dynamodb_resource or boto3.resource("dynamodb")
        self._table = self._dynamodb.Table(self.table_name)
        self._lock = threading.Lock()
        self._last_id = 0
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create on-demand table if it doesn't already exist (e.g. during local tests / moto)."""
        try:
            self._table.load()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code == "ResourceNotFoundException":
                self._table = self._dynamodb.create_table(
                    TableName=self.table_name,
                    KeySchema=[
                        {"AttributeName": "household", "KeyType": "HASH"},
                        {"AttributeName": "sk", "KeyType": "RANGE"},
                    ],
                    AttributeDefinitions=[
                        {"AttributeName": "household", "AttributeType": "S"},
                        {"AttributeName": "sk", "AttributeType": "S"},
                    ],
                    BillingMode="PAY_PER_REQUEST",
                )
                self._table.wait_until_exists()
            else:
                raise

    def _next_id(self) -> int:
        with self._lock:
            now_ns = time.time_ns()
            if now_ns <= self._last_id:
                now_ns = self._last_id + 1
            self._last_id = now_ns
            return now_ns

    def _query_household(self) -> list[dict[str, Any]]:
        """Query all items belonging to this household partition (avoids full table scans)."""
        res = self._table.query(
            KeyConditionExpression=Key("household").eq(self.household)
        )
        items = res.get("Items", [])
        while "LastEvaluatedKey" in res:
            res = self._table.query(
                KeyConditionExpression=Key("household").eq(self.household),
                ExclusiveStartKey=res["LastEvaluatedKey"],
            )
            items.extend(res.get("Items", []))
        return items

    # -- writes -----------------------------------------------------------
    def add(
        self,
        name: str,
        quantity: float = 1,
        days_until_expiry: int | None = None,
        price: float | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        today = today or date.today()
        if days_until_expiry is None:
            days, estimated = lookup(name)
        else:
            days, estimated = days_until_expiry, False

        expires = today + timedelta(days=days)
        item_id = self._next_id()
        item_data: dict[str, Any] = {
            "household": self.household,
            "sk": f"ITEM#{item_id}",
            "id": item_id,
            "name": name.strip(),
            "norm": normalize(name),
            "quantity": Decimal(str(quantity)),
            "added_on": today.isoformat(),
            "expires_on": expires.isoformat(),
            "estimated": int(estimated),
            "status": "active",
            "closed_on": None,
            "price": Decimal(str(price)) if price is not None else None,
        }

        self._table.put_item(Item=item_data)
        return {
            "id": item_id,
            "name": name.strip(),
            "quantity": float(quantity),
            "expires_on": expires.isoformat(),
            "days_left": days,
            "estimated": bool(estimated),
        }

    def close(
        self, names: list[str], outcome: str, today: date | None = None
    ) -> dict[str, list[str]]:
        """Mark the soonest-expiring active item for each name as used/wasted."""
        assert outcome in ("used", "wasted")
        today = today or date.today()
        done: list[str] = []
        missing: list[str] = []

        all_items = self._query_household()
        active_items = [
            item for item in all_items if item.get("status") == "active"
        ]
        active_items.sort(key=lambda r: (r["expires_on"], int(r["id"])))

        for q in names:
            qn = normalize(q)
            hit_idx = None
            for idx, r in enumerate(active_items):
                if _match(r["norm"], qn):
                    hit_idx = idx
                    break

            if hit_idx is None:
                missing.append(q)
                continue

            hit = active_items.pop(hit_idx)
            self._table.update_item(
                Key={"household": self.household, "sk": hit["sk"]},
                UpdateExpression="SET #st = :status, #cl = :closed_on",
                ExpressionAttributeNames={"#st": "status", "#cl": "closed_on"},
                ExpressionAttributeValues={
                    ":status": outcome,
                    ":closed_on": today.isoformat(),
                },
            )
            done.append(hit["name"])

        return {"done": done, "not_found": missing}

    # -- reads ------------------------------------------------------------
    def expiring(
        self, within_days: int = 3, today: date | None = None
    ) -> list[dict[str, Any]]:
        """Active items expiring within N days (already-expired items come first)."""
        today = today or date.today()
        limit = (today + timedelta(days=within_days)).isoformat()
        all_items = self._query_household()
        active_expiring = [
            item
            for item in all_items
            if item.get("status") == "active" and item.get("expires_on") <= limit
        ]
        active_expiring.sort(key=lambda r: (r["expires_on"], int(r["id"])))
        return [self._row(r, today) for r in active_expiring]

    def available(self, name: str, today: date | None = None) -> dict[str, Any] | None:
        """Soonest-expiring unexpired active item matching `name`, or None."""
        today = today or date.today()
        qn = normalize(name)
        today_iso = today.isoformat()
        all_items = self._query_household()
        active_unexpired = [
            item
            for item in all_items
            if item.get("status") == "active" and item.get("expires_on") >= today_iso
        ]
        active_unexpired.sort(key=lambda r: (r["expires_on"], int(r["id"])))
        hit = next((r for r in active_unexpired if _match(r["norm"], qn)), None)
        return self._row(hit, today) if hit else None

    def report(self, days: int = 7, today: date | None = None) -> dict[str, Any]:
        """Summarise food used before expiry vs wasted over the last N days."""
        today = today or date.today()
        since = (today - timedelta(days=days)).isoformat()
        today_iso = today.isoformat()

        all_items = self._query_household()

        used = 0
        used_before_expiry = 0
        money_saved = Decimal(0)
        wasted = 0
        money_wasted = Decimal(0)
        expired_unused = 0

        for item in all_items:
            status = item.get("status")
            closed_on = item.get("closed_on")
            expires_on = item.get("expires_on")
            price = item.get("price") or Decimal(0)

            # used
            if status == "used" and closed_on and closed_on >= since:
                used += 1
                if expires_on and closed_on <= expires_on:
                    used_before_expiry += 1
                    money_saved += price

            # wasted
            if status == "wasted" and closed_on and closed_on >= since:
                wasted += 1
                money_wasted += price

            # expired unused in pantry
            if (
                status == "active"
                and expires_on
                and expires_on < today_iso
                and expires_on >= since
            ):
                expired_unused += 1
                money_wasted += price

        return {
            "days": days,
            "used": used,
            "used_before_expiry": used_before_expiry,
            "money_saved": float(money_saved),
            "wasted": wasted + expired_unused,
            "money_wasted": float(money_wasted),
            "expired_unused": expired_unused,
        }

    @staticmethod
    def _row(r: dict[str, Any], today: date) -> dict[str, Any]:
        exp = date.fromisoformat(r["expires_on"])
        price = float(r["price"]) if r.get("price") is not None else None
        return {
            "id": int(r["id"]),
            "name": r["name"],
            "quantity": float(r["quantity"]),
            "expires_on": r["expires_on"],
            "days_left": (exp - today).days,
            "estimated": bool(r["estimated"]),
            "price": price,
        }
