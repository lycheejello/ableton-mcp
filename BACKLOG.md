# Backlog

Fork-development TODOs. Music-production work lives in the consuming repo.

## Untested

- [ ] **Sanity-check 1.2.0** — the `server.py` refactor (`_forward`/`_call` helpers,
      ~30 tools rewritten, `1030 → 845` lines) and the prior arrangement-v1 scope
      cut (envelope tools dropped `is_arrangement`) shipped without a smoke test.
      First call against a live Ableton on next session should:
      - hit one `_forward` tool that returns JSON (e.g. `get_session_info`)
      - hit one tool that previously returned a custom string (e.g. `set_tempo(60)`)
      - hit one envelope tool on a session clip (`add_clip_envelope_point` with no
        `is_arrangement` arg)
      All should succeed; failures are likely regressions in the refactor.

## Refactor — open

- [ ] **#6 Registry-pattern the Remote Script dispatcher** in
      `AbletonMCP_Remote_Script/__init__.py`. Currently every command name appears
      in (a) a list of read-only commands at the top of the elif chain, (b) a list
      of main-thread commands, and (c) its own `params.get(...)` plumbing inside
      the main-thread closure. Adding a tool means editing four places.
      Replace with a single dict: `COMMANDS = {"name": (handler_method, runs_on_main_thread)}`.
      The closure becomes a generic `handler(**params)` call.
      Notes: keep the file as a single module — Live's MIDI Remote Script loader
      doesn't care about internal structure but does care about the entry-point
      class location. Don't rename `AbletonRemoteScript` or move it across files.

- [ ] **#7 TOOLS.md cheatsheet** — flat table of every tool: name, signature,
      one-line purpose. Easier to scan than reading 32 docstrings when planning
      a session. Auto-generatable from the `@mcp.tool` decorators if you want;
      hand-written is also fine. Lives in the fork repo, not the music vault.

## Smaller things

- [ ] Modernize type hints: `List[Dict[...]]` → `list[dict[...]]` (3.10+ syntax,
      `pyproject.toml` already requires 3.10).
- [ ] Drop the unused `Any` / `AsyncIterator` imports if they're no longer
      referenced after the refactor (verify with `ruff check --select F401`).
- [ ] Remove dead build artifacts on disk (`build/`, `ableton_mcp.egg-info/`)
      — gitignored already, just clutter.

## Deferred to v2 (architecture, not refactors)

- [ ] **Arrangement-view mixer automation** — track timeline lane API, separate
      from `Clip.automation_envelope`. See
      `~/.claude/projects/-Users-huyson-Develop-music/memory/reference_arrangement_envelope_api.md`
      for the API constraint discovered 2026-04-25.
- [ ] **Device-parameter automation** — `device:I:param:J` envelope paths. Build
      on top of `set_device_parameter` once the arrangement automation surface
      is decided.
- [ ] **Audio render** — `render_audio(path, length_beats)`. Needs Live 12
      `Live.Application.Application.render_to_file` (or equivalent — verify in
      target Live build). File-write means the audit policy bar is higher.

## Won't do

- Async/await refactor — bridge is request/response over localhost; sync is right.
- Splitting `server.py` by domain — flat file is fine until ~2000 lines.
- Renaming packages (`MCP_Server`, `AbletonMCP_Remote_Script`) — breaks the
  Remote Script loader path and uvx archive cache for no real gain.
