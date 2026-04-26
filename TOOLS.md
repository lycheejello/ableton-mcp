# Tools

Flat reference for every MCP tool the server exposes. Hand-written; keep in
sync when you add a tool. For full docstrings (parameter quirks, error
modes, LOM caveats) read the `@mcp.tool` definitions in `MCP_Server/server.py`.

Indices are positional: arrangement-clip indices shift when clips are added
or deleted — re-list before mutating.

## Session & transport

| Tool | Signature | Purpose |
| --- | --- | --- |
| `get_session_info` | `()` | Tempo, time signature, track counts, master volume/pan. |
| `get_transport_state` | `()` | Playback state, current beat, loop region — confirm what Live is actually doing. |
| `set_tempo` | `(tempo: float)` | Set BPM. |
| `start_playback` | `(from_beats: float = None)` | Start playing; optionally scrub the arrangement cursor first. |
| `stop_playback` | `()` | Stop. |
| `set_transport_position` | `(beats: float)` | Move arrangement cursor without starting playback. |
| `set_arrangement_loop` | `(start_beats, length_beats)` | Set the loop brace region (doesn't enable looping). |
| `save_session` | `()` | Save the set to its existing path; fails for untitled sets. |
| `save_session_as` | `(path: str)` | Save the set to a new absolute `.als` path. |

## Tracks

| Tool | Signature | Purpose |
| --- | --- | --- |
| `get_track_info` | `(track_index)` | Track name, mute/solo/arm, volume/pan, clip slots, devices. |
| `create_midi_track` | `(index: int = -1)` | Insert a MIDI track (-1 = end of list). |
| `set_track_name` | `(track_index, name)` | Rename a track. |
| `set_track_volume` | `(track_index, value: float)` | Mixer volume, 0.0–1.0 (0.85 ≈ 0 dB). |
| `set_track_pan` | `(track_index, value: float)` | Pan, -1.0–1.0; 0.0 = center. |
| `set_track_mute` | `(track_index, mute: bool)` | Set the mute flag. |
| `set_track_solo` | `(track_index, solo: bool)` | Set the solo flag. |
| `get_track_sends` | `(track_index)` | List a track's sends with the matching return-track names. |
| `set_track_send` | `(track_index, send_index, value: float)` | Send level to `return_tracks[send_index]`, 0.0–1.0. |
| `set_master_volume` | `(value: float)` | Master volume, 0.0–1.0. |
| `set_master_pan` | `(value: float)` | Master pan, -1.0–1.0. |

## Session clips

| Tool | Signature | Purpose |
| --- | --- | --- |
| `create_clip` | `(track_index, clip_index, length: float = 4.0)` | Create empty MIDI clip in a session slot. |
| `set_clip_name` | `(track_index, clip_index, name)` | Rename a session clip. |
| `delete_session_clip` | `(track_index, clip_slot_index)` | Empty a session slot; no-op if already empty. |
| `fire_clip` | `(track_index, clip_index)` | Launch the clip in a slot. |
| `stop_clip` | `(track_index, clip_index)` | Stop the clip in a slot. |

## Arrangement clips

| Tool | Signature | Purpose |
| --- | --- | --- |
| `list_arrangement_clips` | `(track_index)` | Per-clip index, position, length, loop, type. Indices shift on mutate. |
| `add_session_clip_to_arrangement` | `(track_index, session_clip_index, position)` | Duplicate a session clip onto the arrangement timeline. |
| `create_arrangement_midi_clip` | `(track_index, start_time, end_time)` | Empty MIDI clip on the arrangement timeline. |
| `set_arrangement_clip_position` | `(track_index, arr_clip_index, position)` | Move clip; refuses if it would overlap. |
| `set_arrangement_clip_loop` | `(track_index, arr_clip_index, loop_start, loop_end, looping)` | Loop region (clip-local beats) + looping flag. |
| `set_arrangement_clip_markers` | `(track_index, arr_clip_index, start_marker, end_marker)` | Playable region within the clip (audio: trim region). |
| `delete_arrangement_clip` | `(track_index, arr_clip_index)` | Remove arrangement clip. Subsequent indices shift. |

## MIDI notes

| Tool | Signature | Purpose |
| --- | --- | --- |
| `add_notes_to_clip` | `(track_index, clip_index, notes)` | Append notes to a session clip. |
| `get_clip_notes` | `(track_index, clip_index, is_arrangement=False)` | Read existing notes from a clip — round-trip verification. |
| `replace_clip_notes` | `(track_index, clip_index, notes, is_arrangement=False)` | Replace all notes on a clip. |
| `clear_clip_notes` | `(track_index, clip_index, is_arrangement=False)` | Wipe all notes; clip stays. |

Note dict shape: `{pitch, start_time, duration, velocity, mute}`.

## Devices

| Tool | Signature | Purpose |
| --- | --- | --- |
| `list_devices` | `(track_index)` | Per-device index, name, class, type. |
| `get_device_parameters` | `(track_index, device_index)` | Per-param index, name, value, min/max, is_quantized, value_items. |
| `set_device_parameter` | `(track_index, device_index, parameter_index, value)` | Set one param by index. Re-fetch indices per session for plugins. |
| `load_instrument_or_effect` | `(track_index, uri)` | Load a browser item by URI. |
| `load_drum_kit` | `(track_index, rack_uri, kit_path)` | Load a drum rack then a kit into it. |

## Clip automation

`parameter_path`: `volume`, `panning` (or `pan`), `send:N`, `device:I:param:J`.

| Tool | Signature | Purpose |
| --- | --- | --- |
| `add_clip_envelope_point` | `(track_index, clip_index, parameter_path, time, value, is_arrangement=False)` | Add an automation point. Session clips only — `is_arrangement=True` currently errors at the LOM (see BACKLOG). |
| `clear_clip_envelope` | `(track_index, clip_index, parameter_path, is_arrangement=False)` | Remove all envelope points for one parameter. |
| `get_clip_envelope` | `(track_index, clip_index, parameter_path, is_arrangement=False)` | Sample envelope at integer beats — coarse sanity check. |

## Browser

| Tool | Signature | Purpose |
| --- | --- | --- |
| `get_browser_tree` | `(category_type: str = "all")` | Hierarchical tree of browser categories. |
| `get_browser_items_at_path` | `(path: str)` | Items at `category/folder/...`. |
