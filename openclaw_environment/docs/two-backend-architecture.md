# Two-Backend Architecture

The project runs as two local backend processes:

1. Agent backend: owns campaign state, scraping, scoring, draft generation, approval, suppression, duplicate checks, summaries, dashboard API, and database writes.
2. Provider MCP backend: owns provider integrations and provider credentials for search APIs, SMTP sending, and IMAP reply polling.

The agent backend must not read provider credentials. It may read only non-secret runtime settings such as `OUTREACH_DB_PATH` and `OUTREACH_PROVIDER_MCP_URL`.

## Process Boundary

Run the provider MCP backend in an environment that contains provider credentials:

```bash
SERPAPI_API_KEY="..." \
BING_SEARCH_API_KEY="..." \
SMTP_HOST="smtp.example.com" \
SMTP_PORT="587" \
SMTP_USER="sender@example.com" \
SMTP_PASS="..." \
IMAP_HOST="imap.example.com" \
IMAP_PORT="993" \
IMAP_USER="sender@example.com" \
IMAP_PASS="..." \
python3 ../provider_server/mcp_servers/provider_mcp_server.py --port 8770
```

Run the agent backend separately in another terminal without provider credentials:

```bash
OUTREACH_PROVIDER_MCP_URL="http://127.0.0.1:8770/mcp" \
python3 scripts/agent_server.py --port 8765
```

Open the dashboard at `http://127.0.0.1:8765`.

## Provider MCP Tools

The provider server exposes MCP-style JSON-RPC over HTTP at `/mcp`.

- `provider_status`: returns boolean configured/not-configured status for search, SMTP, and IMAP credentials without revealing values.
- `discover_candidates`: searches approved providers for candidate business websites.
- `send_email`: sends one plaintext email through provider-owned SMTP credentials.
- `check_replies`: polls provider-owned IMAP credentials and returns replies matching sent campaign emails supplied by the agent.

The agent uses `scripts/provider_client.py` for these calls. Search, sending, and reply tracking CLIs route through that client.

## Credential Rule

Provider credentials belong only in the provider backend process environment. Do not place them in `USER.md`, `AGENTS.md`, `README.md`, shell history checked into the repo, or the agent backend environment.

The agent backend still enforces outreach safety before asking the provider to send:

- approved draft required
- compliance check required
- suppression check required
- duplicate sent-email check required
- daily sending limit required

The provider backend only performs provider actions and returns provider results. The agent remains responsible for campaign state.
