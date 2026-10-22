# ZeroWaste Kitchen - an Alexa+ MCP server that remembers your food

**The gap:** Alexa+ can reason about recipes, but it has no memory of what is actually in your
kitchen or when it expires. **ZeroWaste Kitchen** is a small, fast MCP server that gives Alexa+
that memory, so it can say *"your chicken expires tomorrow, cook it first"* and *"you only need to
buy onion and cream."*

Built for the *Build, Ship, Shape: Amazon Developer Hackathon* (Alexa+ track).

## How it fits Alexa+
- **Alexa+ is the brain, we are the memory.** Alexa+ handles language, reasoning and recipe ideas.
  This server is the household's system of record. No LLM calls in the request path.
- **MCP spec 2025-11-25 over Streamable HTTP** (stateless, JSON responses).
- **Fast:** every tool returns in ~10 ms locally (Alexa+ requires < 500 ms round trip). Enforced by a test.
- **Voice-first output:** every result has a short, speakable `summary` plus structured data.

## Tools
| Tool | What it does |
|---|---|
| `add_items` | Log groceries; expiry estimated from a shelf-life table (or stated by the user) |
| `whats_expiring` | Food expiring within N days, soonest first |
| `use_items` | Mark items as `used` (cooked) or `wasted` |
| `shopping_gap` | Given a recipe's ingredients: what you have vs. what to buy |
| `waste_report` | Items used before expiry vs. wasted, with money saved/wasted |

## Run it
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m zerowaste.server            # serves http://127.0.0.1:8000/mcp
python demo/alexa_sim.py              # in a second terminal: simulated Alexa+ conversation
pytest -q                             # unit + end-to-end tests (real HTTP, official MCP client)
```
Env vars: `ZW_PORT`, `ZW_HOST`, `ZW_DB` (SQLite path), `ZW_CURRENCY` (symbol for spoken amounts).

## About the Alexa+ simulation (read this)
The author has no Alexa+ device or Alexa+ developer account, so the demo uses `demo/alexa_sim.py`,
a **scripted simulator** that plays the role Alexa+ plays: connect as an MCP client, discover tools,
map a spoken request to a tool call, speak the `summary`. The server itself is a real MCP server
and is not coupled to the simulator; the same endpoint can be registered as an Alexa+ add-on.

## Known limits
- Single household (real use needs account linking / OAuth to scope data per user).
- Shelf-life values are conservative rules of thumb; swap in USDA FoodKeeper for production.
- SQLite storage; a DynamoDB adapter is planned for serverless deployment.

License: MIT
