# Backlog

Fork-development TODOs. Music-production work lives in the consuming repo.

## Open

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

- [ ] **Verify `save_session_as` actually works in the target Live build.**
      Implementation probes `Song.save_song_as` then `Song.save_as`; if neither
      exists in this Live's Python LOM (likely — save-as is often
      Application-side, not Song-side), surface a clearer fallback path or
      gate the tool out. lofi-01 will exercise it.

## Won't do

- Async/await refactor — bridge is request/response over localhost; sync is right.
- Splitting `server.py` by domain — flat file is fine until ~2000 lines.
- Renaming packages (`MCP_Server`, `AbletonMCP_Remote_Script`) — breaks the
  Remote Script loader path and uvx archive cache for no real gain.

## Done (recent)

- 2026-04-25 — #6 registry-pattern dispatcher; #7 TOOLS.md cheatsheet;
  `delete_session_clip`, `set_transport_position`, `start_playback(from_beats)`,
  `save_session`, `save_session_as`; type-hint modernization to 3.10+;
  `_MODIFYING_COMMANDS` hoisted to constant; build artifacts cleaned;
  `.mcp.json` gitignored.
