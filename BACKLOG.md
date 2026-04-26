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

- [ ] **Cue point rename — `set_cue_name(cue_index, name)`.** SZO-23
      shipped read + toggle + nav for cues but not naming. `CuePoint.name`
      is a writable LOM property; this is a one-line tool plus dispatch.
      Load-bearing for the v0 mix-notes interpreter: cue *names* are how
      "in the bridge" / "at the drop" bind to a beat, and currently the
      agent can navigate cues but cannot label them — every cue placed
      via `set_or_delete_cue` lands with Live's auto-name ("1", "2", …)
      and a human has to rename in the UI before the agent can use it.
      Discovered 2026-04-26 during /interpret-notes smoke test.
      LOM: `Live.CuePoint.CuePoint.name`.
      Scope: server + remote-script

- [ ] **Position-aware cue placement — `place_cue(beat, name=None)`.**
      Today, placing N cues at known positions takes 2N round-trips
      (`set_transport_position` then `set_or_delete_cue`) plus an
      observed cursor-lag race: `set_or_delete_cue` toggles ~0.5–2.7 beats
      off the previously-requested position because the next call fires
      before the cursor settles. A direct positional setter sidesteps
      both. If `CuePoint`-level positional add isn't exposed in the LOM,
      either (a) hide the cursor dance behind the tool with a settled-
      cursor wait, or (b) document the LOM gap and keep the dance with a
      sync barrier. Pairs naturally with the rename item — same call can
      take a name. Discovered 2026-04-26 during /interpret-notes smoke test.
      LOM: investigate `Song.cue_points` mutability + `Song.set_or_delete_cue`
      semantics under rapid `current_song_time` writes.
      Scope: server + remote-script

- [ ] **Remove dead `is_arrangement=True` plumbing from envelope tools.**
      The arg is wired through server + remote-script but always errors at
      the LOM layer — arrangement-view automation cannot be written via the
      documented Live 12 Python LOM (see Won't do). Strip the param and any
      branching it triggers, simplify the tools to session-only.
      Scope: server + remote-script

### LOM-audit gaps (2026-04-26)

The 22 items below come from the Live 12.2.7 LOM audit
(`tools/ref/Live12.2.7-LOM.xml`). Each is independently claimable.
Ordered roughly by music-production agent value, not by implementation
ease. Class refs are absolute LOM names so future agents can grep the
XML directly.

- [ ] **Audio + return track creation/deletion + duplicate.** Currently
      only `create_midi_track`. Add `create_audio_track`,
      `create_return_track`, `delete_track`, `delete_return_track`,
      `duplicate_track`, plus `Track.delete_clip` and `delete_device`.
      LOM: `Song.create_audio_track/create_return_track/delete_track/
      delete_return_track/duplicate_track`, `Track.delete_clip/
      delete_device`.
      Scope: server + remote-script

- [ ] **Scenes (session view).** Expose scene list + per-scene
      fire/name + create/delete/duplicate/capture. Capture is the
      "snap a scene from currently playing clips" action.
      LOM: `Song.scenes/create_scene/delete_scene/duplicate_scene/
      capture_and_insert_scene`, `Live.Scene.Scene` for per-scene ops.
      Scope: server + remote-script

- [ ] **Track sends (return routing).** `Track.mixer_device.sends` is
      a list of DeviceParameters (one per return track). Add
      `set_track_send(track, send_index, value)` and `get_track_sends`.
      Core mixing primitive. Pairs with the return-track creation
      item above.
      LOM: `MixerDevice.sends`.
      Scope: server + remote-script

- [ ] **Track input/output routing + monitoring state.** Tracks expose
      their routing as enumerations (`available_input_routing_types`,
      `available_input_routing_channels`, same for output) plus
      `current_*` getters. Monitoring is `current_monitoring_state` over
      `monitoring_states` (Auto/In/Off). Needed for any non-trivial
      signal-flow setup.
      LOM: `Track.input_routing_type/input_routing_channel/
      output_routing_type/output_routing_channel/current_monitoring_state/
      monitoring_states/available_*_routing_*`.
      Scope: server + remote-script

- [ ] **Track arm + freeze.** `arm`, `can_be_armed`, `is_frozen`,
      `can_be_frozen` are Track properties. Freeze action itself isn't
      a Track method — likely lives on Application or via a Song-level
      command; investigate at runtime. Useful for record-arming and
      mixdown-stage freezing of CPU-heavy tracks.
      LOM: `Track.arm/can_be_armed/is_frozen/can_be_frozen`.
      Scope: server + remote-script

- [ ] **Cue points / locators.** Read `Song.cue_points` (list of
      CuePoint objects with name + time), toggle at current position
      via `set_or_delete_cue`, navigate via `jump_to_next_cue`/
      `jump_to_prev_cue`. Useful for naming sections in arrangement
      and for agents to navigate by section name.
      LOM: `Song.cue_points/set_or_delete_cue/jump_to_next_cue/
      jump_to_prev_cue/can_jump_to_next_cue/can_jump_to_prev_cue/
      is_cue_point_selected`.
      Scope: server + remote-script

- [ ] **Time signature + Live 12 scale awareness.** Numerator/
      denominator on Song. Live 12 added scale awareness:
      `scale_name`, `scale_intervals`, `scale_mode`, `root_note`,
      `tuning_system`. Lets MIDI-generation agents stay in key.
      LOM: `Song.signature_numerator/signature_denominator/scale_name/
      scale_intervals/scale_mode/root_note/tuning_system`.
      Scope: server + remote-script

- [ ] **Capture MIDI.** `Song.capture_midi()` creates a clip from
      Live's MIDI input buffer (the Capture button). Pairs with
      `can_capture_midi` to gate the call. Useful for performance-
      capture workflows.
      LOM: `Song.capture_midi/can_capture_midi`.
      Scope: server + remote-script

- [ ] **MIDI clip quantize.** `Clip.quantize(grid, amount)` and
      `Clip.quantize_pitch(pitch)`. Core MIDI editing primitive that
      complements existing note-write tools. Without this, agents
      have to compute quantized note times themselves.
      LOM: `Clip.quantize/quantize_pitch`.
      Scope: server + remote-script

- [ ] **Audio clip warp + pitch + gain.** Currently we expose nothing
      for audio clips. Add `set_clip_warp(track, clip, warping,
      warp_mode)`, `set_clip_gain`, `set_clip_pitch(coarse, fine)`.
      LOM: `Clip.warping/warp_mode/available_warp_modes/gain/
      gain_display_string/pitch_coarse/pitch_fine`.
      Scope: server + remote-script

- [ ] **Warp markers.** Read/write the warp-marker list that maps
      sample time → beat time on audio clips. Foundation for
      time-stretching and groove extraction.
      LOM: `Clip.warp_markers/add_warp_marker/move_warp_marker/
      remove_warp_marker`, `Live.Clip.WarpMarker`,
      `Clip.beat_to_sample_time/sample_to_beat_time/
      seconds_to_sample_time`.
      Scope: server + remote-script

- [ ] **Groove pool + per-clip groove + global groove amount.** Song-
      level groove pool plus per-clip groove assignment. Lets agents
      apply swing to MIDI clips without rewriting notes.
      LOM: `Song.groove_pool/groove_amount/swing_amount`,
      `Clip.groove/has_groove`, `Live.Groove.Groove`,
      `Live.GroovePool.GroovePool`.
      Scope: server + remote-script

- [ ] **Color (tracks + clips).** Set/get color via `color_index`
      (Live's palette) or raw `color` (RGB int). Currently we don't
      surface track or clip color, which is the main visual organizer
      in Live.
      LOM: `Track.color/color_index`, `Clip.color/color_index`.
      Scope: server + remote-script

- [ ] **Group tracks + fold state.** Read `is_grouped`/`group_track`
      to traverse hierarchy, read/set `fold_state` to collapse/expand
      groups. Needed for any agent that creates/edits track groups.
      LOM: `Track.fold_state/is_grouped/is_foldable/group_track`.
      Scope: server + remote-script

- [ ] **Undo / redo + undo grouping.** `Song.undo/redo/can_undo/
      can_redo` plus `begin_undo_step`/`end_undo_step` to merge a
      multi-step MCP-driven edit into a single user-visible undo.
      Big workflow win — without it, every primitive becomes its
      own undo entry.
      LOM: `Song.undo/redo/can_undo/can_redo/begin_undo_step/
      end_undo_step`.
      Scope: server + remote-script

- [ ] **Transport / recording / metronome settings.** Bundle:
      `metronome`, `count_in_duration`, `record_mode`,
      `arrangement_overdub`, `overdub`, `punch_in`, `punch_out`,
      `midi_recording_quantization`, `clip_trigger_quantization`,
      `session_record`, `session_automation_record`.
      LOM: all under `Song`. Read/write each as an MCP tool or one
      bundled `set_transport_options(**kwargs)` setter.
      Scope: server + remote-script

- [ ] **Take lanes (Live 12).** New Live 12 feature for comping —
      multiple takes layered on a track lane. `Track.take_lanes`,
      `Track.create_take_lane`, plus `Clip.is_take_lane_clip` to
      identify clips that live in a take lane vs. main lane.
      LOM: `Track.take_lanes/create_take_lane`,
      `Clip.is_take_lane_clip`.
      Scope: server + remote-script

- [ ] **Crossfader + cue volume + panning mode.** Master mixer
      controls: `crossfader` (DeviceParameter), per-track
      `crossfade_assign` (A/B/None), `cue_volume` for headphone cue
      send, `panning_mode` (stereo vs split-stereo) + the split
      controls.
      LOM: `MixerDevice.crossfader/crossfade_assign/
      crossfade_assignments/cue_volume/panning_mode/panning_modes/
      left_split_stereo/right_split_stereo`.
      Scope: server + remote-script

- [ ] **Clip launch settings.** `launch_mode` (trigger/gate/toggle/
      repeat), `launch_quantization`, `legato`, `velocity_amount`.
      All session-clip behavior knobs that don't change the notes
      themselves.
      LOM: `Clip.launch_mode/launch_quantization/legato/
      velocity_amount`.
      Scope: server + remote-script

- [ ] **Tap tempo + nudge + back-to-arranger.** `Song.tap_tempo`
      (one tool call per tap), `nudge_up`/`nudge_down` (transient
      tempo nudge), `back_to_arranger` (cancel session-clip
      override and follow arrangement).
      LOM: `Song.tap_tempo/nudge_up/nudge_down/back_to_arranger`.
      Scope: server + remote-script

- [ ] **Read all clip envelopes (round-trip).** Add
      `get_clip_envelopes(track, clip)` returning the full envelope
      list for verification, mirroring `get_clip_notes`. Current
      `get_clip_envelope` reads one parameter at a time.
      LOM: `Clip.automation_envelopes` (plural, Live 12+).
      Scope: server + remote-script

- [ ] **Upgrade clip-envelope tools to Live 12 Envelope API.** The
      Envelope class in Live 12 added `delete_events_in_range`,
      `events_in_range`, `value_at_time`, and
      `EnvelopeEventControlCoefficients(x1,y1,x2,y2)` for bezier
      curves. Existing `add_clip_envelope_point` only writes linear
      steps; expose curved breakpoints + range deletion.
      LOM: `Live.Envelope.Envelope.delete_events_in_range/
      events_in_range/value_at_time`,
      `Live.Envelope.EnvelopeEventControlCoefficients`.
      Scope: server + remote-script

- [ ] **Audio render** — `render_audio(path, length_beats)`. Target is Live
      12; use `Live.Application.Application.render_to_file` directly (no
      version probing). File-write means the audit policy bar is higher.
      Last because drift-01 can bounce by hand once.
      Scope: server + remote-script

- [ ] **Fix `save_session_as` for Live 12.** Current impl probes
      `Song.save_song_as` / `Song.save_as` — both wrong; in Live 12 save-as
      is Application-side, not Song-side. Replace the getattr probe with
      the documented Live 12 Application call directly. lofi-01 will
      exercise it.
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
- **Arrangement-view automation (track-lane + per-clip).** The Python
  LOM does not expose a write path for arrangement-view automation
  breakpoints. Confirmed 2026-04-26 against the Live 12.2.7 LOM dump
  (`tools/ref/Live12.2.7-LOM.xml`): `Clip.automation_envelope` /
  `create_automation_envelope` still document "Returns None for
  Arrangement clips", and Track exposes zero envelope methods (only
  `arrangement_clips` list access and `duplicate_clip_to_arrangement`).
  Live 12 *did* upgrade the Envelope class with richer methods
  (`delete_events_in_range`, `events_in_range`, `value_at_time`, bezier
  `EnvelopeEventControlCoefficients`) — see the audit items above for
  consuming those on session clips — but the arrangement-clip
  restriction is unchanged. AbletonOSC does not implement envelope
  writing. Real-time gesture recording (`arrangement_overdub` +
  `begin_gesture`/`end_gesture` during transport playback) is the only
  LOM-level workaround and doesn't fit MCP's request/response model.
  Until Ableton adds an arrangement-envelope-write API, drift-01-style
  fades stay manual in Live.

## Done (recent)

- 2026-04-26 — Live 12 LOM audit. Regenerated the reference XML against
  Live 12.2.7 via `LiveAPI_MakeDoc` (Py2→Py3 fixes documented in the
  commit message). Read class-by-class and added 22 discrete backlog
  items covering audio/return tracks, scenes, sends, routing, arm/freeze,
  cue points, scale awareness, capture-MIDI, quantize, audio-clip warp/
  pitch/gain, warp markers, groove pool, color, group/fold, undo,
  recording/metronome, take lanes, crossfader, clip launch settings,
  tap/nudge/back-to-arranger, envelope round-trip, and Live-12 envelope-
  API upgrade. Confirmed the arrangement-automation gap persists in
  Live 12 — Won't-do entry updated.

- 2026-04-26 — NDJSON framing on the Live<->MCP socket. Both sides now
  write `json.dumps(x) + "\n"` and read line-by-line; replaced the
  "json.loads after each chunk" framing heuristic with a per-connection
  byte buffer + `_read_line`. Dropped the 100ms pre/post sleeps in
  `send_command` (200ms off every modifying call). Updated `tools/probe.py`
  to match. Pipelined-frame test on a single socket now passes.

- 2026-04-26 — `get_clip_notes` for round-trip note verification; fixed
  `clear_clip_notes` / `replace_clip_notes` no-op bug by porting all
  MIDI-note handlers (incl. `add_notes_to_clip`) to the Live 11+ extended
  API (`add_new_notes` / `remove_notes_extended` / `get_notes_extended` /
  `MidiNoteSpecification`). Old `set_notes` / `select_all_notes` /
  `replace_selected_notes` paths surfaced Live's "older process" warning.

- 2026-04-26 — `get_transport_state` (playback state, current beat, tempo,
  loop region) — closes the lofi-01 silent-playback diagnosis gap.

- 2026-04-25 — track-mixer setters (`set_track_volume`, `set_track_pan`,
  `set_track_mute`, `set_track_solo`) and master setters
  (`set_master_volume`, `set_master_pan`).
- 2026-04-25 — #6 registry-pattern dispatcher; #7 TOOLS.md cheatsheet;
  `delete_session_clip`, `set_transport_position`, `start_playback(from_beats)`,
  `save_session`, `save_session_as`; type-hint modernization to 3.10+;
  `_MODIFYING_COMMANDS` hoisted to constant; build artifacts cleaned;
  `.mcp.json` gitignored.
