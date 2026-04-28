# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

# Commands that mutate Live's state. The Remote Script schedules these on Live's
# main thread; we add small pre/post delays and a longer timeout for them.
# Keep in sync with the on_main_thread=True entries in the Remote Script's
# COMMANDS registry (AbletonMCP_Remote_Script/__init__.py).
_MODIFYING_COMMANDS = frozenset({
    "create_midi_track", "create_audio_track", "delete_track", "set_track_arm",
    "set_song_record_mode", "set_input_routing",
    "set_track_name",
    "set_track_volume", "set_track_pan", "set_track_mute", "set_track_solo",
    "set_track_send",
    "set_master_volume", "set_master_pan",
    "set_return_track_volume", "set_return_track_pan",
    "set_return_track_mute", "set_return_track_solo",
    "set_return_device_parameter", "load_return_effect",
    "set_master_device_parameter", "load_master_effect",
    "delete_track_device", "delete_return_device", "delete_master_device",
    "create_clip", "add_notes_to_clip", "set_clip_name",
    "set_tempo", "fire_clip", "stop_clip", "set_device_parameter",
    "start_playback", "stop_playback", "load_instrument_or_effect",
    "load_browser_item",
    "add_session_clip_to_arrangement", "update_arrangement_clip_from_session", "create_arrangement_midi_clip",
    "set_arrangement_clip_position", "set_arrangement_clip_loop",
    "set_arrangement_clip_markers", "delete_arrangement_clip",
    "set_arrangement_loop", "clear_clip_notes", "replace_clip_notes",
    "add_clip_envelope_point", "add_clip_envelope_ramp", "clear_clip_envelope",
    "set_transport_position",
    "delete_session_clip",
    "set_or_delete_cue", "set_cue_name", "place_cue", "jump_to_cue", "jump_to_next_cue", "jump_to_prev_cue",
    "undo", "redo", "begin_undo_step", "end_undo_step",
})

@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    _recv_buffer: bytes = b""

    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            self._recv_buffer = b""
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False

    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None
                self._recv_buffer = b""

    def _read_line(self, buffer_size: int = 8192) -> bytes:
        """Read one newline-terminated frame from the socket. The trailing
        newline is stripped from the returned bytes."""
        while b"\n" not in self._recv_buffer:
            chunk = self.sock.recv(buffer_size)
            if not chunk:
                raise Exception("Connection closed before receiving full response")
            self._recv_buffer += chunk
        line, _, self._recv_buffer = self._recv_buffer.partition(b"\n")
        return line

    def send_command(self, command_type: str, params: dict[str, Any] = None) -> dict[str, Any]:
        """Send a command to Ableton and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")

        command = {
            "type": command_type,
            "params": params or {}
        }

        is_modifying_command = command_type in _MODIFYING_COMMANDS

        try:
            logger.info(f"Sending command: {command_type} with params: {params}")

            # NDJSON framing: one JSON object per line, both directions.
            self.sock.sendall((json.dumps(command) + "\n").encode("utf-8"))
            logger.info("Command sent, waiting for response...")

            timeout = 15.0 if is_modifying_command else 10.0
            self.sock.settimeout(timeout)

            response_data = self._read_line()
            logger.info(f"Received {len(response_data)} bytes of data")

            response = json.loads(response_data.decode("utf-8"))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")

            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))

            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")

        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")

        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCP",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection

    if _ableton_connection is not None:
        try:
            # Test the connection with a simple ping
            # We'll try to send an empty message, which should fail if the connection is dead
            # but won't affect Ableton if it's alive
            _ableton_connection.sock.settimeout(1.0)
            _ableton_connection.sock.sendall(b'')
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None

    # Connection doesn't exist or is invalid, create a new one
    if _ableton_connection is None:
        # Try to connect up to 3 times with a short delay between attempts
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host="localhost", port=9877)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")

                    # Validate connection with a simple command
                    try:
                        # Get session info as a test
                        _ableton_connection.send_command("get_session_info")
                        logger.info("Connection validated successfully")
                        return _ableton_connection
                    except Exception as e:
                        logger.error(f"Connection validation failed: {str(e)}")
                        _ableton_connection.disconnect()
                        _ableton_connection = None
                        # Continue to next attempt
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None

            # Wait before trying again, but only if we have more attempts left
            if attempt < max_attempts:
                import time
                time.sleep(1.0)

        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")

    return _ableton_connection


def _call(command: str, params: dict[str, Any] = None) -> dict[str, Any]:
    """Send a command to Ableton and return the parsed result. Raises on error.

    Used by tools that need to inspect or post-process the result.
    """
    return get_ableton_connection().send_command(command, params)


def _forward(command: str, params: dict[str, Any] = None, label: str = None) -> str:
    """Forward a command to Ableton and return its result as JSON, or an error string.

    Used by the majority of tools that just relay parameters and dump the response.
    `label` is used in error messages; defaults to the command name with underscores
    replaced by spaces (e.g. "set_tempo" -> "set tempo").
    """
    label = label or command.replace("_", " ")
    try:
        return json.dumps(_call(command, params), indent=2)
    except Exception as e:
        logger.error(f"Error in {label}: {e}")
        return f"Error in {label}: {e}"


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    return _forward("get_session_info")

@mcp.tool()
def get_transport_state(ctx: Context) -> str:
    """
    Read playback state, arrangement-cursor position, and loop region.

    Returns is_playing, current_beat, tempo, loop_enabled, loop_start,
    loop_length, loop_end. Pairs with start_playback / stop_playback /
    set_transport_position when you need to confirm what Live is actually
    doing rather than assuming.
    """
    return _forward("get_transport_state")

@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.

    Parameters:
    - track_index: The index of the track to get information about
    """
    return _forward("get_track_info", {"track_index": track_index})

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    return _forward("create_midi_track", {"index": index})

@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track in the Ableton session.

    Used as the destination for printing MIDI tracks to audio (set its input routing
    to the source MIDI track, arm it, enable record_mode, play through the region).

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    return _forward("create_audio_track", {"index": index})

@mcp.tool()
def delete_track(ctx: Context, track_index: int) -> str:
    """
    Delete a regular track by index.

    song.tracks excludes master/return tracks (those use separate LOM accessors), so any
    valid track_index here refers to a regular or group track. Track indices SHIFT after
    deletion — re-list with get_session_info before deleting more.
    """
    return _forward("delete_track", {"track_index": track_index})

@mcp.tool()
def set_track_arm(ctx: Context, track_index: int, armed: bool) -> str:
    """
    Arm or disarm a track for recording.

    Errors on Main and Send tracks (not armable per LOM). Armed tracks accept input
    when Song.record_mode is enabled and transport is rolling.
    """
    return _forward("set_track_arm", {"track_index": track_index, "armed": armed})

@mcp.tool()
def set_song_record_mode(ctx: Context, enabled: bool) -> str:
    """
    Set Song.record_mode — Live's global arrangement-record flag.

    When True and transport is rolling, armed tracks record their input into the
    arrangement at the current cursor position. Pair with set_track_arm for the
    print-to-audio workflow.

    Returns {requested_record_mode: bool} — the *requested* state, not a
    readback. Live commits the write on the next tick, so a same-frame
    readback lies on the first call from a cold session. Trust the absence
    of an error; for ground truth, call get_transport_state on a later tick.
    """
    return _forward("set_song_record_mode", {"enabled": enabled})

@mcp.tool()
def get_input_routing(ctx: Context, track_index: int) -> str:
    """
    Read a track's current input routing + the discoverable lists of available types/channels.

    Returns:
    - current_type / current_channel: display names of the active routing
    - available_types: routing source options (e.g. "Ext. In", "1-MIDI", "Resampling", master/return names)
    - available_channels: subdivisions of the current type (e.g. "Post FX", "1/2", "Pre FX")

    Use this to discover the right type_name + channel_name to pass to set_input_routing.
    """
    return _forward("get_input_routing", {"track_index": track_index})

@mcp.tool()
def set_input_routing(ctx: Context, track_index: int, type_name: str = None, channel_name: str = None) -> str:
    """
    Set a track's input routing by display_name.

    For printing a MIDI track to audio: create an audio track, then call this with
    type_name="<MIDI track name>" and channel_name="Post FX" so the audio track
    captures the MIDI track's instrument output through its full FX chain.

    Pass None for either argument to leave that side untouched. Errors with the list
    of available names if the requested name isn't a valid option.
    """
    payload = {"track_index": track_index}
    if type_name is not None:
        payload["type_name"] = type_name
    if channel_name is not None:
        payload["channel_name"] = channel_name
    return _forward("set_input_routing", payload)

@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.

    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    return _forward("set_track_name", {"track_index": track_index, "name": name})

@mcp.tool()
def set_track_volume(ctx: Context, track_index: int, value: float) -> str:
    """
    Set a track's mixer volume.

    Parameters:
    - track_index: The index of the track
    - value: Live-native float, 0.0–1.0 (0.85 ≈ 0 dB, 1.0 = +6 dB)
    """
    return _forward("set_track_volume", {"track_index": track_index, "value": value})

@mcp.tool()
def set_track_pan(ctx: Context, track_index: int, value: float) -> str:
    """
    Set a track's mixer panning.

    Parameters:
    - track_index: The index of the track
    - value: Live-native float, -1.0 (full left) to 1.0 (full right); 0.0 = center
    """
    return _forward("set_track_pan", {"track_index": track_index, "value": value})

@mcp.tool()
def set_track_mute(ctx: Context, track_index: int, mute: bool) -> str:
    """
    Set a track's mute flag.

    Parameters:
    - track_index: The index of the track
    - mute: True to mute, False to unmute
    """
    return _forward("set_track_mute", {"track_index": track_index, "mute": mute})

@mcp.tool()
def set_track_solo(ctx: Context, track_index: int, solo: bool) -> str:
    """
    Set a track's solo flag.

    Parameters:
    - track_index: The index of the track
    - solo: True to solo, False to clear
    """
    return _forward("set_track_solo", {"track_index": track_index, "solo": solo})

@mcp.tool()
def get_track_sends(ctx: Context, track_index: int) -> str:
    """
    List a track's sends (return routing). Each send routes to the return track
    at the matching index in the song's return tracks; the response includes
    each return's name so "more reverb on the vocal" can be mapped to a send index.

    Parameters:
    - track_index: Index into song.tracks (regular tracks; master/returns not supported)
    """
    return _forward("get_track_sends", {"track_index": track_index})

@mcp.tool()
def set_track_send(ctx: Context, track_index: int, send_index: int, value: float) -> str:
    """
    Set a track's send level (return routing).

    Parameters:
    - track_index: Index into song.tracks (regular tracks only)
    - send_index: Index into the track's send list; matches song.return_tracks[send_index]
    - value: Live-native float, 0.0–1.0 (0.85 ≈ 0 dB, same convention as volume)
    """
    return _forward("set_track_send", {"track_index": track_index, "send_index": send_index, "value": value})

@mcp.tool()
def set_master_volume(ctx: Context, value: float) -> str:
    """
    Set the master track's volume.

    Parameters:
    - value: Live-native float, 0.0–1.0 (0.85 ≈ 0 dB, 1.0 = +6 dB)
    """
    return _forward("set_master_volume", {"value": value})

@mcp.tool()
def set_master_pan(ctx: Context, value: float) -> str:
    """
    Set the master track's panning.

    Parameters:
    - value: Live-native float, -1.0 (full left) to 1.0 (full right); 0.0 = center
    """
    return _forward("set_master_pan", {"value": value})

# Return tracks live under song.return_tracks, separate from song.tracks. The
# regular track-addressed tools (set_track_*, list_devices, load_instrument_or_effect,
# set_device_parameter) all reject return-track indices. Use these variants for
# send-effect setup (reverb buses, delay throws, etc).

@mcp.tool()
def get_return_track_info(ctx: Context, return_index: int) -> str:
    """
    Inspect a return track: name, mixer state, and device chain. Use
    get_session_info for the count, then this for per-return detail.

    Parameters:
    - return_index: Index into song.return_tracks
    """
    return _forward("get_return_track_info", {"return_index": return_index})

@mcp.tool()
def list_return_devices(ctx: Context, return_index: int) -> str:
    """
    List the devices on a return track. Same shape as list_devices.

    Parameters:
    - return_index: Index into song.return_tracks
    """
    return _forward("list_return_devices", {"return_index": return_index})

@mcp.tool()
def get_return_device_parameters(ctx: Context, return_index: int, device_index: int) -> str:
    """
    Get the parameters of a device on a return track. Same shape as
    get_device_parameters.

    Parameters:
    - return_index: Index into song.return_tracks
    - device_index: Index of the device on that return track
    """
    return _forward("get_return_device_parameters", {
        "return_index": return_index,
        "device_index": device_index,
    })

@mcp.tool()
def set_return_device_parameter(
    ctx: Context,
    return_index: int,
    device_index: int,
    parameter_index: int,
    value: float,
) -> str:
    """
    Set a single device parameter on a return track. Same semantics as
    set_device_parameter (call get_return_device_parameters first; do not
    cache indices across sessions).

    Parameters:
    - return_index: Index into song.return_tracks
    - device_index: Index of the device on that return track
    - parameter_index: Index of the parameter
    - value: New value (continuous: within [min, max]; quantized: integer
      index into value_items)
    """
    return _forward("set_return_device_parameter", {
        "return_index": return_index,
        "device_index": device_index,
        "parameter_index": parameter_index,
        "value": value,
    })

@mcp.tool()
def load_return_effect(ctx: Context, return_index: int, uri: str) -> str:
    """
    Load an audio effect onto a return track using its URI. Mirrors
    load_instrument_or_effect for return tracks; instruments don't apply
    here (returns are audio-only).

    Parameters:
    - return_index: Index into song.return_tracks
    - uri: Browser item URI (use get_browser_items_at_path to find one)
    """
    try:
        result = _call("load_return_effect", {"return_index": return_index, "item_uri": uri})
        if not result.get("loaded", False):
            return f"Failed to load effect with URI '{uri}'"
        return f"Loaded '{result.get('item_name')}' onto return track {return_index} ({result.get('track_name')})"
    except Exception as e:
        logger.error(f"Error loading return effect: {e}")
        return f"Error loading return effect: {e}"

@mcp.tool()
def set_return_track_volume(ctx: Context, return_index: int, value: float) -> str:
    """
    Set a return track's mixer volume.

    Parameters:
    - return_index: Index into song.return_tracks
    - value: Live-native float, 0.0–1.0 (0.85 ≈ 0 dB, 1.0 = +6 dB)
    """
    return _forward("set_return_track_volume", {"return_index": return_index, "value": value})

@mcp.tool()
def set_return_track_pan(ctx: Context, return_index: int, value: float) -> str:
    """
    Set a return track's mixer panning.

    Parameters:
    - return_index: Index into song.return_tracks
    - value: Live-native float, -1.0 (full left) to 1.0 (full right); 0.0 = center
    """
    return _forward("set_return_track_pan", {"return_index": return_index, "value": value})

@mcp.tool()
def set_return_track_mute(ctx: Context, return_index: int, mute: bool) -> str:
    """
    Set a return track's mute flag.

    Parameters:
    - return_index: Index into song.return_tracks
    - mute: True to mute, False to unmute
    """
    return _forward("set_return_track_mute", {"return_index": return_index, "mute": mute})

@mcp.tool()
def set_return_track_solo(ctx: Context, return_index: int, solo: bool) -> str:
    """
    Set a return track's solo flag.

    Parameters:
    - return_index: Index into song.return_tracks
    - solo: True to solo, False to clear
    """
    return _forward("set_return_track_solo", {"return_index": return_index, "solo": solo})

# Master track is a single track outside song.tracks. set_master_volume /
# set_master_pan already exist; these add the device-chain surface for
# mix-bus polish (glue comp, master EQ, limiter).

@mcp.tool()
def get_master_track_info(ctx: Context) -> str:
    """
    Inspect the master track: name, mixer state, and device chain.
    """
    return _forward("get_master_track_info", {})

@mcp.tool()
def list_master_devices(ctx: Context) -> str:
    """
    List the devices on the master track.
    """
    return _forward("list_master_devices", {})

@mcp.tool()
def get_master_device_parameters(ctx: Context, device_index: int) -> str:
    """
    Get the parameters of a device on the master track. Same shape as
    get_device_parameters.

    Parameters:
    - device_index: Index of the device on the master track
    """
    return _forward("get_master_device_parameters", {"device_index": device_index})

@mcp.tool()
def set_master_device_parameter(
    ctx: Context,
    device_index: int,
    parameter_index: int,
    value: float,
) -> str:
    """
    Set a single device parameter on the master track. Same semantics as
    set_device_parameter (call get_master_device_parameters first; do not
    cache indices across sessions).

    Parameters:
    - device_index: Index of the device on the master track
    - parameter_index: Index of the parameter
    - value: New value (continuous: within [min, max]; quantized: integer
      index into value_items)
    """
    return _forward("set_master_device_parameter", {
        "device_index": device_index,
        "parameter_index": parameter_index,
        "value": value,
    })

@mcp.tool()
def delete_track_device(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Delete a device from a regular track's chain.

    Note: subsequent device indices shift down after deletion. Re-list
    via list_devices before deleting more from the same chain.

    Parameters:
    - track_index: Index into song.tracks
    - device_index: Index of the device to delete
    """
    return _forward("delete_track_device", {"track_index": track_index, "device_index": device_index})

@mcp.tool()
def delete_return_device(ctx: Context, return_index: int, device_index: int) -> str:
    """
    Delete a device from a return track's chain.

    Note: subsequent device indices shift down after deletion. Re-list
    via list_return_devices before deleting more from the same chain.

    Parameters:
    - return_index: Index into song.return_tracks
    - device_index: Index of the device to delete
    """
    return _forward("delete_return_device", {"return_index": return_index, "device_index": device_index})

@mcp.tool()
def delete_master_device(ctx: Context, device_index: int) -> str:
    """
    Delete a device from the master track's chain.

    Note: subsequent device indices shift down after deletion. Re-list
    via list_master_devices before deleting more.

    Parameters:
    - device_index: Index of the device to delete
    """
    return _forward("delete_master_device", {"device_index": device_index})

@mcp.tool()
def load_master_effect(ctx: Context, uri: str) -> str:
    """
    Load an audio effect onto the master track using its URI. Mirrors
    load_return_effect for the master bus; instruments don't apply
    (master is audio-only).

    Parameters:
    - uri: Browser item URI (use get_browser_items_at_path to find one)
    """
    try:
        result = _call("load_master_effect", {"item_uri": uri})
        if not result.get("loaded", False):
            return f"Failed to load effect with URI '{uri}'"
        return f"Loaded '{result.get('item_name')}' onto master track"
    except Exception as e:
        logger.error(f"Error loading master effect: {e}")
        return f"Error loading master effect: {e}"

@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.

    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    return _forward("create_clip", {
        "track_index": track_index,
        "clip_index": clip_index,
        "length": length,
    })

@mcp.tool()
def add_notes_to_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    notes: list[dict[str, int | float | bool]]
) -> str:
    """
    Add MIDI notes to a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    return _forward("add_notes_to_clip", {
        "track_index": track_index,
        "clip_index": clip_index,
        "notes": notes,
    })

@mcp.tool()
def get_clip_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    is_arrangement: bool = False,
) -> str:
    """
    Read MIDI notes from a clip.

    Returns {note_count, notes: [{pitch, start_time, duration, velocity, mute}, ...]}.
    Works for session clips (default) and arrangement clips (is_arrangement=True).
    Useful for round-trip verification after add_notes_to_clip / replace_clip_notes.
    """
    return _forward("get_clip_notes", {
        "track_index": track_index,
        "clip_index": clip_index,
        "is_arrangement": is_arrangement,
    })

@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    return _forward("set_clip_name", {
        "track_index": track_index,
        "clip_index": clip_index,
        "name": name,
    })

@mcp.tool()
def list_devices(ctx: Context, track_index: int) -> str:
    """
    List the devices on a track.

    Parameters:
    - track_index: The index of the track

    Returns JSON with each device's index, name, class_name, and type.
    """
    return _forward("list_devices", {"track_index": track_index})

@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Get the parameters of a device on a track.

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the device on that track (use list_devices to find it)

    Returns JSON with each parameter's index, name, value, min, max, is_quantized,
    and value_items (list of label strings if the parameter is quantized, else null).
    For VST/AU plugins, parameter names may be opaque (e.g. "Param 17") if the
    plugin doesn't expose them to Live.
    """
    return _forward("get_device_parameters", {
        "track_index": track_index,
        "device_index": device_index,
    })

@mcp.tool()
def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter_index: int,
    value: float,
) -> str:
    """
    Set a single device parameter by index.

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the device on that track
    - parameter_index: The index of the parameter (from get_device_parameters)
    - value: The new value. For continuous parameters, must be within [min, max].
      For quantized parameters (is_quantized=True), pass the integer index into
      value_items.

    Parameter ordering for plugins is not guaranteed across plugin versions —
    call get_device_parameters first; do not cache indices across sessions.
    """
    return _forward("set_device_parameter", {
        "track_index": track_index,
        "device_index": device_index,
        "parameter_index": parameter_index,
        "value": value,
    })

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.

    Parameters:
    - tempo: The new tempo in BPM
    """
    return _forward("set_tempo", {"tempo": tempo})


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.

    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    try:
        result = _call("load_browser_item", {"track_index": track_index, "item_uri": uri})
        if not result.get("loaded", False):
            return f"Failed to load instrument with URI '{uri}'"
        new_devices = result.get("new_devices", [])
        if new_devices:
            return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
        devices = result.get("devices_after", [])
        return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {e}")
        return f"Error loading instrument by URI: {e}"

@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    return _forward("fire_clip", {"track_index": track_index, "clip_index": clip_index})

@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    return _forward("stop_clip", {"track_index": track_index, "clip_index": clip_index})

@mcp.tool()
def start_playback(ctx: Context, from_beats: float = None) -> str:
    """
    Start playing the Ableton session.

    Parameters:
    - from_beats: optional arrangement-time position (in beats) to scrub to
      before starting playback. Omit to play from Live's current cursor.
    """
    params = {}
    if from_beats is not None:
        params["from_beats"] = from_beats
    return _forward("start_playback", params)

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    return _forward("stop_playback")

@mcp.tool()
def set_transport_position(ctx: Context, beats: float) -> str:
    """
    Move the arrangement cursor to a beat position without starting playback.

    Pair with start_playback for "play from beat N" workflows; or use
    start_playback(from_beats=...) directly to do both in one call.
    """
    return _forward("set_transport_position", {"beats": beats})

@mcp.tool()
def get_cue_points(ctx: Context) -> str:
    """
    List arrangement cue points (locators) with their names and beat positions.

    Cue names are the bridge from natural-language regions ("in the bridge",
    "at the drop") to a beat position. Pair with set_transport_position(beats=cue.time)
    or jump_to_cue(cue_index) to seek. Cue indices are positional and shift if
    cues are added/removed — re-fetch before navigating.
    """
    return _forward("get_cue_points")

@mcp.tool()
def set_or_delete_cue(ctx: Context) -> str:
    """
    Toggle a cue point at the current arrangement cursor.

    Mirrors Live's native "Set/Delete Cue" command: creates a cue at the
    current position, or deletes the one already there. Use
    set_transport_position(beats=...) first to place the cursor.
    """
    return _forward("set_or_delete_cue")

@mcp.tool()
def place_cue(ctx: Context, beat: float, name: str = "") -> str:
    """
    Place a cue point at the given beat, optionally naming it in the same call.

    Idempotent: if a cue already exists at the snapped beat, reuses it (created=False
    in the response) rather than toggling it off. Decoupled from transport — stops
    playback if running and restores both the cursor and play state on exit, so the
    user's view doesn't visibly jump.

    Prefer this over the (set_transport_position → set_or_delete_cue → set_cue_name)
    sequence: it's one round-trip, race-free under playback, and cannot accidentally
    delete an existing cue.

    Parameters:
    - beat: Beat position. Live snaps cue creation to grid; the response's `time`
      reflects the snapped position actually used.
    - name: Optional name. Empty string leaves the cue's existing name untouched.
    """
    return _forward("place_cue", {"beat": beat, "name": name or None})

@mcp.tool()
def set_cue_name(ctx: Context, cue_index: int, name: str) -> str:
    """
    Rename the cue point at the given index.

    Cue names are how the mix-notes interpreter binds locator-scoped notes
    ("in the bridge", "at the drop") to a beat — placing a cue with
    set_or_delete_cue and immediately naming it via this tool is the
    canonical "author a section marker" sequence.

    Parameters:
    - cue_index: Index into the list returned by get_cue_points
    - name: New name for the cue

    Cue indices shift when cues are added/removed — re-list before renaming.
    """
    return _forward("set_cue_name", {"cue_index": cue_index, "name": name})

@mcp.tool()
def jump_to_cue(ctx: Context, cue_index: int) -> str:
    """
    Jump the arrangement cursor to the cue point at the given index.

    Parameters:
    - cue_index: Index into the list returned by get_cue_points

    Preserves play state (jumps the cursor whether playing or stopped).
    Cue indices shift when cues are added/removed — re-list before jumping.
    """
    return _forward("jump_to_cue", {"cue_index": cue_index})

@mcp.tool()
def jump_to_next_cue(ctx: Context) -> str:
    """
    Jump to the next cue point relative to the current arrangement cursor.

    No-op if there is no next cue (returns jumped=False).
    """
    return _forward("jump_to_next_cue")

@mcp.tool()
def jump_to_prev_cue(ctx: Context) -> str:
    """
    Jump to the previous cue point relative to the current arrangement cursor.

    No-op if there is no previous cue (returns jumped=False).
    """
    return _forward("jump_to_prev_cue")

@mcp.tool()
def undo(ctx: Context) -> str:
    """
    Undo the last user-visible step in Live's undo history.

    No-op if there is nothing to undo (returns undone=False). Pair with
    begin_undo_step/end_undo_step to make a multi-call agent revision collapse
    into one user-visible undo entry.
    """
    return _forward("undo")

@mcp.tool()
def redo(ctx: Context) -> str:
    """
    Redo the next step in Live's undo history.

    No-op if there is nothing to redo (returns redone=False).
    """
    return _forward("redo")

@mcp.tool()
def begin_undo_step(ctx: Context) -> str:
    """
    Open an undo group. All bridge edits between this call and end_undo_step()
    collapse into a single user-visible undo entry in Live.

    Use this to wrap a complete agent revision (e.g. "more reverb on vocals in
    the bridge" might fan out to a dozen send/EQ/cue calls) so the user can back
    it out with a single Cmd+Z. Always pair with end_undo_step(); leaving a step
    open will fold subsequent unrelated edits into the same undo entry.
    """
    return _forward("begin_undo_step")

@mcp.tool()
def end_undo_step(ctx: Context) -> str:
    """
    Close the undo group opened by begin_undo_step().

    Safe to call without a matching begin (Live ignores it). Returns the
    post-step can_undo/can_redo flags.
    """
    return _forward("end_undo_step")

@mcp.tool()
def delete_session_clip(ctx: Context, track_index: int, clip_slot_index: int) -> str:
    """
    Delete the clip in a session clip slot, leaving the slot empty.

    Symmetry with delete_arrangement_clip. No-op (returns deleted=False) if
    the slot is already empty.
    """
    return _forward("delete_session_clip", {
        "track_index": track_index,
        "clip_slot_index": clip_slot_index,
    })

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.

    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        result = _call("get_browser_tree", {"category_type": category_type})

        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")

        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"

        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)

                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"

                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output

        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"

        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return "Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        if "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return "Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        logger.error(f"Error getting browser tree: {error_msg}")
        return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.

    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        result = _call("get_browser_items_at_path", {"path": path})
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return "Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        if "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return "Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        if "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        if "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        logger.error(f"Error getting browser items at path: {error_msg}")
        return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.

    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        # Step 1: Load the drum rack
        result = _call("load_browser_item", {"track_index": track_index, "item_uri": rack_uri})
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"

        # Step 2: Get the drum kit items at the specified path
        kit_result = _call("get_browser_items_at_path", {"path": kit_path})
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"

        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"

        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        _call("load_browser_item", {"track_index": track_index, "item_uri": kit_uri})
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {e}")
        return f"Error loading drum kit: {e}"

# Arrangement-view tools ------------------------------------------------------

@mcp.tool()
def list_arrangement_clips(ctx: Context, track_index: int) -> str:
    """
    List clips on a track's arrangement timeline (not session clip slots).

    Returns JSON with each arrangement clip's index, name, position (start time
    in beats), end, length, looping/loop_start/loop_end, and is_audio/midi flags.
    Indices are positional and SHIFT when clips are added or deleted — call this
    immediately before mutating; do not cache.
    """
    return _forward("list_arrangement_clips", {"track_index": track_index})

@mcp.tool()
def add_session_clip_to_arrangement(
    ctx: Context, track_index: int, session_clip_index: int, position: float
) -> str:
    """
    Duplicate a session clip onto the arrangement timeline at a given beat position.

    Parameters:
    - track_index: track containing both the session clip and the arrangement timeline
    - session_clip_index: clip slot index in the session view
    - position: arrangement-time start position in beats
    """
    return _forward("add_session_clip_to_arrangement", {
        "track_index": track_index,
        "session_clip_index": session_clip_index,
        "position": position,
    })

@mcp.tool()
def create_arrangement_midi_clip(
    ctx: Context, track_index: int, start_time: float, end_time: float
) -> str:
    """
    Create an empty MIDI clip on the arrangement timeline.

    Parameters:
    - track_index: target track (must be a MIDI track)
    - start_time: beat position where the clip starts
    - end_time: beat position where the clip ends (must be > start_time)
    """
    return _forward("create_arrangement_midi_clip", {
        "track_index": track_index,
        "start_time": start_time,
        "end_time": end_time,
    })

@mcp.tool()
def set_arrangement_clip_position(
    ctx: Context, track_index: int, arr_clip_index: int, position: float
) -> str:
    """
    Move an arrangement clip to a new beat position. Other clips are NOT pushed —
    Live will refuse if the new position would overlap another clip on the same track.
    """
    return _forward("set_arrangement_clip_position", {
        "track_index": track_index,
        "arr_clip_index": arr_clip_index,
        "position": position,
    })

@mcp.tool()
def set_arrangement_clip_loop(
    ctx: Context, track_index: int, arr_clip_index: int,
    loop_start: float, loop_end: float, looping: bool = True
) -> str:
    """
    Set an arrangement clip's loop region (in clip-local beats) and looping flag.
    """
    return _forward("set_arrangement_clip_loop", {
        "track_index": track_index,
        "arr_clip_index": arr_clip_index,
        "loop_start": loop_start,
        "loop_end": loop_end,
        "looping": looping,
    })

@mcp.tool()
def set_arrangement_clip_markers(
    ctx: Context, track_index: int, arr_clip_index: int,
    start_marker: float, end_marker: float
) -> str:
    """
    Set an arrangement clip's start/end markers (clip-local beats) — i.e. the
    playable region within the clip. For audio clips, this is the trim region.
    """
    return _forward("set_arrangement_clip_markers", {
        "track_index": track_index,
        "arr_clip_index": arr_clip_index,
        "start_marker": start_marker,
        "end_marker": end_marker,
    })

@mcp.tool()
def delete_arrangement_clip(ctx: Context, track_index: int, arr_clip_index: int) -> str:
    """Delete an arrangement clip. Indices of subsequent clips shift down by one."""
    return _forward("delete_arrangement_clip", {
        "track_index": track_index,
        "arr_clip_index": arr_clip_index,
    })

@mcp.tool()
def set_arrangement_loop(ctx: Context, start_beats: float, length_beats: float) -> str:
    """
    Set the arrangement loop region (the loop brace shown above the timeline).
    Doesn't enable the loop — use Live's transport for that.
    """
    return _forward("set_arrangement_loop", {
        "start_beats": start_beats,
        "length_beats": length_beats,
    })

@mcp.tool()
def clear_clip_notes(
    ctx: Context, track_index: int, clip_index: int, is_arrangement: bool = False
) -> str:
    """
    Remove all MIDI notes from a clip, leaving the clip itself in place.

    Use this before add_notes_to_clip to truly replace notes — add_notes_to_clip
    appends. Or use replace_clip_notes for the combined operation.

    Parameters:
    - is_arrangement: False = clip_index is a session clip slot (default);
                      True  = clip_index is an arrangement-clip index
    """
    return _forward("clear_clip_notes", {
        "track_index": track_index,
        "clip_index": clip_index,
        "is_arrangement": is_arrangement,
    })

@mcp.tool()
def replace_clip_notes(
    ctx: Context, track_index: int, clip_index: int,
    notes: list[dict[str, int | float | bool]],
    is_arrangement: bool = False,
) -> str:
    """
    Replace (not append) all notes in a MIDI clip with the given list.

    Note format matches add_notes_to_clip: {pitch, start_time, duration, velocity, mute}.
    """
    return _forward("replace_clip_notes", {
        "track_index": track_index,
        "clip_index": clip_index,
        "notes": notes,
        "is_arrangement": is_arrangement,
    })

@mcp.tool()
def add_clip_envelope_point(
    ctx: Context, track_index: int, clip_index: int,
    parameter_path: str, time: float, value: float,
) -> str:
    """
    Add a point to a session clip's automation envelope.

    parameter_path:
    - "volume"
    - "panning" (or "pan")
    - "send:N"            (e.g. "send:0" for return A)
    - "device:I:param:J"  (track.devices[I].parameters[J])

    Time is clip-local beats. Value is range-checked against the parameter's [min, max].
    The envelope is created on first call; subsequent calls add more points.

    Semantics: each call writes a flat region from `time` to clip end. A later call at a higher
    `time` overrides the tail of the earlier region. Result: cliff transitions between flat
    levels — useful for sudden value changes (mute drops, sends turning on/off, instant
    parameter swaps). For smooth fades or curves, use add_clip_envelope_ramp instead.

    SIDE EFFECT: when a session clip with envelopes is placed into the arrangement (via
    add_session_clip_to_arrangement or update_arrangement_clip_from_session), Live materializes
    the envelope as TRACK-LANE arrangement automation. The bridge has no read or write API for
    track-lane automation (LOM doesn't expose it), so the agent can't audit or clean up these
    side-effect writes. Manual track-lane edits in the same range get overwritten on every
    refresh.

    Session clips only — Live's LOM rejects envelope creation on arrangement clips
    ("Not a session clip or parameter belongs to another track"). To get automation
    onto the timeline: author on a session clip, then add_session_clip_to_arrangement
    (first placement) or update_arrangement_clip_from_session (refresh an existing
    arrangement copy after editing the session source).
    """
    return _forward("add_clip_envelope_point", {
        "track_index": track_index,
        "clip_index": clip_index,
        "parameter_path": parameter_path,
        "time": time,
        "value": value,
    })

@mcp.tool()
def add_clip_envelope_ramp(
    ctx: Context, track_index: int, clip_index: int,
    parameter_path: str, start_time: float, end_time: float,
    start_value: float, end_value: float, steps: int = 64,
) -> str:
    """
    Write a smooth-feeling ramp on a session clip's automation envelope.

    Live's LOM only exposes flat-region writes (insert_step), not true breakpoints with linear
    interpolation. This tool approximates a smooth curve by writing N abutting flat steps with
    progressively interpolated values. Default steps=64 gives ~50ms granularity over a 4-beat
    ramp at 90 BPM — well below audible-stairstep threshold.

    Parameters:
    - start_time, end_time: clip-local beats. start_time inclusive, end_time exclusive.
    - start_value, end_value: parameter values at the ramp endpoints. Range-checked.
    - steps: number of flat steps to use for the approximation. Bigger = smoother but more
      LOM calls. 64 is a good default for ramps over 1-4 beats. Drop to 16 for short ramps.

    Session clips only (same arrangement-clip rejection as add_clip_envelope_point). Carries
    the same TRACK-LANE materialization side effect when placed into the arrangement.
    """
    return _forward("add_clip_envelope_ramp", {
        "track_index": track_index,
        "clip_index": clip_index,
        "parameter_path": parameter_path,
        "start_time": start_time,
        "end_time": end_time,
        "start_value": start_value,
        "end_value": end_value,
        "steps": steps,
    })

@mcp.tool()
def clear_clip_envelope(
    ctx: Context, track_index: int, clip_index: int,
    parameter_path: str, is_arrangement: bool = False,
) -> str:
    """
    Remove all envelope points for one parameter on a clip.

    Works on both session clips (default) and arrangement clips
    (set is_arrangement=True; clip_index is then the arrangement_clips index).
    """
    return _forward("clear_clip_envelope", {
        "track_index": track_index,
        "clip_index": clip_index,
        "parameter_path": parameter_path,
        "is_arrangement": is_arrangement,
    })

@mcp.tool()
def get_clip_envelope(
    ctx: Context, track_index: int, clip_index: int,
    parameter_path: str, is_arrangement: bool = False,
) -> str:
    """
    Inspect a clip's automation envelope for a parameter. Returns sampled values at
    integer-beat intervals — coarse, intended for sanity checks. Live's UI is the
    source of truth.

    Works on both session clips (default) and arrangement clips
    (set is_arrangement=True). For arrangement clips with no envelope present, returns
    exists=false (Live's LOM returns None rather than raising).
    """
    return _forward("get_clip_envelope", {
        "track_index": track_index,
        "clip_index": clip_index,
        "parameter_path": parameter_path,
        "is_arrangement": is_arrangement,
    })

@mcp.tool()
def update_arrangement_clip_from_session(
    ctx: Context, track_index: int, arr_clip_index: int, session_clip_index: int,
) -> str:
    """
    Refresh an existing arrangement clip from its session source.

    Live's session-to-arrangement model creates an independent copy: edits to the
    source session clip's notes/envelopes don't propagate to the placed arrangement
    copy. This tool deletes the arrangement copy and re-places the session source at
    the SAME position, so authoring an envelope on the session clip and calling this
    tool gets the updated envelope onto the timeline.

    Use this when you've edited a session clip and want the change to show up in an
    already-placed arrangement copy. For first-time placement, use
    add_session_clip_to_arrangement instead.

    Parameters:
    - arr_clip_index: index into the track's arrangement_clips list (re-list after
      mutations — indices shift if other arrangement clips are added/removed).
    - session_clip_index: clip slot index of the session source.
    """
    return _forward("update_arrangement_clip_from_session", {
        "track_index": track_index,
        "arr_clip_index": arr_clip_index,
        "session_clip_index": session_clip_index,
    })

# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()
