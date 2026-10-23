"""ZeroWaste Kitchen - an MCP server that gives Alexa+ a memory of your food.

Design rules (driven by Alexa+ MCP requirements):
  * Streamable HTTP transport, MCP spec 2025-11-25.
  * Alexa+ is the reasoning/NLU layer, so tools are small, deterministic and
    fast (no LLM calls in the request path; target well under 500 ms).
  * Every result carries a short, speakable `summary` plus structured data.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from .store import Store

CURRENCY = os.environ.get("ZW_CURRENCY", "")

INSTRUCTIONS = (
    "ZeroWaste Kitchen remembers what food the household has and when it expires. "
    "Use it when the user mentions groceries they bought or used, asks what to cook "
    "or what is about to go bad, or wants to know what they still need to buy. "
    "Call whats_expiring before suggesting recipes so the soonest-expiring food is used first."
)


# ---- speech helpers -------------------------------------------------------
def say_list(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def say_days(d: int) -> str:
    if d < -1:
        return f"expired {-d} days ago"
    if d == -1:
        return "expired yesterday"
    if d == 0:
        return "expires today"
    if d == 1:
        return "expires tomorrow"
    return f"expires in {d} days"


def say_money(x: float) -> str:
    return f"{CURRENCY}{x:g}"


# ---- tool inputs ------------------------------------------------------------
class NewItem(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="Food name, e.g. 'spinach'")
    quantity: float = Field(default=1, gt=0, description="How many / how much")
    days_until_expiry: int | None = Field(
        default=None, ge=0, le=730,
        description="Only if the user states it; otherwise a shelf-life default is used")
    price: float | None = Field(default=None, ge=0, description="Optional price paid")


def build_server(
    store: Any | None = None,
    host: str | None = None,
    port: int | None = None,
) -> FastMCP:
    host = host or os.environ.get("ZW_HOST", "127.0.0.1")
    port = port if port is not None else int(os.environ.get("ZW_PORT", "8000"))

    # When binding to 0.0.0.0 for hosted deployments (e.g. Lambda Function URL / containers),
    # ensure DNS rebinding protection does not reject deployed hostnames.
    transport_security = None
    if host == "0.0.0.0":
        from mcp.server.transport_security import TransportSecuritySettings
        transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

    if store is None:
        store_type = os.environ.get("ZW_STORE", "sqlite").lower()
        if store_type == "dynamodb":
            from .dynamo_store import DynamoDBStore
            store = DynamoDBStore()
        else:
            store = Store(os.environ.get("ZW_DB", "zerowaste.db"))
    mcp = FastMCP(
        "ZeroWaste Kitchen",
        instructions=INSTRUCTIONS,
        host=host,
        port=port,
        stateless_http=True,   # no sticky sessions: scales on Lambda/containers
        json_response=True,    # plain JSON replies: lowest latency for short tool calls
        transport_security=transport_security,
    )
    read_only = ToolAnnotations(readOnlyHint=True, idempotentHint=True)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

    static_file = Path(__file__).parent / "static" / "simulator.html"

    @mcp.custom_route("/", methods=["GET"])
    async def simulator(request: Request) -> HTMLResponse:
        content = static_file.read_text(encoding="utf-8") if static_file.is_file() else "<h1>Simulator not found</h1>"
        return HTMLResponse(content)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    @mcp.tool(annotations=write)
    def add_items(items: list[NewItem]) -> dict[str, Any]:
        """Add groceries the user just bought to the household food memory.
        Expiry dates are estimated automatically; do not ask the user for them."""
        added = [store.add(i.name, i.quantity, i.days_until_expiry, i.price) for i in items[:50]]
        soonest = min(added, key=lambda a: a["days_left"])
        summary = (f"Added {len(added)} item{'s' if len(added) != 1 else ''}. "
                   f"Soonest to expire: {soonest['name']}, {say_days(soonest['days_left'])}.")
        return {"summary": summary, "added": added}

    @mcp.tool(annotations=read_only)
    def whats_expiring(within_days: int = Field(default=3, ge=0, le=60)) -> dict[str, Any]:
        """List food that expires within N days (default 3), soonest first.
        Call this before suggesting what to cook."""
        rows = store.expiring(within_days)
        if not rows:
            return {"summary": f"Nothing is expiring in the next {within_days} days.", "items": []}
        spoken = [f"{r['name']} {say_days(r['days_left'])}" for r in rows[:5]]
        extra = len(rows) - 5
        summary = say_list(spoken) + (f", and {extra} more." if extra > 0 else ".")
        return {"summary": summary, "items": rows}

    @mcp.tool(annotations=write)
    def use_items(names: list[str],
                  outcome: Literal["used", "wasted"] = "used") -> dict[str, Any]:
        """Record that the user cooked/ate ('used') or threw away ('wasted') foods."""
        res = store.close(names, outcome)
        parts = []
        if res["done"]:
            verb = "Marked" if outcome == "used" else "Logged as wasted:"
            parts.append(f"{verb} {say_list(res['done'])}" + (" as used." if outcome == "used" else "."))
        if res["not_found"]:
            parts.append(f"I couldn't find {say_list(res['not_found'])} in your kitchen.")
        return {"summary": " ".join(parts) or "Nothing to update.", **res}

    @mcp.tool(annotations=read_only)
    def shopping_gap(ingredients: list[str]) -> dict[str, Any]:
        """Given the ingredients of a meal, say which the user already has (unexpired)
        and which they still need to buy."""
        have, missing = [], []
        for ing in ingredients[:60]:
            hit = store.available(ing)
            (have if hit else missing).append(hit["name"] if hit else ing)
        if not missing:
            summary = "You already have everything."
        elif not have:
            summary = f"You need to buy {say_list(missing)}."
        else:
            summary = (f"You have {say_list(have)}. You still need {say_list(missing)}.")
        return {"summary": summary, "have": have, "missing": missing}

    @mcp.tool(annotations=read_only)
    def waste_report(days: int = Field(default=7, ge=1, le=365)) -> dict[str, Any]:
        """Summarise food used before expiry vs wasted over the last N days (default 7)."""
        r = store.report(days)
        parts = [f"In the last {days} days you used {r['used_before_expiry']} "
                 f"item{'s' if r['used_before_expiry'] != 1 else ''} before they expired"]
        if r["money_saved"]:
            parts[0] += f", saving about {say_money(r['money_saved'])}"
        parts.append(f"and {r['wasted']} went to waste"
                     + (f", about {say_money(r['money_wasted'])}" if r["money_wasted"] else ""))
        return {"summary": ", ".join(parts) + ".", **r}

    return mcp


def main() -> None:
    host = os.environ.get("ZW_HOST", "127.0.0.1")
    port = int(os.environ.get("ZW_PORT", "8000"))
    build_server(host=host, port=port).run(transport="streamable-http")


if __name__ == "__main__":
    main()
