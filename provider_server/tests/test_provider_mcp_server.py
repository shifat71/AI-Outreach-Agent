from __future__ import annotations

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_SERVERS = os.path.join(ROOT, "mcp_servers")
sys.path.insert(0, MCP_SERVERS)

from provider_mcp_server import TOOLS, handle_mcp_message


class ProviderMcpServerTests(unittest.TestCase):
    def test_exposes_required_tools(self):
        tool_names = {tool["name"] for tool in TOOLS}

        self.assertTrue({"provider_status", "discover_candidates", "send_email", "check_replies"} <= tool_names)

    def test_provider_status_does_not_return_secret_values(self):
        old = os.environ.get("SMTP_HOST")
        os.environ["SMTP_HOST"] = "secret.smtp.example"
        response = handle_mcp_message(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {"name": "provider_status", "arguments": {}},
            }
        )
        if old is None:
            os.environ.pop("SMTP_HOST", None)
        else:
            os.environ["SMTP_HOST"] = old

        status = response["result"]["structuredContent"]
        self.assertIs(status["smtp"]["SMTP_HOST"], True)
        self.assertIsInstance(status["imap"]["IMAP_HOST"], bool)


if __name__ == "__main__":
    unittest.main()
