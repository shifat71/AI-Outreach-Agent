# Runtime Provider Configuration

Do not store credentials, API keys, app passwords, or tokens in markdown files.

The outreach agent keeps `USER.md` limited to non-secret profile and campaign preferences. Provider-backed operations read secrets only from the environment used to launch the sibling provider server at `../provider_server/mcp_servers/provider_mcp_server.py`.

## Environment Variables

Search providers:
- `SERPAPI_API_KEY`
- `BING_SEARCH_API_KEY`

SMTP sending:
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`

IMAP reply polling:
- `IMAP_HOST`
- `IMAP_PORT`
- `IMAP_USER`
- `IMAP_PASS`

## Local Provider MCP Server

Start one provider backend with the credentials above:

```bash
python3 ../provider_server/mcp_servers/provider_mcp_server.py --port 8770
```

Start the agent backend separately in another terminal without those credentials:

```bash
OUTREACH_PROVIDER_MCP_URL="http://127.0.0.1:8770/mcp" \
python3 scripts/agent_server.py --port 8765
```

The provider server exposes status and tool calls without printing or returning secret values.
