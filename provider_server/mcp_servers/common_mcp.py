"""Minimal stdio MCP helpers for local outreach tool servers."""
from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable


def read_message() -> dict | None:
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.decode("utf-8").strip()
        if not line:
            break
        key, value = line.split(":", 1)
        headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def write_message(payload: dict) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def tool_schema(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


def run_server(server_name: str, tools: list[dict], handlers: dict[str, Callable[[dict], dict]]) -> None:
    while True:
        message = read_message()
        if message is None:
            break

        request_id = message.get("id")
        method = message.get("method")
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": server_name, "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                }
            elif method == "tools/list":
                result = {"tools": tools}
            elif method == "tools/call":
                params = message.get("params") or {}
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if name not in handlers:
                    raise ValueError(f"unknown tool: {name}")
                output = handlers[name](arguments)
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(output, indent=2, sort_keys=True),
                        }
                    ]
                }
            elif method == "notifications/initialized":
                continue
            else:
                raise ValueError(f"unsupported method: {method}")
            if request_id is not None:
                write_message({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as exc:
            if request_id is not None:
                write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": str(exc),
                            "data": traceback.format_exc(),
                        },
                    }
                )
