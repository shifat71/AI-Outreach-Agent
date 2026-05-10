"""Agent-side client for the local provider MCP backend.

The agent process must not read provider credentials directly. Search, SMTP,
and IMAP access go through the provider MCP server over localhost HTTP.
"""
from __future__ import annotations

import json
import os
import uuid
import urllib.error
import urllib.request


DEFAULT_PROVIDER_MCP_URL = "http://127.0.0.1:8770/mcp"


class ProviderError(RuntimeError):
    """Raised when the provider MCP server is unavailable or returns an error."""


def provider_mcp_url() -> str:
    return os.environ.get("OUTREACH_PROVIDER_MCP_URL", DEFAULT_PROVIDER_MCP_URL)


def call_tool(name: str, arguments: dict | None = None) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        provider_mcp_url(),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except Exception as parse_exc:
            raise ProviderError(f"provider MCP server returned HTTP {exc.code}") from parse_exc
    except urllib.error.URLError as exc:
        raise ProviderError(
            f"provider MCP server is unavailable at {provider_mcp_url()}. "
            "Start it from openclaw_environment with: "
            "python3 ../provider_server/mcp_servers/provider_mcp_server.py --port 8770"
        ) from exc

    if data.get("error"):
        message = data["error"].get("message") or "provider MCP error"
        raise ProviderError(message)

    result = data.get("result") or {}
    if "structuredContent" in result:
        return result["structuredContent"]

    content = result.get("content") or []
    if content and content[0].get("type") == "text":
        return json.loads(content[0].get("text") or "{}")

    return result


def provider_status() -> dict:
    return call_tool("provider_status")


def discover_candidates(niche: str, location: str, count: int) -> dict:
    return call_tool("discover_candidates", {"niche": niche, "location": location, "count": count})


def send_email(
    to_email: str,
    subject: str,
    body: str,
    from_name: str | None = None,
    reply_to: str | None = None,
    signature: str | None = None,
) -> dict:
    return call_tool(
        "send_email",
        {
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "from_name": from_name,
            "reply_to": reply_to,
            "signature": signature,
        },
    )


def check_replies(sent: list[dict], limit: int = 200) -> dict:
    return call_tool("check_replies", {"sent": sent, "limit": limit})
