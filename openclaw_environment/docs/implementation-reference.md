# OpenClaw Environment Implementation Reference

This document describes what is implemented in `openclaw_environment/` as of the current codebase. This project owns campaign state and agent workflow. It does not own provider credentials.

## Runtime Shape

- `scripts/agent_server.py`: entry point for the agent backend. It imports and runs `scripts/api_server.py`.
- `scripts/api_server.py`: standard-library HTTP server for the dashboard and REST API.
- `dashboard/index.html`: browser UI served by the agent backend at `/` and `/dashboard`.
- `scripts/provider_client.py`: only agent-side provider boundary. It calls the sibling provider server over HTTP MCP at `OUTREACH_PROVIDER_MCP_URL`, defaulting to `http://127.0.0.1:8770/mcp`.
- `.openclaw/config.json`: OpenClaw runtime config. It records the provider MCP URL and skill directory, but does not register credential-owning MCP scripts inside this project.

## Credential Boundary

The agent project must not receive or read provider credentials such as `SERPAPI_API_KEY`, `BING_SEARCH_API_KEY`, `SMTP_*`, or `IMAP_*`.

Allowed runtime settings in this project:

- `OUTREACH_DB_PATH`: optional override for the SQLite database path.
- `OUTREACH_PROVIDER_MCP_URL`: optional provider MCP endpoint override.

Provider-backed actions route through `scripts/provider_client.py`:

- search discovery: `discover_candidates`
- SMTP sending: `send_email`
- IMAP reply polling: `check_replies`
- redacted provider status: `provider_status`

## Database

SQLite is initialized and migrated by `scripts/init_db.py`. The default database path is read from `USER.md` as `DB_PATH`, falling back to `campaigns/outreach.db`.

Implemented tables:

- `campaigns`: campaign parameters, target counts, offer, language, approval flag, daily send limit, status, timestamps.
- `leads`: business/contact data, website URLs, public email, contact page, address, source URL, fit score, status, rejection reason, timestamps.
- `email_drafts`: generated or edited draft subject/body, approval status, compliance result, provider message ID, sent timestamp.
- `sent_emails`: immutable send attempts with status, provider message ID, error text, subject/body snapshot, sent timestamp.
- `replies`: reply records, snippets/raw text, sentiment, intent, next action, received timestamp.
- `suppression_list`: suppressed emails/domains with reason, source, timestamp.

Migration-safe additions are handled with `add_column_if_missing`, so `python3 scripts/init_db.py` is safe to run repeatedly.

## CLI Surface

Campaign setup and parsing:

- `scripts/init_db.py`: initialize or migrate the SQLite database.
- `scripts/parse_campaign.py`: parse a natural-language campaign request; `--create` stores it as a campaign.
- `scripts/track.py new-campaign`: create a campaign with explicit fields.

Lead discovery and extraction:

- `scripts/search_leads.py`: request candidate URLs from the provider server. It does not call search providers directly.
- `scripts/scrape_website.py`: fetch a website homepage and likely contact/about pages.
- `scripts/extract_contact.py`: parse HTML for public emails, business name, address, contact links, and context.
- `scripts/save_to_db.py`: save one scraped lead JSON object to a campaign.
- `scripts/track.py add-lead`: manually add a lead.

Scoring, drafting, and compliance:

- `scripts/score_lead.py`: compute and store fit score/status for a lead.
- `scripts/write_email.py`: generate a personalized draft from lead/campaign/profile data.
- `scripts/check_compliance.py`: validate one draft before approval or sending.
- `scripts/track.py approve-draft`: approve only compliant, unsuppressed drafts.
- `scripts/track.py reject-draft`: reject a draft and update lead state.
- `scripts/track.py list-drafts`: list draft review data.

Sending and reply tracking:

- `scripts/send_approved_email.py`: enforces approval, compliance, duplicate checks, suppression checks, and daily limits, then asks the provider server to send.
- `scripts/send_email.py`: low-level provider-backed sender with basic safety checks; campaign sends should use `send_approved_email.py`.
- `scripts/track_replies.py`: wrapper for `track.py check-replies`.
- `scripts/track.py check-replies`: asks the provider server for matching IMAP replies, then stores and classifies them.
- `scripts/track.py log-reply`: manually log a reply.
- `scripts/track.py log-sent`: manually log a send attempt.

Reporting and operations:

- `scripts/track.py summary`: campaign totals for businesses, emails, forms, drafts, sends, failures, replies, and opt-outs.
- `scripts/track.py export`: CSV export of campaign, lead, draft, send, and reply data.
- `scripts/track.py add-suppression`, `list-suppression`, `check-duplicate`: suppression and duplicate operations.

## Dashboard REST API

Served by `python3 scripts/agent_server.py --port 8765`.

Read endpoints:

- `GET /` and `GET /dashboard`: dashboard HTML.
- `GET /api/health`: agent backend health.
- `GET /api/provider/status`: provider MCP status via `provider_client`.
- `GET /api/jobs/{job_id}`: discovery job state.
- `GET /api/campaigns`: campaign list.
- `GET /api/campaigns/{id}/summary`: campaign counters.
- `GET /api/campaigns/{id}/leads`: campaign leads.
- `GET /api/campaigns/{id}/drafts`: campaign drafts joined with lead name/email.
- `GET /api/campaigns/{id}/replies`: replies and intent counts.
- `GET /api/campaigns/{id}/export`: CSV export.
- `GET /api/suppression?limit=N`: suppression entries.

Write endpoints:

- `POST /api/campaigns`: create campaign.
- `POST /api/campaigns/{id}/discover`: start background discovery job.
- `POST /api/campaigns/{id}/leads`: add lead.
- `POST /api/leads/{id}/score`: score lead.
- `POST /api/leads/{id}/drafts`: create draft.
- `POST /api/drafts/{id}`: edit draft and rerun compliance.
- `POST /api/drafts/{id}/approve`: approve compliant draft.
- `POST /api/drafts/{id}/reject`: reject draft.
- `POST /api/drafts/{id}/send`: run `send_approved_email.py`, dry-run by default.
- `POST /api/suppression`: add suppressed email/domain.
- `POST /api/replies`: manually log and classify a reply.

Discovery jobs use a small `ThreadPoolExecutor` and store in-memory job state in `JOBS`.

## Lead Scoring and Compliance

Implemented in `scripts/lead_utils.py`.

Scoring considers:

- niche match
- location match
- real business website signals
- public email presence
- contact page presence
- duplicates
- suppression status

Compliance checks include:

- valid recipient email
- subject length and deceptive terms
- body length minimum and maximum
- opt-out line
- daily send limit when requested
- suppression status

## Reply Classification

Reply classification uses auditable keyword rules in `scripts/common.py`. Intents include:

- `unsubscribe`
- `bounce`
- `auto_reply`
- `pricing_question`
- `meeting_request`
- `interested`
- `not_interested`
- `unknown`

Unsubscribe replies add the email to `suppression_list`. Bounces mark leads failed. Non-unknown, non-auto replies mark leads replied.

## Tests

Implemented tests live in `tests/test_requirements.py` and cover:

- natural-language campaign parsing
- public contact extraction with source URL and address
- compliance word-count and opt-out enforcement
- agent scripts avoiding direct provider credential access
- provider MCP URL constant

Run:

```bash
python3 -m py_compile scripts/*.py tests/*.py
python3 -m unittest discover -s tests
```
