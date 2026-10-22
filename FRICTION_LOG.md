# Friction log (Build, Ship, Shape - Alexa+ track)

| # | Task | Expected | Actual | Severity | Workaround | Suggestion |
|---|---|---|---|---|---|---|
| 1 | `pip install mcp` and follow v1-style tutorials | `FastMCP` importable; protocol 2025-11-25 | Latest `mcp` (2.x) removed `mcp.server.fastmcp` (renamed `MCPServer`) and its latest protocol revision is newer than the 2025-11-25 Alexa+ supports | Medium | Pin `mcp>=1.25,<2` (1.30 negotiates 2025-11-25) | Alexa+ docs should state which MCP SDK versions are verified, so new developers don't pick a default that mismatches |
| 2 | Run client code from SDK examples | No warnings | `streamablehttp_client` is deprecated in favour of `streamable_http_client` | Low | Ignore warning | Keep Alexa+ sample code in sync with SDK renames |
| 3 | Try the Alexa+ add-on flow with no prior access | Self-serve onboarding with the `alexa-ai` CLI | Docs state credentials are issued after approval, so a hackathon participant cannot test against real Alexa+ without prior access | High | Built a scripted simulator that acts as the MCP client | Offer a public local emulator (MCP client + 500 ms latency check + golden-case tests) so any developer can validate an MCP server before approval |
