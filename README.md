# ableton-mcp

An MCP bridge between Claude and Ableton Live with read/write access to device parameters and Arrangement-view control, alongside the standard track/clip/transport/browser-load tools.

Run as a local `uvx` package; no network egress beyond the localhost socket to Ableton's Remote Script.

## What this fork adds

**Device parameters** (read + write any device's parameters by index)

- `list_devices(track_index)`
- `get_device_parameters(track_index, device_index)`
- `set_device_parameter(track_index, device_index, parameter_index, value)`

**Arrangement view v1** — clip placement, loop region, clip edits

- `list_arrangement_clips(track_index)`
- `add_session_clip_to_arrangement(track_index, session_clip_index, position)`
- `create_arrangement_midi_clip(track_index, start_time, end_time)`
- `set_arrangement_clip_position` / `set_arrangement_clip_loop` / `set_arrangement_clip_markers`
- `delete_arrangement_clip(track_index, arr_clip_index)`
- `set_arrangement_loop(start_beats, length_beats)`

**Clip note editing** (fixes upstream's append-only `add_notes_to_clip`)

- `clear_clip_notes(track_index, clip_index, is_arrangement=False)`
- `replace_clip_notes(track_index, clip_index, notes, is_arrangement=False)`

**Mixer envelope automation** on session clips (`volume`, `panning`, `send:N`)

- `add_clip_envelope_point` / `clear_clip_envelope` / `get_clip_envelope`

### Deferred (not in this fork yet)

- **Audio render / export** — Live's `render_audio` API needs verification before wiring up file writes.
- **Device-parameter automation** (`device:I:param:J` envelope paths). Mixer params only for now.
- **Arrangement-view mixer automation.** Live's `Clip.automation_envelope` rejects arrangement clips for mixer params; arrangement-track automation lives on the track timeline lane (a different API surface). Workaround: build automation in a session clip, then place the clip into the arrangement.

## Components

1. **Ableton Remote Script** (`AbletonMCP_Remote_Script/__init__.py`) — MIDI Remote Script that opens a localhost TCP socket inside Ableton and dispatches commands to the Live API.
2. **MCP Server** (`MCP_Server/server.py`) — FastMCP server that exposes tools to the LLM and forwards them as JSON commands to the Remote Script.

## Installation

### Prerequisites

- Ableton Live 10 or newer (developed against Live 12 Standard)
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) — `brew install uv` on macOS

### 1. Install the Remote Script

Copy `AbletonMCP_Remote_Script/` (the folder, renamed to `AbletonMCP/`) into Ableton's User Remote Scripts directory, or symlink it (recommended for development):

```bash
ln -sfn "$(pwd)/AbletonMCP_Remote_Script/__init__.py" \
  "$HOME/Music/Ableton/User Library/Remote Scripts/AbletonMCP/__init__.py"
```

(The directory `Remote Scripts/AbletonMCP/` must exist; create it if needed.)

Then in Ableton: **Preferences → Link, Tempo & MIDI → Control Surface dropdown → AbletonMCP**. Input and Output: **None**.

Editing the Remote Script requires a full Ableton **⌘Q + relaunch** to reload — toggling the Control Surface is not enough.

### 2. Configure the MCP server

In your Claude Code project's `.mcp.json` (or Claude Desktop config):

```json
{
  "mcpServers": {
    "AbletonMCP": {
      "command": "uvx",
      "args": ["--from", "/path/to/this/fork", "ableton-mcp"]
    }
  }
}
```

`uvx` caches build archives by package version. When editing the fork's source, **bump `pyproject.toml` `version`** before relaunching Claude — `--refresh` and `--reinstall` alone don't invalidate the cache.

Editing `MCP_Server/server.py` requires a full Claude Code restart (the tool registry is per-conversation).

## Tool reference

All upstream tools remain available. New tools are listed in [What this fork adds](#what-this-fork-adds) above. Each tool's docstring (visible to the LLM) describes parameter formats and edge cases.

For mixer-envelope automation, `parameter_path` accepts:

- `"volume"` — `track.mixer_device.volume`
- `"panning"` (or `"pan"`) — `track.mixer_device.panning`
- `"send:N"` — `track.mixer_device.sends[N]` (e.g. `"send:0"` for return A)

Values are clamped to each parameter's `[min, max]`; out-of-range writes raise.

## Communication protocol

Localhost TCP socket on port `9877`. Newline-terminated JSON objects:

- Request: `{"type": "<command>", "params": {...}}`
- Response: `{"status": "success", "result": ...}` or `{"status": "error", "message": "..."}`

No outbound network calls; no filesystem writes. The MCP server connects to Ableton; Ableton listens locally.

## Troubleshooting

- **`Connection refused`** — Remote Script isn't loaded. Re-check Preferences → Control Surface dropdown.
- **`Unknown command: <name>`** — the Remote Script on disk is newer than what Live has loaded. Fully restart Live.
- **New tools not visible to Claude** — bump `pyproject.toml` `version` and restart Claude Code.
- **`Connection reset by peer` on first call after Live restart** — known one-shot; retry, it succeeds.

## Credits

Original project by [Siddharth Ahuja](https://github.com/ahujasid/ableton-mcp) ([Discord](https://discord.gg/3ZrMyGKnaU)). This fork is a personal extension; bug reports for upstream-only behavior should go to the upstream repo.

MIT license, unchanged from upstream. Not affiliated with Ableton.
