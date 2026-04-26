# Backlog

Fork-development TODOs. Music-production work lives in the consuming repo.

## Claiming items (for parallel agents)

To avoid stepping on each other, agents working in parallel must claim before
editing code. Protocol:

1. `git pull --rebase origin main` — get latest claim state.
2. Pick an unclaimed `- [ ]` item whose file scope doesn't overlap an
   in-progress claim (see "Scope" below each item, when present).
3. Change `- [ ]` to `- [claimed: <agent-id> YYYY-MM-DD]` on that line and
   commit *just that edit* directly to main with message
   `claim: <short item title>`. Push immediately.
4. If the push rejects (someone else claimed first), rebase, pick a different
   item, retry.
5. Do the work on a branch `agent/<agent-id>/<slug>`, open a PR.
6. On merge, replace the claim line with `- [x]` and move to "Done (recent)".
7. If abandoning, revert the claim line back to `- [ ]` in a single commit.

Scope tags (`Scope: server | remote-script | docs | transport`) on items below
indicate which files an agent will touch — use them to parallelize across
disjoint sets only.

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
      Scope: server + remote-script (LOM research-heavy)

- [ ] **Audio render** — `render_audio(path, length_beats)`. Needs Live 12
      `Live.Application.Application.render_to_file` (or equivalent — verify
      in target Live build). File-write means the audit policy bar is higher.
      Last because drift-01 can bounce by hand once.
      Scope: server + remote-script

- [ ] **Verify `save_session_as` actually works in the target Live build.**
      Implementation probes `Song.save_song_as` then `Song.save_as`; if neither
      exists in this Live's Python LOM (likely — save-as is often
      Application-side, not Song-side), surface a clearer fallback path or
      gate the tool out. lofi-01 will exercise it.
      Scope: remote-script (server signature stable)

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
      Scope: remote-script (browser/loader investigation; server unchanged)

- [claimed: claude-clipnotes 2026-04-26] **`get_clip_notes` (read existing notes from a clip).** Currently the
      MCP can write notes (`add_notes_to_clip`, `replace_clip_notes`) and
      read automation (`get_clip_envelope`), but cannot read notes back.
      That makes round-trip verification and bug diagnosis nearly impossible
      — when the user reports unexpected note content, the only path is to
      ask them to eyeball Live's UI. Acceptance: tool returns `[{pitch,
      start_time, duration, velocity, mute}, ...]` for both session and
      arrangement clips. Useful for debugging the `clear_clip_notes` no-op
      issue below.
      Scope: server + remote-script

- [claimed: claude-clipnotes 2026-04-26] **`clear_clip_notes` silently no-ops on session clips.** Hit during
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
      Scope: remote-script (bug likely in clip-note handler; depends on
      `get_clip_notes` for a clean repro)

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
      Scope: transport (server send/receive + remote-script socket handler).
      EXCLUSIVE: blocks all other server.py + remote-script work while
      in-flight — coordinate, do not parallelize.

- [ ] **Switch TCP → Unix domain socket** (after NDJSON lands). Trivial
      swap: `AF_INET`/`(host, port)` → `AF_UNIX`/`/tmp/abletonmcp.sock`.
      Wins: no other process on the machine can connect (security), no
      port-conflict surprises if a second Live ever runs, no firewall
      prompts. Cost: lose `nc localhost 9877` debugging in favor of
      `nc -U /tmp/abletonmcp.sock`. Defer until after NDJSON since
      changing framing and transport in the same commit muddles the diff.
      Scope: transport. EXCLUSIVE with NDJSON item; sequence after.

## Won't do

- Async/await refactor — bridge is request/response over localhost; sync is right.
- Splitting `server.py` by domain — flat file is fine until ~2000 lines.
- Renaming packages (`MCP_Server`, `AbletonMCP_Remote_Script`) — breaks the
  Remote Script loader path and uvx archive cache for no real gain.

## Done (recent)

- 2026-04-26 — `get_transport_state` (playback state, current beat, tempo,
  loop region) — closes the lofi-01 silent-playback diagnosis gap.

- 2026-04-25 — #6 registry-pattern dispatcher; #7 TOOLS.md cheatsheet;
  `delete_session_clip`, `set_transport_position`, `start_playback(from_beats)`,
  `save_session`, `save_session_as`; type-hint modernization to 3.10+;
  `_MODIFYING_COMMANDS` hoisted to constant; build artifacts cleaned;
  `.mcp.json` gitignored.
