# Provider Server Implementation Reference

This document describes what is implemented in `provider_server/`. This project owns provider integrations and provider credentials. It does not own campaign state or outreach safety decisions.

## Runtime Shape

- `mcp_servers/provider_mcp_server.py`: standalone HTTP MCP backend.
- `mcp_servers/common_mcp.py`: minimal stdio MCP helpers retained as shared MCP utility code.
- `tests/test_provider_mcp_server.py`: provider tool and redacted-status tests.

Start the server from `provider_server/`:

```bash
python3 mcp_servers/provider_mcp_server.py --port 8770
```

The server listens on `127.0.0.1` by default and exposes:

- `GET /health`
- `GET /mcp`
- `POST /mcp`

## Credential Ownership

Provider credentials are read only by `mcp_servers/provider_mcp_server.py`.

Supported environment variables:

- Search: `SERPAPI_API_KEY`, `BING_SEARCH_API_KEY`
- SMTP: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`
- IMAP: `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASS`

The provider status output returns booleans only. It must never return secret values.

## MCP HTTP Protocol

`POST /mcp` accepts JSON-RPC-style messages:

- `initialize`
- `notifications/initialized`
- `tools/list`
- `tools/call`

Tool results include both text content and `structuredContent` so the OpenClaw-side provider client can consume parsed JSON directly.

## Implemented Tools

### `provider_status`

Input: empty object.

Returns:

- `search`: booleans for `SERPAPI_API_KEY` and `BING_SEARCH_API_KEY`
- `smtp`: booleans for `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`
- `imap`: booleans for `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASS`

### `discover_candidates`

Input:

- `niche`
- `location`
- `count`

Behavior:

- Builds four search queries: official website, contact email, best-in-location, and near-location website.
- Uses SerpApi first when configured.
- Falls back to Bing Search when SerpApi returns no results or is not configured.
- Deduplicates by domain.
- Filters social and aggregator domains including Facebook, Instagram, LinkedIn, Yelp, TripAdvisor, Google Maps, and OpenTable.
- Returns queries, provider configuration status, results, and provider errors.

### `send_email`

Input:

- `to_email`
- `subject`
- `body`
- optional `from_name`
- optional `reply_to`
- optional `signature`

Behavior:

- Requires SMTP environment variables.
- Normalizes and validates the recipient email.
- Adds an optional signature.
- Sends a plaintext MIME email over SMTP with STARTTLS.
- Returns `ok`, normalized `to_email`, and `provider_message_id`.

The OpenClaw environment is responsible for approval, compliance, duplicate prevention, suppression checks, and daily limits before calling this tool.

### `check_replies`

Input:

- `sent`: array of sent-email records from the OpenClaw environment.
- optional `limit`, default `200`.

Behavior:

- Requires IMAP environment variables.
- Polls the inbox.
- Matches replies by `From` address against supplied sent-email `to_email` values.
- Extracts plaintext body.
- Classifies sentiment and intent with auditable keyword rules.
- Returns reply objects containing campaign/lead/draft IDs supplied by the OpenClaw environment plus reply subject, snippet, raw text, sentiment, intent, and received date.

## Search Provider Details

SerpApi request:

- URL: `https://serpapi.com/search.json`
- Parameters: `engine=google`, `q`, `api_key`, `num`

Bing request:

- URL: `https://api.bing.microsoft.com/v7.0/search`
- Parameters: `q`, `count`
- Header: `Ocp-Apim-Subscription-Key`

## Reply Classification

The provider includes local reply classification so returned reply data is immediately useful to the OpenClaw environment. Intents include:

- `unsubscribe`
- `bounce`
- `auto_reply`
- `pricing_question`
- `meeting_request`
- `interested`
- `not_interested`
- `unknown`

The OpenClaw environment persists replies and applies lead/suppression state changes.

## Tests

Run:

```bash
python3 -m py_compile mcp_servers/*.py tests/*.py
python3 -m unittest discover -s tests
```

Current tests verify:

- required provider tools are exposed
- provider status returns booleans instead of secret values
