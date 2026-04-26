# Backlog

Fork-development TODOs. Music-production work lives in the consuming repo.

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

- [ ] **`delete_session_clip(track_index, clip_slot_index)`** — symmetry with
      `delete_arrangement_clip`. drift-01 left 5 discarded recording takes in
      session slots; user can't (per policy) clear them by hand. LOM:
      `clip_slot.delete_clip()`. Trivial — no main-thread issues, returns
      slot info on success. Add to dispatcher registry alongside the
      arrangement variant.
- [ ] **`set_transport_position(beats)`** + extend `start_playback` to take
      optional `from_beats`. Currently no way to scrub the arrangement cursor
      via MCP — auditioning a specific section means hand-clicking the
      timeline, which violates the no-hand-software policy. LOM:
      `Song.current_song_time = beats`. Pair with existing start/stop for
      "play from beat N" ergonomics. drift-01 needed: play from m17 (beat 64)
      to audition the build section.
- [ ] **`save_session()`** + **`save_session_as(path)`**. No way to persist
      a Live set via MCP — user can't (per policy) ⌘S the file. LOM:
      `Song.save_song()` (saves to current path), `Song.save_song_as(path)`.
      For a fresh untitled set, `save_session()` will fail (no path) — should
      surface a clear error pointing at `save_session_as`. lofi-01 hit this
      when Claude couldn't save a freshly-created Live set.
- [ ] Modernize type hints: `List[Dict[...]]` → `list[dict[...]]` (3.10+ syntax,
      `pyproject.toml` already requires 3.10).
- [ ] Drop the unused `Any` / `AsyncIterator` imports if they're no longer
      referenced after the refactor (verify with `ruff check --select F401`).
- [ ] Remove dead build artifacts on disk (`build/`, `ableton_mcp.egg-info/`)
      — gitignored already, just clutter.

## Next — promoted from drift-01 discovery (2026-04-25)

drift-01 walked the full Session→Arrangement→bounce loop and surfaced the
exact gaps. Tackle in this order; each unblocks a piece of drift-02.

- [ ] **Arrangement-view automation (track-lane + per-clip)** — supersedes the
      former two separate items. Smoke test on 2026-04-25 (1.3.0) proved
      `Clip.automation_envelope` rejects arrangement clips for ANY param type
      (mixer AND device — earlier reference-doc claim that device params
      worked was wrong). So per-clip and track-lane arrangement automation
      both need the same alternate API. Approach: read AbletonOSC's source
      (it implements arrangement envelopes successfully) and port the LOM
      call. Acceptance: (a) write breakpoints on a track's volume lane in
      arrangement (drift-01 needed: T1 Erebus fade-in 90b, mute at 225,
      return at 315; Master fade 360→420), (b) write a device-param arc on
      an arrangement clip (e.g. Resonators Decay), (c) drift-01 bounces with
      audible fades. The current `is_arrangement=True` arg on the envelope
      tools is wired but errors at the LOM layer — repurpose or replace as
      part of this work.

- [ ] **Audio render** — `render_audio(path, length_beats)`. Needs Live 12
      `Live.Application.Application.render_to_file` (or equivalent — verify
      in target Live build). File-write means the audit policy bar is higher.
      Last because drift-01 can bounce by hand once.

## Won't do

- Async/await refactor — bridge is request/response over localhost; sync is right.
- Splitting `server.py` by domain — flat file is fine until ~2000 lines.
- Renaming packages (`MCP_Server`, `AbletonMCP_Remote_Script`) — breaks the
  Remote Script loader path and uvx archive cache for no real gain.
