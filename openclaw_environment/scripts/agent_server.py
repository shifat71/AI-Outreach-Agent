"""Agent backend entry point.

This wraps the dashboard/API implementation under an explicit agent-server
name. Provider credentials belong in the separate provider MCP server process.
"""
from __future__ import annotations

from api_server import main


if __name__ == "__main__":
    main()
