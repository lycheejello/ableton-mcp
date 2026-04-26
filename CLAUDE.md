# ableton-mcp — bridge

The protocol layer: Ableton Remote Script (`AbletonMCP_Remote_Script/`) + MCP server (`MCP_Server/`). See `../CLAUDE.md` for company-wide context and `../vault/00-now.md` for current focus.

## Version-bump rule (load-bearing)

**Bump `pyproject.toml` `version` on every shipping commit that changes `MCP_Server/` or `AbletonMCP_Remote_Script/`.**

Why: the MCP server is launched via `uvx --from <path> ableton-mcp`. uv caches built wheels keyed on `(name, version)`. If you ship source changes without bumping the version, every running CC session keeps serving the stale cached wheel — new tools won't appear, fixes won't take effect, and `/mcp` reconnect doesn't help. Bumping the version forces uv to build a fresh wheel into a new cache slot.

How to apply:
- Feature add (new tool / new primitive): minor bump (`1.4.0` → `1.5.0`).
- Bug fix or behavior change inside an existing tool: patch bump (`1.4.0` → `1.4.1`).
- Bump *in the same commit* as the source change. Do not bundle multiple ships under one version.
- Only `MCP_Server/` and `AbletonMCP_Remote_Script/` changes need a bump. Doc / tooling / test-only changes don't.

The Remote Script side has no separate cache, but bumping anyway keeps the version monotonic and easy to read in `git log`.

## Smoke-test convention

Use `tools/probe.py` for live-Ableton smoke tests of new bridge tools — it bypasses the MCP server and the `uvx` cache, so iteration is just "restart Live → probe."
