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
            "set_track_name":                  (True, lambda p: s._set_track_name(p.get("track_index", 0), p.get("name", ""))),
            "set_track_volume":                (True, lambda p: s._set_track_volume(p.get("track_index", 0), p.get("value"))),
            "set_track_pan":                   (True, lambda p: s._set_track_pan(p.get("track_index", 0), p.get("value"))),
            "set_track_mute":                  (True, lambda p: s._set_track_mute(p.get("track_index", 0), p.get("mute", False))),
            "set_track_solo":                  (True, lambda p: s._set_track_solo(p.get("track_index", 0), p.get("solo", False))),
            "set_track_send":                  (True, lambda p: s._set_track_send(p.get("track_index", 0), p.get("send_index", 0), p.get("value"))),
            "set_master_volume":               (True, lambda p: s._set_master_volume(p.get("value"))),
            "set_master_pan":                  (True, lambda p: s._set_master_pan(p.get("value"))),
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
            "jump_to_cue":                     (True, lambda p: s._jump_to_cue(p.get("cue_index", 0))),
            "jump_to_next_cue":                (True, lambda p: s._jump_to_next_cue()),
            "jump_to_prev_cue":                (True, lambda p: s._jump_to_prev_cue()),
            "save_session":                    (True, lambda p: s._save_session()),
            "save_session_as":                 (True, lambda p: s._save_session_as(p.get("path", ""))),
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
            "add_clip_envelope_point":         (True, lambda p: s._add_clip_envelope_point(p.get("track_index", 0), p.get("clip_index", 0), p.get("parameter_path", ""), p.get("time", 0.0), p.get("value", 0.0), p.get("is_arrangement", False))),
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

    def _get_clip_for_envelope(self, track_index, clip_index, is_arrangement):
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
        _, clip = self._get_clip_for_envelope(track_index, clip_index, is_arrangement)
        if not clip.is_midi_clip:
            raise Exception("Clip is not a MIDI clip")
        self._remove_all_notes(clip)
        return {"cleared": True}

    def _replace_clip_notes(self, track_index, clip_index, notes, is_arrangement):
        _, clip = self._get_clip_for_envelope(track_index, clip_index, is_arrangement)
        if not clip.is_midi_clip:
            raise Exception("Clip is not a MIDI clip")
        self._remove_all_notes(clip)
        specs = self._build_note_specs(notes)
        if specs:
            clip.add_new_notes(specs)
        return {"note_count": len(specs)}

    def _get_clip_notes(self, track_index, clip_index, is_arrangement):
        _, clip = self._get_clip_for_envelope(track_index, clip_index, is_arrangement)
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

    def _add_clip_envelope_point(self, track_index, clip_index, parameter_path, time, value, is_arrangement):
        # Live's clip.automation_envelope rejects arrangement clips for ANY param type
        # (confirmed 2026-04-25 with both mixer and device params). The is_arrangement
        # branch is wired but currently always errors — arrangement automation needs a
        # different LOM API which we haven't located yet.
        track, clip = self._get_clip_for_envelope(track_index, clip_index, is_arrangement)
        param = self._resolve_parameter(track, parameter_path)
        if not (param.min <= value <= param.max):
            raise ValueError("value {0} out of range [{1}, {2}] for {3}".format(value, param.min, param.max, param.name))
        try:
            env = clip.automation_envelope(param)
            if env is None:
                env = clip.create_automation_envelope(param)
        except AttributeError:
            raise Exception("Clip envelope API not available in this Live version")
        env.insert_step(time, 0.0, value)
        return {"parameter": param.name, "time": time, "value": value}

    def _clear_clip_envelope(self, track_index, clip_index, parameter_path, is_arrangement):
        track, clip = self._get_clip_for_envelope(track_index, clip_index, is_arrangement)
        param = self._resolve_parameter(track, parameter_path)
        try:
            clip.clear_envelope(param)
        except AttributeError:
            raise Exception("Clip.clear_envelope is not available in this Live version")
        return {"parameter": param.name, "cleared": True}

    def _get_clip_envelope(self, track_index, clip_index, parameter_path, is_arrangement):
        track, clip = self._get_clip_for_envelope(track_index, clip_index, is_arrangement)
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

    def _save_session(self):
        """Save the current Live set to its existing path. Fails for unsaved sets."""
        try:
            try:
                self._song.save_song()
            except AttributeError:
                raise Exception("Song.save_song is not available in this Live version")
            except RuntimeError as e:
                # Live raises RuntimeError for untitled sets ("set has no path yet").
                raise Exception("Cannot save: set has no path yet. Use save_session_as(path) instead. ({0})".format(e))
            return {"saved": True}
        except Exception as e:
            self.log_message("Error saving session: " + str(e))
            raise

    def _save_session_as(self, path):
        """Save the current Live set to a new path. path must be absolute and end in .als."""
        try:
            if not path:
                raise ValueError("path is required")
            song = self._song
            # Live's Python LOM doesn't expose a documented save-as on Song in all
            # versions; try a few names and surface a clear error if none exist.
            saver = getattr(song, "save_song_as", None) or getattr(song, "save_as", None)
            if saver is None:
                raise Exception("No save-as API on Song in this Live version (tried save_song_as, save_as)")
            saver(path)
            return {"saved": True, "path": path}
        except Exception as e:
            self.log_message("Error saving session as: " + str(e))
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
