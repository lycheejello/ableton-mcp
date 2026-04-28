# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import Live
import socket
import json
import threading
import time
import traceback

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()

        # Build command registry (must come after _song is set, before server starts)
        self._commands = self._build_commands()

        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        
        # Stop the server
        if self.server:
            try:
                self.server.close()
            except:
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client. NDJSON framing:
        each request and response is a single JSON object terminated by \n."""
        self.log_message("Client handler started")
        client.settimeout(None)
        buffer = ''

        def send(obj):
            payload = (json.dumps(obj) + "\n").encode('utf-8')
            client.sendall(payload)

        try:
            while self.running:
                try:
                    data = client.recv(8192)
                    if not data:
                        self.log_message("Client disconnected")
                        break
                    buffer += data.decode('utf-8')

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if not line:
                            continue
                        try:
                            command = json.loads(line)
                        except ValueError as e:
                            self.log_message("Malformed JSON line: " + str(e))
                            send({"status": "error", "message": "Malformed JSON: " + str(e)})
                            continue

                        self.log_message("Received command: " + str(command.get("type", "unknown")))
                        response = self._process_command(command)
                        send(response)

                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    try:
                        send({"status": "error", "message": str(e)})
                    except Exception:
                        break
                    break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except:
                pass
            self.log_message("Client handler stopped")
    
    def _build_commands(self):
        """Map command name -> (on_main_thread, handler(params)).

        Adding a new tool: write the `_method` below, then add ONE entry here.
        Read-only handlers run on the caller thread; state-modifying handlers
        run on Live's main thread (Live's API is not thread-safe for writes).
        """
        s = self
        return {
            # Read-only
            "get_session_info":          (False, lambda p: s._get_session_info()),
            "get_transport_state":       (False, lambda p: s._get_transport_state()),
            "get_track_info":            (False, lambda p: s._get_track_info(p.get("track_index", 0))),
            "list_devices":              (False, lambda p: s._list_devices(p.get("track_index", 0))),
            "get_device_parameters":     (False, lambda p: s._get_device_parameters(p.get("track_index", 0), p.get("device_index", 0))),
            "get_track_sends":           (False, lambda p: s._get_track_sends(p.get("track_index", 0))),
            "get_cue_points":            (False, lambda p: s._get_cue_points()),
            "list_arrangement_clips":    (False, lambda p: s._list_arrangement_clips(p.get("track_index", 0))),
            "get_clip_envelope":         (False, lambda p: s._get_clip_envelope(p.get("track_index", 0), p.get("clip_index", 0), p.get("parameter_path", ""), p.get("is_arrangement", False))),
            "get_clip_notes":            (False, lambda p: s._get_clip_notes(p.get("track_index", 0), p.get("clip_index", 0), p.get("is_arrangement", False))),
            "get_browser_item":          (False, lambda p: s._get_browser_item(p.get("uri"), p.get("path"))),
            "get_browser_tree":          (False, lambda p: s.get_browser_tree(p.get("category_type", "all"))),
            "get_browser_items_at_path": (False, lambda p: s.get_browser_items_at_path(p.get("path", ""))),
            # State-modifying (main thread)
            "create_midi_track":               (True, lambda p: s._create_midi_track(p.get("index", -1))),
            "create_audio_track":              (True, lambda p: s._create_audio_track(p.get("index", -1))),
            "delete_track":                    (True, lambda p: s._delete_track(p.get("track_index", 0))),
            "set_track_arm":                   (True, lambda p: s._set_track_arm(p.get("track_index", 0), p.get("armed", False))),
            "set_song_record_mode":            (True, lambda p: s._set_song_record_mode(p.get("enabled", False))),
            "get_input_routing":               (False, lambda p: s._get_input_routing(p.get("track_index", 0))),
            "set_input_routing":               (True, lambda p: s._set_input_routing(p.get("track_index", 0), p.get("type_name"), p.get("channel_name"))),
            "set_track_name":                  (True, lambda p: s._set_track_name(p.get("track_index", 0), p.get("name", ""))),
            "set_track_volume":                (True, lambda p: s._set_track_volume(p.get("track_index", 0), p.get("value"))),
            "set_track_pan":                   (True, lambda p: s._set_track_pan(p.get("track_index", 0), p.get("value"))),
            "set_track_mute":                  (True, lambda p: s._set_track_mute(p.get("track_index", 0), p.get("mute", False))),
            "set_track_solo":                  (True, lambda p: s._set_track_solo(p.get("track_index", 0), p.get("solo", False))),
            "set_track_send":                  (True, lambda p: s._set_track_send(p.get("track_index", 0), p.get("send_index", 0), p.get("value"))),
            "set_master_volume":               (True, lambda p: s._set_master_volume(p.get("value"))),
            "set_master_pan":                  (True, lambda p: s._set_master_pan(p.get("value"))),
            "get_return_track_info":           (False, lambda p: s._get_return_track_info(p.get("return_index", 0))),
            "list_return_devices":             (False, lambda p: s._list_return_devices(p.get("return_index", 0))),
            "get_return_device_parameters":    (False, lambda p: s._get_return_device_parameters(p.get("return_index", 0), p.get("device_index", 0))),
            "set_return_device_parameter":     (True, lambda p: s._set_return_device_parameter(p.get("return_index", 0), p.get("device_index", 0), p.get("parameter_index", 0), p.get("value"))),
            "load_return_effect":              (True, lambda p: s._load_return_effect(p.get("return_index", 0), p.get("item_uri", ""))),
            "set_return_track_volume":         (True, lambda p: s._set_return_track_volume(p.get("return_index", 0), p.get("value"))),
            "set_return_track_pan":            (True, lambda p: s._set_return_track_pan(p.get("return_index", 0), p.get("value"))),
            "set_return_track_mute":           (True, lambda p: s._set_return_track_mute(p.get("return_index", 0), p.get("mute", False))),
            "set_return_track_solo":           (True, lambda p: s._set_return_track_solo(p.get("return_index", 0), p.get("solo", False))),
            "get_master_track_info":           (False, lambda p: s._get_master_track_info()),
            "list_master_devices":             (False, lambda p: s._list_master_devices()),
            "get_master_device_parameters":    (False, lambda p: s._get_master_device_parameters(p.get("device_index", 0))),
            "set_master_device_parameter":     (True, lambda p: s._set_master_device_parameter(p.get("device_index", 0), p.get("parameter_index", 0), p.get("value"))),
            "load_master_effect":              (True, lambda p: s._load_master_effect(p.get("item_uri", ""))),
            "delete_track_device":             (True, lambda p: s._delete_track_device(p.get("track_index", 0), p.get("device_index", 0))),
            "delete_return_device":            (True, lambda p: s._delete_return_device(p.get("return_index", 0), p.get("device_index", 0))),
            "delete_master_device":            (True, lambda p: s._delete_master_device(p.get("device_index", 0))),
            "create_clip":                     (True, lambda p: s._create_clip(p.get("track_index", 0), p.get("clip_index", 0), p.get("length", 4.0))),
            "add_notes_to_clip":               (True, lambda p: s._add_notes_to_clip(p.get("track_index", 0), p.get("clip_index", 0), p.get("notes", []))),
            "set_clip_name":                   (True, lambda p: s._set_clip_name(p.get("track_index", 0), p.get("clip_index", 0), p.get("name", ""))),
            "set_tempo":                       (True, lambda p: s._set_tempo(p.get("tempo", 120.0))),
            "fire_clip":                       (True, lambda p: s._fire_clip(p.get("track_index", 0), p.get("clip_index", 0))),
            "stop_clip":                       (True, lambda p: s._stop_clip(p.get("track_index", 0), p.get("clip_index", 0))),
            "start_playback":                  (True, lambda p: s._start_playback(p.get("from_beats"))),
            "stop_playback":                   (True, lambda p: s._stop_playback()),
            "set_transport_position":          (True, lambda p: s._set_transport_position(p.get("beats", 0.0))),
            "set_or_delete_cue":               (True, lambda p: s._set_or_delete_cue()),
            "set_cue_name":                    (True, lambda p: s._set_cue_name(p.get("cue_index", 0), p.get("name", ""))),
            "place_cue":                       (False, lambda p: s._place_cue(p.get("beat", 0.0), p.get("name"))),
            "jump_to_cue":                     (True, lambda p: s._jump_to_cue(p.get("cue_index", 0))),
            "jump_to_next_cue":                (True, lambda p: s._jump_to_next_cue()),
            "jump_to_prev_cue":                (True, lambda p: s._jump_to_prev_cue()),
            "undo":                            (True, lambda p: s._undo()),
            "redo":                            (True, lambda p: s._redo()),
            "begin_undo_step":                 (True, lambda p: s._begin_undo_step()),
            "end_undo_step":                   (True, lambda p: s._end_undo_step()),
            "delete_session_clip":             (True, lambda p: s._delete_session_clip(p.get("track_index", 0), p.get("clip_slot_index", 0))),
            "load_browser_item":               (True, lambda p: s._load_browser_item(p.get("track_index", 0), p.get("item_uri", ""))),
            "set_device_parameter":            (True, lambda p: s._set_device_parameter(p.get("track_index", 0), p.get("device_index", 0), p.get("parameter_index", 0), p.get("value"))),
            "add_session_clip_to_arrangement": (True, lambda p: s._add_session_clip_to_arrangement(p.get("track_index", 0), p.get("session_clip_index", 0), p.get("position", 0.0))),
            "create_arrangement_midi_clip":    (True, lambda p: s._create_arrangement_midi_clip(p.get("track_index", 0), p.get("start_time", 0.0), p.get("end_time", 4.0))),
            "set_arrangement_clip_position":   (True, lambda p: s._set_arrangement_clip_position(p.get("track_index", 0), p.get("arr_clip_index", 0), p.get("position", 0.0))),
            "set_arrangement_clip_loop":       (True, lambda p: s._set_arrangement_clip_loop(p.get("track_index", 0), p.get("arr_clip_index", 0), p.get("loop_start", 0.0), p.get("loop_end", 4.0), p.get("looping", True))),
            "set_arrangement_clip_markers":    (True, lambda p: s._set_arrangement_clip_markers(p.get("track_index", 0), p.get("arr_clip_index", 0), p.get("start_marker", 0.0), p.get("end_marker", 4.0))),
            "delete_arrangement_clip":         (True, lambda p: s._delete_arrangement_clip(p.get("track_index", 0), p.get("arr_clip_index", 0))),
            "set_arrangement_loop":            (True, lambda p: s._set_arrangement_loop(p.get("start_beats", 0.0), p.get("length_beats", 16.0))),
            "clear_clip_notes":                (True, lambda p: s._clear_clip_notes(p.get("track_index", 0), p.get("clip_index", 0), p.get("is_arrangement", False))),
            "replace_clip_notes":              (True, lambda p: s._replace_clip_notes(p.get("track_index", 0), p.get("clip_index", 0), p.get("notes", []), p.get("is_arrangement", False))),
            "add_clip_envelope_point":         (True, lambda p: s._add_clip_envelope_point(p.get("track_index", 0), p.get("clip_index", 0), p.get("parameter_path", ""), p.get("time", 0.0), p.get("value", 0.0))),
            "add_clip_envelope_ramp":          (True, lambda p: s._add_clip_envelope_ramp(p.get("track_index", 0), p.get("clip_index", 0), p.get("parameter_path", ""), p.get("start_time", 0.0), p.get("end_time", 1.0), p.get("start_value", 0.0), p.get("end_value", 1.0), p.get("steps", 64))),
            "update_arrangement_clip_from_session": (True, lambda p: s._update_arrangement_clip_from_session(p.get("track_index", 0), p.get("arr_clip_index", 0), p.get("session_clip_index", 0))),
            "clear_clip_envelope":             (True, lambda p: s._clear_clip_envelope(p.get("track_index", 0), p.get("clip_index", 0), p.get("parameter_path", ""), p.get("is_arrangement", False))),
        }

    def _process_command(self, command):
        """Process a command from the client and return a response."""
        command_type = command.get("type", "")
        params = command.get("params", {})

        entry = self._commands.get(command_type)
        if entry is None:
            return {"status": "error", "message": "Unknown command: " + command_type}
        on_main, handler = entry

        def run():
            try:
                result = handler(params)
                return {"status": "success", "result": result if result is not None else {}}
            except Exception as e:
                self.log_message("Error in handler '{0}': {1}".format(command_type, e))
                self.log_message(traceback.format_exc())
                return {"status": "error", "message": str(e)}

        if not on_main:
            return run()

        response_queue = queue.Queue()

        def main_thread_task():
            response_queue.put(run())

        try:
            self.schedule_message(0, main_thread_task)
        except AssertionError:
            # Already on the main thread — run directly.
            main_thread_task()

        try:
            return response_queue.get(timeout=10.0)
        except queue.Empty:
            return {"status": "error", "message": "Timeout waiting for operation to complete"}
    
    # Command implementations
    
    def _get_session_info(self):
        """Get information about the current session"""
        try:
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise

    def _get_transport_state(self):
        """Read playback state, arrangement-cursor position, and loop region."""
        try:
            song = self._song
            return {
                "is_playing": song.is_playing,
                "current_beat": song.current_song_time,
                "tempo": song.tempo,
                "loop_enabled": song.loop,
                "loop_start": song.loop_start,
                "loop_length": song.loop_length,
                "loop_end": song.loop_start + song.loop_length,
            }
        except Exception as e:
            self.log_message("Error getting transport state: " + str(e))
            raise

    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Get clip slots
            clip_slots = []
            for slot_index, slot in enumerate(track.clip_slots):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "mute": track.mute,
                "solo": track.solo,
                "arm": track.arm,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "sends": [
                    {"index": i, "value": send.value, "min": send.min, "max": send.max}
                    for i, send in enumerate(track.mixer_device.sends)
                ],
                "clip_slots": clip_slots,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise
    
    def _list_devices(self, track_index):
        """List devices on a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            devices = []
            for i, d in enumerate(track.devices):
                devices.append({
                    "index": i,
                    "name": d.name,
                    "class_name": d.class_name,
                    "type": self._get_device_type(d),
                })
            return {"track_index": track_index, "track_name": track.name, "devices": devices}
        except Exception as e:
            self.log_message("Error listing devices: " + str(e))
            raise

    def _get_device_parameters(self, track_index, device_index):
        """Get parameters of a device on a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            params = []
            for i, p in enumerate(device.parameters):
                value_items = None
                if p.is_quantized:
                    try:
                        value_items = list(p.value_items)
                    except Exception:
                        value_items = None
                params.append({
                    "index": i,
                    "name": p.name,
                    "value": p.value,
                    "min": p.min,
                    "max": p.max,
                    "is_quantized": p.is_quantized,
                    "value_items": value_items,
                })
            return {
                "track_index": track_index,
                "device_index": device_index,
                "device_name": device.name,
                "class_name": device.class_name,
                "parameters": params,
            }
        except Exception as e:
            self.log_message("Error getting device parameters: " + str(e))
            raise

    def _set_device_parameter(self, track_index, device_index, parameter_index, value):
        """Set a single device parameter by index. For quantized params, value is the integer index into value_items."""
        try:
            if value is None:
                raise ValueError("value is required")
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            if parameter_index < 0 or parameter_index >= len(device.parameters):
                raise IndexError("Parameter index out of range")
            p = device.parameters[parameter_index]
            if not (p.min <= value <= p.max):
                raise ValueError("value {0} out of range [{1}, {2}] for {3}".format(value, p.min, p.max, p.name))
            p.value = value
            return {
                "device_name": device.name,
                "parameter_index": parameter_index,
                "name": p.name,
                "value": p.value,
            }
        except Exception as e:
            self.log_message("Error setting device parameter: " + str(e))
            raise

    # Arrangement-view helpers ------------------------------------------------

    def _resolve_parameter(self, track, parameter_path):
        """Resolve a parameter_path to a Live DeviceParameter on a track.

          'volume'            -> track.mixer_device.volume
          'panning' / 'pan'   -> track.mixer_device.panning
          'send:N'            -> track.mixer_device.sends[N]
          'device:I:param:J'  -> track.devices[I].parameters[J]
        """
        if not parameter_path:
            raise ValueError("parameter_path is required")
        path = parameter_path.strip().lower()
        mixer = track.mixer_device
        if path == "volume":
            return mixer.volume
        if path in ("panning", "pan"):
            return mixer.panning
        if path.startswith("send:"):
            try:
                idx = int(path.split(":", 1)[1])
            except ValueError:
                raise ValueError("send path must be 'send:<int>'")
            sends = mixer.sends
            if idx < 0 or idx >= len(sends):
                raise IndexError("send index out of range")
            return sends[idx]
        if path.startswith("device:"):
            parts = path.split(":")
            if len(parts) != 4 or parts[2] != "param":
                raise ValueError("device path must be 'device:<int>:param:<int>'")
            try:
                di, pi = int(parts[1]), int(parts[3])
            except ValueError:
                raise ValueError("device path indices must be integers")
            devices = track.devices
            if di < 0 or di >= len(devices):
                raise IndexError("device index out of range (track has {0})".format(len(devices)))
            params_list = devices[di].parameters
            if pi < 0 or pi >= len(params_list):
                raise IndexError("parameter index out of range (device has {0})".format(len(params_list)))
            return params_list[pi]
        raise ValueError("Unsupported parameter_path '{0}' (supports volume, panning, send:N, device:I:param:J)".format(parameter_path))

    def _get_arrangement_clip(self, track, arr_clip_index):
        clips = list(track.arrangement_clips)
        if arr_clip_index < 0 or arr_clip_index >= len(clips):
            raise IndexError("Arrangement clip index out of range (track has {0})".format(len(clips)))
        return clips[arr_clip_index]

    def _get_clip(self, track_index, clip_index, is_arrangement):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if is_arrangement:
            return track, self._get_arrangement_clip(track, clip_index)
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip slot index out of range")
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            raise Exception("No clip in slot")
        return track, slot.clip

    def _list_arrangement_clips(self, track_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        clips = []
        for i, c in enumerate(track.arrangement_clips):
            clips.append({
                "index": i,
                "name": c.name,
                "position": c.start_time,
                "end": c.end_time,
                "length": c.length,
                "looping": c.looping,
                "loop_start": c.loop_start,
                "loop_end": c.loop_end,
                "is_audio_clip": c.is_audio_clip,
                "is_midi_clip": c.is_midi_clip,
            })
        return {"track_index": track_index, "track_name": track.name, "clips": clips}

    def _add_session_clip_to_arrangement(self, track_index, session_clip_index, position):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if session_clip_index < 0 or session_clip_index >= len(track.clip_slots):
            raise IndexError("Session clip slot index out of range")
        slot = track.clip_slots[session_clip_index]
        if not slot.has_clip:
            raise Exception("No clip in session slot {0}".format(session_clip_index))
        try:
            track.duplicate_clip_to_arrangement(slot.clip, position)
        except AttributeError:
            raise Exception("track.duplicate_clip_to_arrangement is not available in this Live version")
        return {"track_index": track_index, "position": position, "arrangement_clip_count": len(track.arrangement_clips)}

    def _update_arrangement_clip_from_session(self, track_index, arr_clip_index, session_clip_index):
        # Workaround for Live's session→arrangement-copy model: arrangement clips are independent
        # copies, so editing the source session clip's notes/envelopes doesn't propagate. We delete
        # the existing arrangement clip and re-place its session source at the same position.
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        old_clip = self._get_arrangement_clip(track, arr_clip_index)
        position = old_clip.start_time
        if session_clip_index < 0 or session_clip_index >= len(track.clip_slots):
            raise IndexError("Session clip slot index out of range")
        slot = track.clip_slots[session_clip_index]
        if not slot.has_clip:
            raise Exception("No clip in session slot {0}".format(session_clip_index))
        try:
            track.delete_clip(old_clip)
            track.duplicate_clip_to_arrangement(slot.clip, position)
        except AttributeError:
            raise Exception("track.delete_clip / duplicate_clip_to_arrangement not available in this Live version")
        return {"track_index": track_index, "position": position, "arrangement_clip_count": len(track.arrangement_clips)}

    def _create_arrangement_midi_clip(self, track_index, start_time, end_time):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        if end_time <= start_time:
            raise ValueError("end_time must be greater than start_time")
        track = self._song.tracks[track_index]
        if not track.has_midi_input:
            raise Exception("Track {0} is not a MIDI track".format(track_index))
        try:
            clip = track.create_midi_clip(start_time, end_time)
        except AttributeError:
            raise Exception("track.create_midi_clip is not available in this Live version")
        return {
            "track_index": track_index,
            "start_time": start_time,
            "end_time": end_time,
            "name": clip.name if clip else None,
        }

    def _set_arrangement_clip_position(self, track_index, arr_clip_index, position):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        clip = self._get_arrangement_clip(track, arr_clip_index)
        try:
            clip.position = position
        except AttributeError:
            raise Exception("Clip.position is read-only in this Live version")
        return {"position": clip.start_time, "length": clip.length}

    def _set_arrangement_clip_loop(self, track_index, arr_clip_index, loop_start, loop_end, looping):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        clip = self._get_arrangement_clip(track, arr_clip_index)
        if loop_end <= loop_start:
            raise ValueError("loop_end must be greater than loop_start")
        clip.loop_start = loop_start
        clip.loop_end = loop_end
        clip.looping = bool(looping)
        return {"loop_start": clip.loop_start, "loop_end": clip.loop_end, "looping": clip.looping}

    def _set_arrangement_clip_markers(self, track_index, arr_clip_index, start_marker, end_marker):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        clip = self._get_arrangement_clip(track, arr_clip_index)
        if end_marker <= start_marker:
            raise ValueError("end_marker must be greater than start_marker")
        clip.start_marker = start_marker
        clip.end_marker = end_marker
        return {"start_marker": clip.start_marker, "end_marker": clip.end_marker}

    def _delete_arrangement_clip(self, track_index, arr_clip_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        clip = self._get_arrangement_clip(track, arr_clip_index)
        try:
            track.delete_clip(clip)
        except AttributeError:
            raise Exception("track.delete_clip is not available in this Live version")
        return {"deleted_index": arr_clip_index, "remaining": len(track.arrangement_clips)}

    def _set_arrangement_loop(self, start_beats, length_beats):
        if length_beats <= 0:
            raise ValueError("length_beats must be > 0")
        self._song.loop_start = start_beats
        self._song.loop_length = length_beats
        return {"loop_start": self._song.loop_start, "loop_length": self._song.loop_length}

    def _build_note_specs(self, notes):
        """Convert input dicts to Live.Clip.MidiNoteSpecification tuple."""
        specs = []
        for note in notes:
            specs.append(Live.Clip.MidiNoteSpecification(
                pitch=note.get("pitch", 60),
                start_time=note.get("start_time", 0.0),
                duration=note.get("duration", 0.25),
                velocity=note.get("velocity", 100),
                mute=note.get("mute", False),
            ))
        return tuple(specs)

    def _remove_all_notes(self, clip):
        """Wipe every MIDI note in a clip via the Live 11+ extended API."""
        # remove_notes_extended(from_pitch, pitch_span, from_time, time_span)
        clip.remove_notes_extended(0, 128, 0.0, max(clip.length, 1.0))

    def _clear_clip_notes(self, track_index, clip_index, is_arrangement):
        _, clip = self._get_clip(track_index, clip_index, is_arrangement)
        if not clip.is_midi_clip:
            raise Exception("Clip is not a MIDI clip")
        self._remove_all_notes(clip)
        return {"cleared": True}

    def _replace_clip_notes(self, track_index, clip_index, notes, is_arrangement):
        _, clip = self._get_clip(track_index, clip_index, is_arrangement)
        if not clip.is_midi_clip:
            raise Exception("Clip is not a MIDI clip")
        self._remove_all_notes(clip)
        specs = self._build_note_specs(notes)
        if specs:
            clip.add_new_notes(specs)
        return {"note_count": len(specs)}

    def _get_clip_notes(self, track_index, clip_index, is_arrangement):
        _, clip = self._get_clip(track_index, clip_index, is_arrangement)
        if not clip.is_midi_clip:
            raise Exception("Clip is not a MIDI clip")
        # get_notes_extended(from_pitch, pitch_span, from_time, time_span)
        # returns objects with pitch, start_time, duration, velocity, mute, note_id.
        raw = clip.get_notes_extended(0, 128, 0.0, max(clip.length, 1.0))
        notes = [
            {
                "pitch": n.pitch,
                "start_time": n.start_time,
                "duration": n.duration,
                "velocity": n.velocity,
                "mute": bool(n.mute),
            }
            for n in raw
        ]
        return {"note_count": len(notes), "notes": notes}

    def _add_clip_envelope_point(self, track_index, clip_index, parameter_path, time, value):
        # Session-only: Live's Clip.create_automation_envelope rejects arrangement clips
        # ("Not a session clip or parameter belongs to another track"). To get an envelope
        # onto the timeline, author it on a session clip and use add_session_clip_to_arrangement
        # (or update_arrangement_clip_from_session to refresh an existing arrangement copy).
        track, clip = self._get_clip(track_index, clip_index, False)
        param = self._resolve_parameter(track, parameter_path)
        if not (param.min <= value <= param.max):
            raise ValueError("value {0} out of range [{1}, {2}] for {3}".format(value, param.min, param.max, param.name))
        if time < 0 or time >= clip.length:
            raise ValueError("time {0} out of clip range [0, {1})".format(time, clip.length))
        try:
            env = clip.automation_envelope(param)
            if env is None:
                env = clip.create_automation_envelope(param)
        except AttributeError:
            raise Exception("Clip envelope API not available in this Live version")
        # The LOM only exposes insert_step(start, length, value) for writes — no breakpoint API
        # and no linear interpolation between sparse events. Each call writes a flat region from
        # `time` to clip end; a later call at a higher `time` overrides the tail of the earlier
        # region. Net effect: cliff transitions between flat regions. For smooth ramps use
        # add_clip_envelope_ramp (writes many abutting small steps approximating a curve).
        env.insert_step(time, clip.length - time, value)
        return {"parameter": param.name, "time": time, "value": value}

    def _add_clip_envelope_ramp(self, track_index, clip_index, parameter_path, start_time, end_time, start_value, end_value, steps):
        track, clip = self._get_clip(track_index, clip_index, False)
        param = self._resolve_parameter(track, parameter_path)
        for v in (start_value, end_value):
            if not (param.min <= v <= param.max):
                raise ValueError("value {0} out of range [{1}, {2}] for {3}".format(v, param.min, param.max, param.name))
        if start_time < 0 or end_time > clip.length or start_time >= end_time:
            raise ValueError("ramp range [{0}, {1}) out of clip [0, {2})".format(start_time, end_time, clip.length))
        if steps < 2:
            raise ValueError("steps must be >= 2")
        try:
            env = clip.automation_envelope(param)
            if env is None:
                env = clip.create_automation_envelope(param)
        except AttributeError:
            raise Exception("Clip envelope API not available in this Live version")
        duration = end_time - start_time
        step_len = duration / steps
        for i in range(steps):
            t = start_time + i * step_len
            progress = i / float(steps - 1)
            v = start_value + (end_value - start_value) * progress
            env.insert_step(t, step_len, v)
        return {
            "parameter": param.name,
            "start_time": start_time,
            "end_time": end_time,
            "start_value": start_value,
            "end_value": end_value,
            "steps": steps,
            "step_length": step_len,
        }

    def _clear_clip_envelope(self, track_index, clip_index, parameter_path, is_arrangement):
        track, clip = self._get_clip(track_index, clip_index, is_arrangement)
        param = self._resolve_parameter(track, parameter_path)
        try:
            clip.clear_envelope(param)
        except AttributeError:
            raise Exception("Clip.clear_envelope is not available in this Live version")
        return {"parameter": param.name, "cleared": True}

    def _get_clip_envelope(self, track_index, clip_index, parameter_path, is_arrangement):
        track, clip = self._get_clip(track_index, clip_index, is_arrangement)
        param = self._resolve_parameter(track, parameter_path)
        env = None
        try:
            env = clip.automation_envelope(param)
        except AttributeError:
            raise Exception("Clip envelope API not available in this Live version")
        if env is None:
            return {"parameter": param.name, "exists": False, "points": []}
        # AutomationEnvelope doesn't expose a clean "list points" — we sample at integer beats.
        # Caller should treat this as a coarse view; precise inspection requires Live's UI.
        length = clip.length
        samples = []
        try:
            steps = max(1, int(length))
            for i in range(steps + 1):
                t = min(float(i), length)
                samples.append({"time": t, "value": env.value_at_time(t)})
        except AttributeError:
            pass
        return {"parameter": param.name, "exists": True, "samples": samples}

    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)

            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]

            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise

    def _create_audio_track(self, index):
        """Create a new audio track at the specified index (or end if index=-1)."""
        try:
            self._song.create_audio_track(index)
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            return {"index": new_track_index, "name": new_track.name}
        except Exception as e:
            self.log_message("Error creating audio track: " + str(e))
            raise

    def _delete_track(self, track_index):
        """Delete a regular track by index. song.tracks excludes master/return so the index is always safe."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            name = self._song.tracks[track_index].name
            self._song.delete_track(track_index)
            return {"deleted_index": track_index, "name": name, "remaining": len(self._song.tracks)}
        except Exception as e:
            self.log_message("Error deleting track: " + str(e))
            raise

    def _set_track_arm(self, track_index, armed):
        """Arm/disarm a track for recording. Errors on Main and Send tracks."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            track.arm = bool(armed)
            return {"track_index": track_index, "armed": track.arm}
        except Exception as e:
            self.log_message("Error setting track arm: " + str(e))
            raise

    def _set_song_record_mode(self, enabled):
        """Set Song.record_mode (the global arrangement-record flag)."""
        try:
            self._song.record_mode = bool(enabled)
            return {"record_mode": self._song.record_mode}
        except Exception as e:
            self.log_message("Error setting record mode: " + str(e))
            raise

    def _get_input_routing(self, track_index):
        """Read a track's current input routing + the discoverable lists of available types/channels."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            cur_type = getattr(track, "input_routing_type", None)
            cur_chan = getattr(track, "input_routing_channel", None)
            avail_types = getattr(track, "available_input_routing_types", None) or []
            avail_chans = getattr(track, "available_input_routing_channels", None) or []
            return {
                "track_index": track_index,
                "current_type": getattr(cur_type, "display_name", None),
                "current_channel": getattr(cur_chan, "display_name", None),
                "available_types": [getattr(t, "display_name", None) for t in avail_types],
                "available_channels": [getattr(c, "display_name", None) for c in avail_chans],
            }
        except Exception as e:
            self.log_message("Error getting input routing: " + str(e))
            raise

    def _set_input_routing(self, track_index, type_name, channel_name):
        """Set a track's input routing by display_name. Pass None to leave a side untouched."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if type_name is not None:
                avail_types = list(track.available_input_routing_types)
                match = None
                for t in avail_types:
                    if getattr(t, "display_name", None) == type_name:
                        match = t
                        break
                if match is None:
                    names = [getattr(t, "display_name", None) for t in avail_types]
                    raise ValueError("input routing type '{0}' not in available {1}".format(type_name, names))
                track.input_routing_type = match
            if channel_name is not None:
                avail_chans = list(track.available_input_routing_channels)
                match = None
                for c in avail_chans:
                    if getattr(c, "display_name", None) == channel_name:
                        match = c
                        break
                if match is None:
                    names = [getattr(c, "display_name", None) for c in avail_chans]
                    raise ValueError("input routing channel '{0}' not in available {1}".format(channel_name, names))
                track.input_routing_channel = match
            return {
                "track_index": track_index,
                "current_type": getattr(track.input_routing_type, "display_name", None),
                "current_channel": getattr(track.input_routing_channel, "display_name", None),
            }
        except Exception as e:
            self.log_message("Error setting input routing: " + str(e))
            raise

    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            # Set the name
            track = self._song.tracks[track_index]
            track.name = name

            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise

    def _get_track_or_raise(self, track_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        return self._song.tracks[track_index]

    def _set_mixer_param(self, mixer_param, value):
        """Assign a Live mixer DeviceParameter, validating range. Returns the readback."""
        if value is None:
            raise ValueError("value is required")
        v = float(value)
        if not (mixer_param.min <= v <= mixer_param.max):
            raise ValueError("value {0} out of range [{1}, {2}]".format(v, mixer_param.min, mixer_param.max))
        mixer_param.value = v
        return mixer_param.value

    def _set_track_volume(self, track_index, value):
        """Set track mixer volume (Live native float, 0.0–1.0; 0.85 ≈ 0dB)."""
        try:
            track = self._get_track_or_raise(track_index)
            new_value = self._set_mixer_param(track.mixer_device.volume, value)
            return {"track_index": track_index, "volume": new_value}
        except Exception as e:
            self.log_message("Error setting track volume: " + str(e))
            raise

    def _set_track_pan(self, track_index, value):
        """Set track mixer panning (Live native float, -1.0–1.0)."""
        try:
            track = self._get_track_or_raise(track_index)
            new_value = self._set_mixer_param(track.mixer_device.panning, value)
            return {"track_index": track_index, "panning": new_value}
        except Exception as e:
            self.log_message("Error setting track pan: " + str(e))
            raise

    def _get_track_sends(self, track_index):
        """List a track's sends. Each send routes to the return track at the same index in song.return_tracks.

        Live native float (0.0–1.0). Use return-track names to map "more reverb" → send index.
        """
        try:
            track = self._get_track_or_raise(track_index)
            sends = track.mixer_device.sends
            returns = list(self._song.return_tracks)
            send_list = []
            for i, send in enumerate(sends):
                return_name = returns[i].name if i < len(returns) else None
                send_list.append({
                    "index": i,
                    "return_track_name": return_name,
                    "value": send.value,
                    "min": send.min,
                    "max": send.max,
                })
            return {
                "track_index": track_index,
                "track_name": track.name,
                "sends": send_list,
            }
        except Exception as e:
            self.log_message("Error getting track sends: " + str(e))
            raise

    def _set_track_send(self, track_index, send_index, value):
        """Set a track's send level (Live native float, 0.0–1.0). send_index addresses song.return_tracks[send_index]."""
        try:
            track = self._get_track_or_raise(track_index)
            sends = track.mixer_device.sends
            if send_index < 0 or send_index >= len(sends):
                raise IndexError("Send index out of range")
            new_value = self._set_mixer_param(sends[send_index], value)
            return {"track_index": track_index, "send_index": send_index, "value": new_value}
        except Exception as e:
            self.log_message("Error setting track send: " + str(e))
            raise

    def _get_cue_points(self):
        """List arrangement cue points (locators). Each cue's `time` is in beats; pair with set_transport_position or jump_to_cue to seek."""
        try:
            cues = [
                {"index": i, "name": cue.name, "time": cue.time}
                for i, cue in enumerate(self._song.cue_points)
            ]
            return {"cue_points": cues}
        except Exception as e:
            self.log_message("Error getting cue points: " + str(e))
            raise

    def _set_or_delete_cue(self):
        """Toggle a cue point at the current arrangement position (Live's native set/delete-cue behavior)."""
        try:
            self._song.set_or_delete_cue()
            return {"cue_count": len(self._song.cue_points), "at_beat": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error toggling cue: " + str(e))
            raise

    def _place_cue(self, beat, name=None):
        """Place a cue at `beat` (idempotent; reuses an existing cue at that beat). Optionally rename.
        Decoupled from transport: stops playback first to avoid races, restores cursor + play state on exit.

        Implementation: this handler runs off-main (in the socket thread). It hops short main-thread
        steps via schedule_message, with real wall-clock sleeps in between so Live's main thread has
        time to actually commit the cursor assignment between scheduled callbacks. schedule_message
        ticks alone don't span enough frames — the cursor stays stale within a single message-pump
        cycle. CuePoint.time is read-only so we can't post-correct a misplaced cue.
        """
        target = float(beat)
        state = {}
        errors = []

        def run_on_main(fn, wait=2.0):
            ev = threading.Event()
            box = {}
            def wrapper():
                try:
                    box["v"] = fn()
                except Exception as e:
                    box["err"] = str(e)
                finally:
                    ev.set()
            try:
                self.schedule_message(0, wrapper)
            except AssertionError:
                wrapper()
            if not ev.wait(timeout=wait):
                raise RuntimeError("place_cue: main-thread step timed out")
            if "err" in box:
                raise RuntimeError(box["err"])
            return box.get("v")

        # Step 1: snapshot transport, fast-path idempotency, then assign cursor.
        def s1():
            state["was_playing"] = self._song.is_playing
            state["prior_time"] = self._song.current_song_time
            self._song.stop_playing()
            for i, cue in enumerate(self._song.cue_points):
                if abs(cue.time - target) < 1e-6:
                    if name:
                        cue.name = name
                    state["fast_path"] = {
                        "cue_index": i, "name": cue.name, "time": cue.time, "created": False,
                    }
                    if state["was_playing"]:
                        self._song.start_playing()
                    return
            state["existing_times"] = sorted(c.time for c in self._song.cue_points)
            self._song.current_song_time = target

        run_on_main(s1)
        if "fast_path" in state:
            return state["fast_path"]

        # Wall-clock yield so Live's main thread can commit the cursor assignment.
        time.sleep(0.1)

        # Step 2: toggle. Cursor should now be at target.
        def s2():
            self._song.set_or_delete_cue()
        run_on_main(s2)

        time.sleep(0.05)

        # Step 3: read cue list, identify new cue, name it, restore transport.
        def s3():
            new_times = sorted(c.time for c in self._song.cue_points)
            if len(new_times) < len(state["existing_times"]):
                # Toggle deleted a cue at the cursor — re-toggle to restore, then fail cleanly.
                self._song.set_or_delete_cue()
                self._song.current_song_time = state["prior_time"]
                if state["was_playing"]:
                    self._song.start_playing()
                raise RuntimeError("place_cue could not toggle on a free position; aborted to preserve existing cues")
            added = [t for t in new_times if t not in set(state["existing_times"])]
            if not added:
                raise RuntimeError("place_cue: toggle did not produce a new cue")
            new_time = added[0]
            cue_index = None
            cue_obj = None
            for i, cue in enumerate(self._song.cue_points):
                if abs(cue.time - new_time) < 1e-6:
                    cue_index = i
                    cue_obj = cue
                    break
            if cue_obj is None:
                raise RuntimeError("place_cue: lost track of newly created cue")
            if name:
                cue_obj.name = name
            result = {
                "cue_index": cue_index,
                "name": cue_obj.name,
                "time": cue_obj.time,
                "created": True,
            }
            self._song.current_song_time = state["prior_time"]
            if state["was_playing"]:
                self._song.start_playing()
            return result

        return run_on_main(s3)

    def _set_cue_name(self, cue_index, name):
        """Rename the cue at the given index (cue_points are positional and shift if cues are added/removed)."""
        try:
            cues = self._song.cue_points
            if cue_index < 0 or cue_index >= len(cues):
                raise IndexError("Cue index out of range")
            cues[cue_index].name = name
            return {"cue_index": cue_index, "name": cues[cue_index].name, "time": cues[cue_index].time}
        except Exception as e:
            self.log_message("Error setting cue name: " + str(e))
            raise

    def _jump_to_cue(self, cue_index):
        """Jump the arrangement cursor to the named cue at the given index."""
        try:
            cues = self._song.cue_points
            if cue_index < 0 or cue_index >= len(cues):
                raise IndexError("Cue index out of range")
            cue = cues[cue_index]
            cue.jump()
            return {"cue_index": cue_index, "name": cue.name, "time": cue.time}
        except Exception as e:
            self.log_message("Error jumping to cue: " + str(e))
            raise

    def _jump_to_next_cue(self):
        """Jump to the next cue from the current position (no-op if none)."""
        try:
            if not self._song.can_jump_to_next_cue:
                return {"jumped": False, "current_beat": self._song.current_song_time}
            self._song.jump_to_next_cue()
            return {"jumped": True, "current_beat": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error jumping to next cue: " + str(e))
            raise

    def _jump_to_prev_cue(self):
        """Jump to the previous cue from the current position (no-op if none)."""
        try:
            if not self._song.can_jump_to_prev_cue:
                return {"jumped": False, "current_beat": self._song.current_song_time}
            self._song.jump_to_prev_cue()
            return {"jumped": True, "current_beat": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error jumping to prev cue: " + str(e))
            raise

    def _undo(self):
        """Undo the last user-visible step in Live's undo history (no-op if nothing to undo)."""
        try:
            if not self._song.can_undo:
                return {"undone": False, "can_undo": False, "can_redo": self._song.can_redo}
            self._song.undo()
            return {"undone": True, "can_undo": self._song.can_undo, "can_redo": self._song.can_redo}
        except Exception as e:
            self.log_message("Error in undo: " + str(e))
            raise

    def _redo(self):
        """Redo the next step in Live's undo history (no-op if nothing to redo)."""
        try:
            if not self._song.can_redo:
                return {"redone": False, "can_undo": self._song.can_undo, "can_redo": False}
            self._song.redo()
            return {"redone": True, "can_undo": self._song.can_undo, "can_redo": self._song.can_redo}
        except Exception as e:
            self.log_message("Error in redo: " + str(e))
            raise

    def _begin_undo_step(self):
        """Open an undo group; subsequent edits collapse into one user-visible undo entry until end_undo_step()."""
        try:
            self._song.begin_undo_step()
            return {"ok": True}
        except Exception as e:
            self.log_message("Error in begin_undo_step: " + str(e))
            raise

    def _end_undo_step(self):
        """Close the undo group opened by begin_undo_step()."""
        try:
            self._song.end_undo_step()
            return {"ok": True, "can_undo": self._song.can_undo, "can_redo": self._song.can_redo}
        except Exception as e:
            self.log_message("Error in end_undo_step: " + str(e))
            raise

    def _set_track_mute(self, track_index, mute):
        """Set track mute flag."""
        try:
            track = self._get_track_or_raise(track_index)
            track.mute = bool(mute)
            return {"track_index": track_index, "mute": track.mute}
        except Exception as e:
            self.log_message("Error setting track mute: " + str(e))
            raise

    def _set_track_solo(self, track_index, solo):
        """Set track solo flag."""
        try:
            track = self._get_track_or_raise(track_index)
            track.solo = bool(solo)
            return {"track_index": track_index, "solo": track.solo}
        except Exception as e:
            self.log_message("Error setting track solo: " + str(e))
            raise

    def _set_master_volume(self, value):
        """Set master-track volume (Live native float, 0.0–1.0)."""
        try:
            new_value = self._set_mixer_param(self._song.master_track.mixer_device.volume, value)
            return {"volume": new_value}
        except Exception as e:
            self.log_message("Error setting master volume: " + str(e))
            raise

    def _set_master_pan(self, value):
        """Set master-track panning (Live native float, -1.0–1.0)."""
        try:
            new_value = self._set_mixer_param(self._song.master_track.mixer_device.panning, value)
            return {"panning": new_value}
        except Exception as e:
            self.log_message("Error setting master pan: " + str(e))
            raise

    # Return-track surface ----------------------------------------------------
    # song.return_tracks is parallel to song.tracks but distinct — track-addressed
    # tools (set_track_volume, list_devices, load_browser_item, ...) reject these
    # indices, so returns get their own variants here.

    def _get_return_track_or_raise(self, return_index):
        if return_index < 0 or return_index >= len(self._song.return_tracks):
            raise IndexError("Return-track index out of range")
        return self._song.return_tracks[return_index]

    def _get_return_track_info(self, return_index):
        """Inspect a return track: mixer state + device chain. Mirrors get_track_info but for song.return_tracks[return_index]."""
        try:
            track = self._get_return_track_or_raise(return_index)
            devices = []
            for i, d in enumerate(track.devices):
                devices.append({
                    "index": i,
                    "name": d.name,
                    "class_name": d.class_name,
                    "type": self._get_device_type(d),
                })
            return {
                "return_index": return_index,
                "name": track.name,
                "mute": track.mute,
                "solo": track.solo,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "devices": devices,
            }
        except Exception as e:
            self.log_message("Error getting return-track info: " + str(e))
            raise

    def _list_return_devices(self, return_index):
        try:
            track = self._get_return_track_or_raise(return_index)
            devices = []
            for i, d in enumerate(track.devices):
                devices.append({
                    "index": i,
                    "name": d.name,
                    "class_name": d.class_name,
                    "type": self._get_device_type(d),
                })
            return {"return_index": return_index, "track_name": track.name, "devices": devices}
        except Exception as e:
            self.log_message("Error listing return devices: " + str(e))
            raise

    def _get_return_device_parameters(self, return_index, device_index):
        try:
            track = self._get_return_track_or_raise(return_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            params = []
            for i, p in enumerate(device.parameters):
                value_items = None
                if p.is_quantized:
                    try:
                        value_items = list(p.value_items)
                    except Exception:
                        value_items = None
                params.append({
                    "index": i,
                    "name": p.name,
                    "value": p.value,
                    "min": p.min,
                    "max": p.max,
                    "is_quantized": p.is_quantized,
                    "value_items": value_items,
                })
            return {
                "return_index": return_index,
                "device_index": device_index,
                "device_name": device.name,
                "class_name": device.class_name,
                "parameters": params,
            }
        except Exception as e:
            self.log_message("Error getting return device parameters: " + str(e))
            raise

    def _set_return_device_parameter(self, return_index, device_index, parameter_index, value):
        try:
            if value is None:
                raise ValueError("value is required")
            track = self._get_return_track_or_raise(return_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            if parameter_index < 0 or parameter_index >= len(device.parameters):
                raise IndexError("Parameter index out of range")
            p = device.parameters[parameter_index]
            if not (p.min <= value <= p.max):
                raise ValueError("value {0} out of range [{1}, {2}] for {3}".format(value, p.min, p.max, p.name))
            p.value = value
            return {
                "device_name": device.name,
                "parameter_index": parameter_index,
                "name": p.name,
                "value": p.value,
            }
        except Exception as e:
            self.log_message("Error setting return device parameter: " + str(e))
            raise

    def _load_return_effect(self, return_index, item_uri):
        """Load a browser item (audio effect) onto a return track by URI."""
        try:
            track = self._get_return_track_or_raise(return_index)
            app = self.application()
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            self._song.view.selected_track = track
            app.browser.load_item(item)
            return {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri,
            }
        except Exception as e:
            self.log_message("Error loading return effect: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _set_return_track_volume(self, return_index, value):
        try:
            track = self._get_return_track_or_raise(return_index)
            new_value = self._set_mixer_param(track.mixer_device.volume, value)
            return {"return_index": return_index, "volume": new_value}
        except Exception as e:
            self.log_message("Error setting return-track volume: " + str(e))
            raise

    def _set_return_track_pan(self, return_index, value):
        try:
            track = self._get_return_track_or_raise(return_index)
            new_value = self._set_mixer_param(track.mixer_device.panning, value)
            return {"return_index": return_index, "panning": new_value}
        except Exception as e:
            self.log_message("Error setting return-track pan: " + str(e))
            raise

    def _set_return_track_mute(self, return_index, mute):
        try:
            track = self._get_return_track_or_raise(return_index)
            track.mute = bool(mute)
            return {"return_index": return_index, "mute": track.mute}
        except Exception as e:
            self.log_message("Error setting return-track mute: " + str(e))
            raise

    def _set_return_track_solo(self, return_index, solo):
        try:
            track = self._get_return_track_or_raise(return_index)
            track.solo = bool(solo)
            return {"return_index": return_index, "solo": track.solo}
        except Exception as e:
            self.log_message("Error setting return-track solo: " + str(e))
            raise

    # Master-track device surface --------------------------------------------
    # song.master_track is a single track outside song.tracks. Only its mixer
    # was reachable (set_master_volume/pan). These add the device chain.

    def _get_master_track_info(self):
        try:
            track = self._song.master_track
            devices = []
            for i, d in enumerate(track.devices):
                devices.append({
                    "index": i,
                    "name": d.name,
                    "class_name": d.class_name,
                    "type": self._get_device_type(d),
                })
            return {
                "name": track.name,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "devices": devices,
            }
        except Exception as e:
            self.log_message("Error getting master-track info: " + str(e))
            raise

    def _list_master_devices(self):
        try:
            track = self._song.master_track
            devices = []
            for i, d in enumerate(track.devices):
                devices.append({
                    "index": i,
                    "name": d.name,
                    "class_name": d.class_name,
                    "type": self._get_device_type(d),
                })
            return {"track_name": track.name, "devices": devices}
        except Exception as e:
            self.log_message("Error listing master devices: " + str(e))
            raise

    def _get_master_device_parameters(self, device_index):
        try:
            track = self._song.master_track
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            params = []
            for i, p in enumerate(device.parameters):
                value_items = None
                if p.is_quantized:
                    try:
                        value_items = list(p.value_items)
                    except Exception:
                        value_items = None
                params.append({
                    "index": i,
                    "name": p.name,
                    "value": p.value,
                    "min": p.min,
                    "max": p.max,
                    "is_quantized": p.is_quantized,
                    "value_items": value_items,
                })
            return {
                "device_index": device_index,
                "device_name": device.name,
                "class_name": device.class_name,
                "parameters": params,
            }
        except Exception as e:
            self.log_message("Error getting master device parameters: " + str(e))
            raise

    def _set_master_device_parameter(self, device_index, parameter_index, value):
        try:
            if value is None:
                raise ValueError("value is required")
            track = self._song.master_track
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            if parameter_index < 0 or parameter_index >= len(device.parameters):
                raise IndexError("Parameter index out of range")
            p = device.parameters[parameter_index]
            if not (p.min <= value <= p.max):
                raise ValueError("value {0} out of range [{1}, {2}] for {3}".format(value, p.min, p.max, p.name))
            p.value = value
            return {
                "device_name": device.name,
                "parameter_index": parameter_index,
                "name": p.name,
                "value": p.value,
            }
        except Exception as e:
            self.log_message("Error setting master device parameter: " + str(e))
            raise

    def _delete_track_device(self, track_index, device_index):
        """Delete a device from a regular track. Subsequent device indices shift down — re-list before deleting more."""
        try:
            track = self._get_track_or_raise(track_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            name = track.devices[device_index].name
            track.delete_device(device_index)
            return {"track_index": track_index, "deleted_index": device_index, "name": name, "remaining": len(track.devices)}
        except Exception as e:
            self.log_message("Error deleting track device: " + str(e))
            raise

    def _delete_return_device(self, return_index, device_index):
        """Delete a device from a return track. Subsequent device indices shift down."""
        try:
            track = self._get_return_track_or_raise(return_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            name = track.devices[device_index].name
            track.delete_device(device_index)
            return {"return_index": return_index, "deleted_index": device_index, "name": name, "remaining": len(track.devices)}
        except Exception as e:
            self.log_message("Error deleting return device: " + str(e))
            raise

    def _delete_master_device(self, device_index):
        """Delete a device from the master track. Subsequent device indices shift down."""
        try:
            track = self._song.master_track
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            name = track.devices[device_index].name
            track.delete_device(device_index)
            return {"deleted_index": device_index, "name": name, "remaining": len(track.devices)}
        except Exception as e:
            self.log_message("Error deleting master device: " + str(e))
            raise

    def _load_master_effect(self, item_uri):
        """Load a browser item (audio effect) onto the master track by URI."""
        try:
            track = self._song.master_track
            app = self.application()
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            self._song.view.selected_track = track
            app.browser.load_item(item)
            return {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri,
            }
        except Exception as e:
            self.log_message("Error loading master effect: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    def _add_notes_to_clip(self, track_index, clip_index, notes):
        """Append MIDI notes to a clip using the Live 11+ extended API."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            specs = self._build_note_specs(notes)
            if specs:
                clip.add_new_notes(specs)
            return {"note_count": len(specs)}
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise
    
    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    def _start_playback(self, from_beats=None):
        """Start playing. If from_beats is given, scrub the arrangement cursor first."""
        try:
            if from_beats is not None:
                if from_beats < 0:
                    raise ValueError("from_beats must be >= 0")
                self._song.current_song_time = float(from_beats)
            self._song.start_playing()
            return {"playing": self._song.is_playing, "song_time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise

    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()

            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise

    def _set_transport_position(self, beats):
        """Move the arrangement cursor to a given beat position."""
        try:
            if beats < 0:
                raise ValueError("beats must be >= 0")
            self._song.current_song_time = float(beats)
            return {"song_time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error setting transport position: " + str(e))
            raise

    def _delete_session_clip(self, track_index, clip_slot_index):
        """Delete the clip in a session clip slot, leaving the slot empty."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_slot_index < 0 or clip_slot_index >= len(track.clip_slots):
                raise IndexError("Clip slot index out of range")
            slot = track.clip_slots[clip_slot_index]
            if not slot.has_clip:
                return {"deleted": False, "reason": "slot was already empty"}
            slot.delete_clip()
            return {"deleted": True, "track_index": track_index, "clip_slot_index": clip_slot_index}
        except Exception as e:
            self.log_message("Error deleting session clip: " + str(e))
            raise
    
    def _get_browser_item(self, uri, path):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = path.split("/")
                
                # Determine the root based on the first part
                current_item = None
                if path_parts[0].lower() == "nstruments":
                    current_item = app.browser.instruments
                elif path_parts[0].lower() == "sounds":
                    current_item = app.browser.sounds
                elif path_parts[0].lower() == "drums":
                    current_item = app.browser.drums
                elif path_parts[0].lower() == "audio_effects":
                    current_item = app.browser.audio_effects
                elif path_parts[0].lower() == "midi_effects":
                    current_item = app.browser.midi_effects
                else:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    def _load_browser_item(self, track_index, item_uri):
        """Load a browser item onto a track by its URI"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            
            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            
            # Select the track
            self._song.view.selected_track = track
            
            # Load the item
            app.browser.load_item(item)
            
            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories
                categories = [
                    browser_or_item.instruments,
                    browser_or_item.sounds,
                    browser_or_item.drums,
                    browser_or_item.audio_effects,
                    browser_or_item.midi_effects
                ]
                
                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item
                
                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Helper methods
    
    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except:
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0].lower()
            current_item = None
            
            # Check standard categories first
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                # Try to find the category in other browser attributes
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                
                if not found:
                    # If we still haven't found the category, return available categories
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "items": []
                    }
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
