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

- [ ] **Track-mixer setters: `set_track_volume`, `set_track_mute`,
      `set_track_solo`, `set_track_pan`.** Currently `get_track_info` reads
      these (volume, mute, solo, panning) but no setters exist, so the only
      level control is at the device tail. Hit hard during lofi-01 mixing:
      drum/keys/bass balance had to be solved by pushing instrument-level
      gain instead of fader, and a stuck solo on the Bass track couldn't be
      cleared via MCP. Acceptance: each setter round-trips through
      `get_track_info` and matches the Live UI; mute/solo accept booleans;
      volume/pan accept the Live-native float ranges.

- [ ] **Master-track setters: `set_master_volume`, `set_master_pan`.**
      Same shape as the track setters above. `get_session_info` already
      surfaces master state; complete the read/write pair.

- [ ] **VST3 plugin loading by browser URI fails.** During lofi-01,
      `get_browser_items_at_path("plugins/u-he")` returned Diva with
      `uri="query:Plugins#VST3:u-he:Diva"` and `is_loadable=true`, but
      `load_instrument_or_effect` with that URI errored
      `"Browser item with URI ... not found"`. Same with URL-encoded variant.
      Stock devices load fine; the issue is specific to plugin URIs.
      Workaround was manual drag-drop (twice). Acceptance: loading a VST3
      from `plugins/<vendor>/<plugin>` via MCP succeeds; if the underlying
      LOM call really doesn't accept plugin URIs, document that and either
      provide an alternate path (e.g. by file path) or surface a clearer
      error than "not found."

- [ ] **`get_transport_state` (read playback / position).** No way to
      check if Live is playing, current beat, looping state, etc. During
      lofi-01 we wasted time chasing silent playback that turned out to
      be the transport stopped — no API feedback. Acceptance: returns
      `{is_playing, current_beat, loop_start, loop_end, loop_enabled,
      tempo}` (or similar). Pairs with the existing `start_playback` /
      `stop_playback` setters.

- [ ] **`get_clip_notes` (read existing notes from a clip).** Currently the
      MCP can write notes (`add_notes_to_clip`, `replace_clip_notes`) and
      read automation (`get_clip_envelope`), but cannot read notes back.
      That makes round-trip verification and bug diagnosis nearly impossible
      — when the user reports unexpected note content, the only path is to
      ask them to eyeball Live's UI. Acceptance: tool returns `[{pitch,
      start_time, duration, velocity, mute}, ...]` for both session and
      arrangement clips. Useful for debugging the `clear_clip_notes` no-op
      issue below.

- [ ] **`clear_clip_notes` silently no-ops on session clips.** Hit during
      lofi-01 (2026-04-25): tool returned `{"cleared": true}` but the clip
      retained all prior notes. Subsequent `add_notes_to_clip` then stacked on
      top of the un-cleared notes, producing phase-cancellation transients
      that read as click artifacts on each beat. Same likely affects
      `replace_clip_notes` (which presumably clears + adds internally).
      Acceptance: clearing a session-clip's notes via MCP empties the clip
      in Live's UI, verified by user re-firing the clip and seeing/hearing
      no residual notes; `replace_clip_notes` round-trip leaves exactly the
      passed-in note set. Workaround in the meantime: create a fresh clip
      in a different slot.

- [ ] **NDJSON framing + drop the modifying-command sleeps.** Current
      transport (JSON over TCP localhost:9877) frames messages by
      heuristic: read chunks, try `json.loads` after each, treat
      `JSONDecodeError` as "incomplete, keep reading"
      (`MCP_Server/server.py` `receive_full_response`). Works because
      messages are small and only one is in flight, but it's load-bearing
      — any pipelining or partially-buffered prior response corrupts the
      stream. Replace with newline-delimited JSON: both sides write
      `json.dumps(x) + "\n"`, both sides `readline()`. Then delete the
      100ms pre/post sleeps in `send_command` (lines ~124 and ~145) —
      they're papering over the framing flakiness, not solving a real
      timing problem (the Remote Script's response queue already
      guarantees the response only fires after the main-thread task
      completes). Wins: 200ms off every modifying call, robust framing,
      ~20 LOC simpler.

- [ ] **Switch TCP → Unix domain socket** (after NDJSON lands). Trivial
      swap: `AF_INET`/`(host, port)` → `AF_UNIX`/`/tmp/abletonmcp.sock`.
      Wins: no other process on the machine can connect (security), no
      port-conflict surprises if a second Live ever runs, no firewall
      prompts. Cost: lose `nc localhost 9877` debugging in favor of
      `nc -U /tmp/abletonmcp.sock`. Defer until after NDJSON since
      changing framing and transport in the same commit muddles the diff.

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
