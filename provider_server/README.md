# Provider MCP Server

This project is the credential-owning backend for the AI outreach workspace. It exposes MCP-style JSON-RPC over HTTP and provides provider-backed data/actions to the OpenClaw environment.

The provider server owns:

- Search provider access through `SERPAPI_API_KEY` or `BING_SEARCH_API_KEY`.
- SMTP sending through `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, and `SMTP_PASS`.
- IMAP reply polling through `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, and `IMAP_PASS`.

It must not own campaign state. The OpenClaw environment remains responsible for approval, compliance, duplicate prevention, suppression checks, and database writes.

Implementation details are documented in `docs/implementation-reference.md`.

## Run

Start from this folder:

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
python3 mcp_servers/provider_mcp_server.py --port 8770
```

Credentials are optional per capability. For example, discovery can work with only search credentials, while sending requires SMTP credentials.

## Endpoints

- `GET /health`: health and redacted provider configuration status.
- `GET /mcp`: tool list.
- `POST /mcp`: MCP-style JSON-RPC endpoint.

## Tools

- `provider_status`: returns boolean configured/not-configured status without revealing secret values.
- `discover_candidates`: searches approved providers for candidate business websites.
- `send_email`: sends one plaintext email through provider-owned SMTP credentials.
- `check_replies`: polls provider-owned IMAP credentials and returns replies matching sent campaign emails supplied by the OpenClaw environment.

For tool inputs, outputs, provider behavior, and tests, see `docs/implementation-reference.md`.

## Test

```bash
python3 -m py_compile mcp_servers/*.py tests/*.py
python3 -m unittest tests/test_provider_mcp_server.py
```
