# AI Outreach Agent Workspace

AI Outreach Agent is a local-first, approval-driven B2B outreach system. It helps an operator create a targeted campaign, discover relevant businesses, extract public contact data from official websites, score leads, draft personalized outreach emails, approve or reject drafts, send only approved compliant emails, and track replies.

The workspace is split into two separate projects:

- `openclaw_environment/`: the OpenClaw-facing agent workspace. It owns campaign state, dashboard/API, scraping, lead scoring, drafting, compliance checks, approval, suppression, duplicate prevention, reply logging, exports, and tests.
- `provider_server/`: the provider MCP backend. It owns provider credentials and provider integrations for search APIs, SMTP sending, and IMAP reply polling.

The OpenClaw environment must not receive search, SMTP, or IMAP credentials. It requests provider-backed data/actions from the provider server over `OUTREACH_PROVIDER_MCP_URL`, defaulting to `http://127.0.0.1:8770/mcp`.

## Problem

Cold outreach workflows often fail because they mix discovery, scraping, drafting, sending, and reply tracking into one unsafe process. That creates practical problems:

- Leads are not traceable back to source URLs.
- Emails are guessed or pulled from low-quality directories.
- Drafts are generic and not reviewed before sending.
- Duplicate sends and suppression checks are easy to miss.
- Provider credentials get mixed into agent code or documentation.
- Replies and opt-outs are not captured consistently.

This project solves those problems by making outreach auditable, staged, and approval-first.

## How It Solves It

The system separates responsibility across two backends:

1. The OpenClaw agent backend controls the outreach workflow and campaign database.
2. The provider MCP backend controls provider credentials and provider network actions.

The agent can ask for provider-backed search results, SMTP sending, and IMAP replies, but it cannot read provider secrets directly. Before any send, the agent checks approval, compliance, duplicate state, suppression state, and daily send limits.

The result is a safer workflow:

1. Parse the campaign request.
2. Discover candidate websites through the provider server.
3. Scrape public business websites.
4. Store leads with source URLs.
5. Score and filter leads.
6. Draft personalized emails.
7. Check compliance.
8. Require approval.
9. Send through the provider server only after checks pass.
10. Track replies and opt-outs.
11. Summarize/export campaign data.

## Current Implementation

The implementation is intentionally dependency-light:

- Python standard-library HTTP servers.
- SQLite campaign database.
- Plain HTML dashboard.
- Local HTTP MCP-style provider server.
- No framework dependency required for the MVP.

Implemented OpenClaw-side pieces:

- `openclaw_environment/scripts/agent_server.py`
- `openclaw_environment/scripts/api_server.py`
- `openclaw_environment/dashboard/index.html`
- `openclaw_environment/scripts/init_db.py`
- `openclaw_environment/scripts/search_leads.py`
- `openclaw_environment/scripts/scrape_website.py`
- `openclaw_environment/scripts/extract_contact.py`
- `openclaw_environment/scripts/score_lead.py`
- `openclaw_environment/scripts/write_email.py`
- `openclaw_environment/scripts/check_compliance.py`
- `openclaw_environment/scripts/send_approved_email.py`
- `openclaw_environment/scripts/track.py`
- `openclaw_environment/scripts/track_replies.py`
- `openclaw_environment/scripts/provider_client.py`

Implemented provider-side pieces:

- `provider_server/mcp_servers/provider_mcp_server.py`
- `provider_server/mcp_servers/common_mcp.py`
- `provider_server/tests/test_provider_mcp_server.py`

Detailed implementation references:

- `openclaw_environment/docs/implementation-reference.md`
- `provider_server/docs/implementation-reference.md`
- `openclaw_environment/docs/two-backend-architecture.md`

## Repository Layout

```text
.
├── AGENTS.md
├── README.md
├── openclaw_environment/
│   ├── AGENTS.md
│   ├── MEMORY.md
│   ├── README.md
│   ├── SOUL.md
│   ├── TOOLS.md
│   ├── USER.md
│   ├── campaigns/
│   ├── dashboard/
│   ├── docs/
│   ├── scripts/
│   ├── skills/
│   └── tests/
└── provider_server/
    ├── AGENTS.md
    ├── README.md
    ├── docs/
    ├── mcp_servers/
    └── tests/
```

## Security Model

Provider credentials must only be set in the `provider_server/` process environment.

Provider credentials:

- `SERPAPI_API_KEY`
- `BING_SEARCH_API_KEY`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `IMAP_HOST`
- `IMAP_PORT`
- `IMAP_USER`
- `IMAP_PASS`

OpenClaw-side runtime settings:

- `OUTREACH_DB_PATH`: optional SQLite database path override.
- `OUTREACH_PROVIDER_MCP_URL`: optional provider MCP URL override.

Do not store API keys, SMTP passwords, app passwords, or tokens in markdown files. `openclaw_environment/USER.md` is for non-secret sender profile details, service offer, CTA, default niche/location, and database path.

## Main Workflows

### 1. Campaign Creation

The agent parses or receives campaign parameters:

- `niche`
- `location`
- `target_count`
- `offer`
- `language`
- `approval_required`
- `daily_send_limit`

Campaigns are stored in SQLite in the `campaigns` table.

### 2. Lead Discovery

The OpenClaw environment calls `scripts/search_leads.py`, which requests candidate websites from the provider server. The provider server can use SerpApi or Bing Search when configured.

Candidate discovery:

- builds niche/location search queries
- filters social and aggregator-only domains
- deduplicates domains
- returns candidate business websites to the agent

### 3. Public Contact Extraction

The agent scrapes official business websites with `scripts/scrape_website.py` and `scripts/extract_contact.py`.

It checks:

- homepage
- contact page
- about page
- contact-us page

It extracts:

- business name
- website URL
- public email
- contact page URL
- address if visible
- source URL
- short context/description

Emails are never guessed.

### 4. Lead Scoring

`scripts/score_lead.py` and `scripts/lead_utils.py` score leads using:

- niche match
- location match
- real business signals
- public email presence
- contact page presence
- duplicate penalties
- suppression penalties

Low-quality leads are rejected with stored reasons.

### 5. Draft Generation

`scripts/write_email.py` creates a short personalized draft for a valid lead.

Drafts must:

- use a short, specific subject
- reference a real detail from the website
- keep the body concise
- include a clear offer
- include a simple CTA
- include an opt-out line
- avoid deception, fake urgency, and false claims

### 6. Compliance and Approval

`scripts/check_compliance.py` and `scripts/track.py approve-draft` enforce:

- valid recipient email
- subject/body constraints
- opt-out line
- no deceptive terms
- suppression checks
- approval before send

Approved drafts are stored in `email_drafts`.

### 7. Sending

`scripts/send_approved_email.py` is the campaign send path.

Before asking the provider server to send, it checks:

- draft is approved
- compliance passes
- recipient is not suppressed
- recipient was not already successfully contacted
- daily sending limit is not exceeded

The provider server sends the email through SMTP and returns a provider message ID. Send attempts are stored in `sent_emails`.

### 8. Reply Tracking

`scripts/track_replies.py` and `scripts/track.py check-replies` ask the provider server to poll IMAP. Replies are matched against sent campaign emails and classified.

Reply intents include:

- `interested`
- `not_interested`
- `pricing_question`
- `meeting_request`
- `unsubscribe`
- `bounce`
- `auto_reply`
- `unknown`

Unsubscribe replies are added to the suppression list.

### 9. Summary and Export

Campaign summaries include:

- businesses found
- emails extracted
- contact-form-only leads
- approved drafts
- successful sends
- failures
- replies
- opt-outs

Campaign data can be exported as CSV.

## Example Use Scenario

User request:

```text
Find 25 dental clinics in Austin and write personalized outreach emails offering website redesign and local SEO.
```

Expected workflow:

1. The agent creates a campaign for `dental clinics` in `Austin`.
2. The provider server searches for candidate clinic websites.
3. The agent scrapes official websites and extracts public emails.
4. Leads are saved with source URLs.
5. Leads are scored and low-quality matches are rejected.
6. Draft emails are generated with website-specific hooks.
7. The operator reviews drafts in the dashboard.
8. Approved drafts are sent through the provider server.
9. Replies are tracked and classified.
10. Unsubscribes are suppressed.
11. Campaign results are summarized/exported.

## How To Run

Use three terminals.

### Terminal 1: Initialize OpenClaw Database

```bash
cd openclaw_environment
python3 scripts/init_db.py
```

### Terminal 2: Start Provider Server

From the workspace root:

```bash
cd provider_server
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

Credentials are capability-specific. Discovery requires a search key. Sending requires SMTP settings. Reply tracking requires IMAP settings.

### Terminal 3: Start Agent Backend

From the workspace root:

```bash
cd openclaw_environment
OUTREACH_PROVIDER_MCP_URL="http://127.0.0.1:8770/mcp" \
python3 scripts/agent_server.py --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

## How To Use The Dashboard

1. Open `http://127.0.0.1:8765`.
2. Create a campaign with niche, location, target count, offer, language, approval setting, and daily limit.
3. Start discovery.
4. Review discovered leads.
5. Score leads or inspect statuses.
6. Generate drafts.
7. Edit drafts if needed.
8. Approve or reject drafts.
9. Dry-run sends before real sending.
10. Send approved drafts.
11. Check replies.
12. Export campaign data.

The dashboard talks to the OpenClaw agent backend. The agent backend talks to the provider server only when provider-backed actions are needed.

## CLI Usage

Run these commands from `openclaw_environment/`.

Create a campaign:

```bash
python3 scripts/track.py new-campaign \
  --niche "restaurants" \
  --location "Paris, France" \
  --target-count 50 \
  --offer "website redesign and SEO" \
  --language "en" \
  --daily-send-limit 25
```

Parse and create from natural language:

```bash
python3 scripts/parse_campaign.py \
  "Find 50 restaurants in Paris and write personalized outreach emails offering website redesign and SEO." \
  --create
```

Search candidate websites through the provider server:

```bash
python3 scripts/search_leads.py \
  --niche "restaurants" \
  --location "Paris, France" \
  --count 100
```

Scrape a website:

```bash
python3 scripts/scrape_website.py --url "https://example.com"
```

Save scraped JSON:

```bash
python3 scripts/save_to_db.py --campaign-id CAMPAIGN_ID < scraped_lead.json
```

Score a lead:

```bash
python3 scripts/score_lead.py --lead-id LEAD_ID --threshold 60
```

Write a draft:

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

Dry-run send:

```bash
python3 scripts/send_approved_email.py --draft-id DRAFT_ID --dry-run
```

Send approved draft:

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

## API Overview

The agent backend runs at `http://127.0.0.1:8765`.

Main read endpoints:

- `GET /`
- `GET /dashboard`
- `GET /api/health`
- `GET /api/provider/status`
- `GET /api/jobs/{job_id}`
- `GET /api/campaigns`
- `GET /api/campaigns/{id}/summary`
- `GET /api/campaigns/{id}/leads`
- `GET /api/campaigns/{id}/drafts`
- `GET /api/campaigns/{id}/replies`
- `GET /api/campaigns/{id}/export`
- `GET /api/suppression?limit=N`

Main write endpoints:

- `POST /api/campaigns`
- `POST /api/campaigns/{id}/discover`
- `POST /api/campaigns/{id}/leads`
- `POST /api/leads/{id}/score`
- `POST /api/leads/{id}/drafts`
- `POST /api/drafts/{id}`
- `POST /api/drafts/{id}/approve`
- `POST /api/drafts/{id}/reject`
- `POST /api/drafts/{id}/send`
- `POST /api/suppression`
- `POST /api/replies`

The provider server runs at `http://127.0.0.1:8770`.

Provider endpoints:

- `GET /health`
- `GET /mcp`
- `POST /mcp`

Provider MCP tools:

- `provider_status`
- `discover_candidates`
- `send_email`
- `check_replies`

## Database Overview

SQLite is initialized by `openclaw_environment/scripts/init_db.py`.

Tables:

- `campaigns`
- `leads`
- `email_drafts`
- `sent_emails`
- `replies`
- `suppression_list`

The initializer is migration-safe and can be run repeatedly.

## Compliance and Safety Rules

The project is designed for compliant review, but it is not legal advice.

Operational rules:

- Use public business data only.
- Prefer official business websites.
- Never fabricate email addresses.
- Store source URLs for contact information.
- Include opt-out text in every email.
- Require approval before sending.
- Respect suppression entries.
- Prevent duplicate sends.
- Enforce daily send limits.
- Confirm before large send batches.
- Add unsubscribe replies to suppression.
- Do not store secrets in markdown files.

Review applicable outreach laws and privacy rules before running campaigns.

## Testing

OpenClaw environment:

```bash
cd openclaw_environment
python3 -m py_compile scripts/*.py tests/*.py
python3 -m unittest discover -s tests
```

Provider server:

```bash
cd provider_server
python3 -m py_compile mcp_servers/*.py tests/*.py
python3 -m unittest discover -s tests
```

Smoke test with both servers running:

```bash
curl -s http://127.0.0.1:8770/health
curl -s http://127.0.0.1:8765/api/health
curl -s http://127.0.0.1:8765/api/provider/status
```

## Troubleshooting

Provider status shows all `false`:

- The provider server is running, but credentials were not provided in its environment.

Search returns no candidates:

- Start the provider server with `SERPAPI_API_KEY` or `BING_SEARCH_API_KEY`.
- Verify the agent is using the correct `OUTREACH_PROVIDER_MCP_URL`.

Sending fails:

- Ensure the draft is approved.
- Run a dry run first.
- Check SMTP variables in the provider server environment.
- Check suppression and duplicate state.

Reply tracking finds no replies:

- Ensure successful sends exist in `sent_emails`.
- Check IMAP variables in the provider server environment.
- Confirm replies came from the same email address that was contacted.

Database not found:

- Run `python3 scripts/init_db.py` from `openclaw_environment/`.
- Check `DB_PATH` in `openclaw_environment/USER.md`.

## Documentation Map

- Workspace operating rules: `AGENTS.md`
- OpenClaw operating rules: `openclaw_environment/AGENTS.md`
- OpenClaw README: `openclaw_environment/README.md`
- OpenClaw implementation reference: `openclaw_environment/docs/implementation-reference.md`
- Architecture notes: `openclaw_environment/docs/two-backend-architecture.md`
- Runtime provider configuration: `openclaw_environment/docs/runtime-provider-configuration.md`
- Product requirements: `openclaw_environment/docs/openclaw-ai-lead-finder-requirements.md`
- Provider README: `provider_server/README.md`
- Provider implementation reference: `provider_server/docs/implementation-reference.md`

## Current Limitations

- The MVP uses SQLite and local processes.
- Discovery depends on configured provider search credentials.
- SMTP and IMAP behavior depends on the configured provider account.
- Reply matching is based on sender address matching against sent emails.
- Reply classification uses deterministic keyword rules.
- Discovery job state is in memory and resets when the agent backend restarts.

## Intended Operating Posture

This is an operator-controlled outreach agent. It is not meant to be a blind bulk sender. Keep the workflow staged, auditable, approval-first, and respectful of suppression and opt-out requests.
# AI-Outreach-Agent
