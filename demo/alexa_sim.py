"""Alexa+ simulator (scripted orchestrator) for the ZeroWaste Kitchen MCP server.

Real Alexa+ is the MCP *client*: it discovers tools, maps a spoken request to a
tool call, then speaks the result. This script plays that role deterministically
so the demo is reproducible offline. It is a simulation, not real Alexa+.

Usage:  python -m zerowaste.server &   then   python demo/alexa_sim.py
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("ZW_URL", "http://127.0.0.1:8000/mcp")

TURNS = [
    ("Alexa, I just bought chicken, spinach and yogurt.", "add_items",
     {"items": [{"name": "chicken", "price": 220}, {"name": "spinach", "price": 40},
                {"name": "yogurt", "price": 60}]}),
    ("Alexa, what's about to go bad?", "whats_expiring", {"within_days": 3}),
    ("Alexa, I want to make a palak chicken curry. What do I need to buy?", "shopping_gap",
     {"ingredients": ["chicken", "spinach", "onion", "garlic", "cream"]}),
    ("Alexa, I cooked the chicken and spinach tonight.", "use_items",
     {"names": ["chicken", "spinach"], "outcome": "used"}),
    ("Alexa, how am I doing on food waste?", "waste_report", {"days": 7}),
]


async def main() -> None:
    async with streamablehttp_client(URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            print(f"[connected] {init.serverInfo.name}, MCP {init.protocolVersion}")
            tools = (await s.list_tools()).tools
            print(f"[discovered] {', '.join(t.name for t in tools)}\n")
            for utterance, tool, args in TURNS:
                print(f"You:    {utterance}")
                print(f"        -> tool call: {tool}({json.dumps(args)})")
                res = await s.call_tool(tool, args)
                if res.isError or not res.structuredContent:
                    text = " ".join(getattr(c, "text", "") for c in res.content)
                    print(f"Alexa+: Sorry, something went wrong. [{text}]\n")
                    continue
                print(f"Alexa+: {res.structuredContent['summary']}\n")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
