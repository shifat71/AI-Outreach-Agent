# AI Outreach Agent

AI Outreach Agent is a local-first B2B lead discovery and outreach workflow. It helps create targeted campaigns, find official business websites, extract public contact information, score leads, draft personalized outreach emails, require user approval, send only approved compliant messages, and track replies.

The project is designed for auditable, ethical outreach. It uses public business data only, stores source URLs for contact information, enforces suppression and duplicate checks, and keeps provider credentials out of documentation files.

## Features

- Natural-language campaign parsing.
- Local SQLite campaign database with migration-safe initialization.
- Provider MCP-backed search integration for candidate business websites.
- Homepage/contact/about scraping with public email extraction.
- Lead scoring with niche, location, email, contact-page, duplicate, and suppression signals.
- Personalized email draft generation with compliance checks.
- User approval workflow before sending.
- Provider MCP-backed SMTP sending for approved drafts only.
- Provider MCP-backed IMAP reply polling and intent classification.
- Suppression list for do-not-contact emails and domains.
- Separate agent backend for the dashboard, REST API, and campaign workflow.
- Separate provider MCP backend for search, email sending, and reply tracking.
- CSV export for campaign audit and reporting.

## Repository Structure

```text
.
├── dashboard/              # Local dashboard UI
├── docs/                   # Product, architecture, and implementation documentation
├── scripts/                # Campaign, scraping, scoring, drafting, sending, reply tools
├── skills/                 # OpenClaw skill instructions
├── tests/                  # Requirement-focused tests
├── AGENTS.md               # Agent operating rules
├── SOUL.md                 # Agent identity and behavior
├── USER.md                 # Non-secret profile and campaign preferences
└── TOOLS.md                # Tool usage guide
```

Implementation details are documented in `docs/implementation-reference.md`.

## Security Model

Do not store credentials, API keys, app passwords, or tokens in markdown files or in the agent backend environment.

`USER.md` is only for non-secret sender profile details, service offer, CTA, default niche/location, and database path. Runtime secrets must be provided only to the provider MCP backend process environment.

Supported runtime variables:

```bash
# Search providers
export SERPAPI_API_KEY="..."
export BING_SEARCH_API_KEY="..."

# SMTP sending
export SMTP_HOST="smtp.example.com"
export SMTP_PORT="587"
export SMTP_USER="sender@example.com"
export SMTP_PASS="..."

# IMAP reply polling
export IMAP_HOST="imap.example.com"
export IMAP_PORT="993"
export IMAP_USER="sender@example.com"
export IMAP_PASS="..."
```

The agent backend calls the provider backend through `OUTREACH_PROVIDER_MCP_URL`, which defaults to `http://127.0.0.1:8770/mcp`. The code intentionally ignores secret-looking keys if they are accidentally added to `USER.md`.

## Quick Start

Initialize the database:

```bash
python3 scripts/init_db.py
```

Parse and create a campaign from natural language:

```bash
python3 scripts/parse_campaign.py \
  "Find 50 restaurants in Paris and write personalized outreach emails offering my explainer video service." \
  --create
```

Or create one explicitly:

```bash
python3 scripts/track.py new-campaign \
  --niche "restaurants" \
  --location "Paris, France" \
  --target-count 50 \
  --offer "explainer video service" \
  --language "en" \
  --daily-send-limit 25
```

From this folder, run the provider MCP backend in another terminal from the sibling provider project:

```bash
python3 ../provider_server/mcp_servers/provider_mcp_server.py --port 8770
```

Run the agent backend in another terminal:

```bash
python3 scripts/agent_server.py --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

## Campaign Workflow

1. Create a campaign.
2. Discover candidate business websites.
3. Scrape public contact data from official websites.
4. Save leads with source URLs.
5. Score leads and reject low-quality matches.
6. Generate personalized drafts.
7. Run compliance checks.
8. Review, edit, approve, or reject drafts.
9. Send only approved drafts.
10. Track replies and update lead status.
11. Export or summarize campaign results.

## CLI Examples

Search for candidate sites:

```bash
python3 scripts/search_leads.py \
  --niche "restaurants" \
  --location "Paris, France" \
  --count 100
```

Scrape a business site:

```bash
python3 scripts/scrape_website.py --url "https://example.com"
```

Save scraped JSON to the database:

```bash
python3 scripts/save_to_db.py --campaign-id CAMPAIGN_ID < scraped_lead.json
```

Score a lead:

```bash
python3 scripts/score_lead.py --lead-id LEAD_ID --threshold 60
```

Generate a draft:

```bash
python3 scripts/write_email.py --lead-id LEAD_ID
```

Check compliance:

```bash
python3 scripts/check_compliance.py --draft-id DRAFT_ID
```

Approve or reject:

```bash
python3 scripts/track.py approve-draft --draft-id DRAFT_ID
python3 scripts/track.py reject-draft --draft-id DRAFT_ID --reason "Not a good fit"
```

Dry-run an approved send:

```bash
python3 scripts/send_approved_email.py --draft-id DRAFT_ID --dry-run
```

Send an approved draft:

```bash
python3 scripts/send_approved_email.py --draft-id DRAFT_ID
```

Check replies:

```bash
python3 scripts/track_replies.py --campaign-id CAMPAIGN_ID
```

Summarize and export:

```bash
python3 scripts/track.py summary --campaign-id CAMPAIGN_ID
python3 scripts/track.py export --campaign-id CAMPAIGN_ID --output campaigns/campaign_CAMPAIGN_ID.csv
```

## MCP Servers

The project uses one provider MCP backend plus one agent backend.

```bash
python3 ../provider_server/mcp_servers/provider_mcp_server.py --port 8770
```

```bash
python3 scripts/agent_server.py --port 8765
```

Provider MCP tools:

- `provider_status`: reports credential configuration without returning values.
- `discover_candidates`: searches approved providers for candidate business websites.
- `send_email`: sends a plaintext email through provider-owned SMTP credentials.
- `check_replies`: polls provider-owned IMAP credentials and returns matching replies.

Provider server code lives in the sibling `../provider_server` project. The OpenClaw environment talks to it through `OUTREACH_PROVIDER_MCP_URL`.

## Compliance Rules

The agent must:

- Use public business data only.
- Prefer official business websites.
- Never fabricate email addresses.
- Store the source URL where each email was found.
- Include an opt-out line in every email.
- Avoid deceptive subjects, fake urgency, and guaranteed outcomes.
- Require approval before sending when approval is enabled.
- Check suppression and duplicate state immediately before sending.
- Enforce daily sending limits.
- Add unsubscribe replies to the suppression list.

This project helps make outreach review practical, but it is not legal advice. Review applicable laws such as CAN-SPAM, GDPR, and regional privacy requirements before running campaigns.

## Dashboard API

The local API is served by:

```bash
python3 scripts/agent_server.py --port 8765
```

Core endpoints include:

- `GET /api/health`
- `GET /api/provider/status`
- `GET /api/campaigns`
- `POST /api/campaigns`
- `POST /api/campaigns/{id}/discover`
- `GET /api/jobs/{job_id}`
- `GET /api/campaigns/{id}/summary`
- `GET /api/campaigns/{id}/leads`
- `GET /api/campaigns/{id}/drafts`
- `POST /api/drafts/{id}`
- `POST /api/drafts/{id}/approve`
- `POST /api/drafts/{id}/reject`
- `POST /api/drafts/{id}/send`
- `GET /api/campaigns/{id}/replies`
- `POST /api/replies`
- `GET /api/suppression`
- `POST /api/suppression`
- `GET /api/campaigns/{id}/export`

For endpoint behavior, database tables, CLI commands, and provider-client boundaries, see `docs/implementation-reference.md`.

## Testing

Run syntax checks:

```bash
python3 -m py_compile scripts/*.py tests/*.py
```

Run the test suite:

```bash
python3 -m unittest discover -s tests
```

## Notes

- SQLite is used for the MVP database.
- `campaigns/*.db` and generated CSV files are ignored by Git.
- Playwright rendering is optional. If Playwright is installed, the scraper can fall back to it for JavaScript-heavy sites.
- Keep dependencies minimal and auditable.
