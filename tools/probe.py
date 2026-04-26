#!/usr/bin/env python3
"""Direct TCP probe for the AbletonMCP Remote Script.

Bypasses the MCP server (and its uvx build cache) by talking straight to
the Remote Script's socket on localhost:9877. Useful when iterating on
Remote Script handlers — restart Live to reload the script, then probe
without restarting the MCP client.

Usage:
    python3 tools/probe.py <command> [json-params]
    python3 tools/probe.py get_track_info '{"track_index": 0}'
    python3 tools/probe.py set_track_volume '{"track_index": 0, "value": 0.7}'
    python3 tools/probe.py get_session_info

Returns the parsed JSON response on stdout. Exit 1 on error status.
"""
import json
import socket
import sys

HOST = "localhost"
PORT = 9877
TIMEOUT = 10.0


def probe(command: str, params: dict | None = None) -> dict:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    sock.connect((HOST, PORT))
    try:
        payload = (json.dumps({"type": command, "params": params or {}}) + "\n").encode("utf-8")
        sock.sendall(payload)
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(8192)
            if not chunk:
                raise RuntimeError("Connection closed before full response")
            buf += chunk
        line, _, _ = buf.partition(b"\n")
        return json.loads(line.decode("utf-8"))
    finally:
        sock.close()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    command = argv[1]
    params = json.loads(argv[2]) if len(argv) > 2 else None
    response = probe(command, params)
    print(json.dumps(response, indent=2))
    return 0 if response.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
