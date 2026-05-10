# OpenClaw-Powered AI Lead Finder and Outreach Agent

## Implementation Status

This repository currently implements the product as two sibling projects:

- `openclaw_environment/`: OpenClaw-facing agent workspace with the standard-library dashboard/API, SQLite campaign database, lead workflow scripts, skill instructions, and tests.
- `provider_server/`: credential-owning HTTP MCP backend for search, SMTP, and IMAP provider operations.

The implementation intentionally uses Python standard-library servers and SQLite for the MVP. For exact implemented modules, endpoints, database tables, and provider tools, see:

- `docs/implementation-reference.md`
- `docs/two-backend-architecture.md`
- `../provider_server/docs/implementation-reference.md`

## 1. Purpose

Build an OpenClaw-powered AI lead finder and outreach agent that supports targeted business-to-business outreach. The system must discover relevant businesses, extract public contact information, generate personalized email drafts, require user approval before sending, send only approved emails, and track replies.

The product must be designed for ethical, compliant outreach, not indiscriminate bulk email. It should be suitable both as an internal automation tool and as a packaged or managed commercial solution.

## 2. Product Scope

Given a user prompt such as:

```text
Find 50 restaurants in Paris and write personalized outreach emails offering my explainer video service.
```

The agent must:

1. Parse the campaign into structured parameters.
2. Search the web for relevant businesses.
3. Prefer official business websites and reputable public directories as discovery sources.
4. Scrape public business websites for contact information.
5. Extract business name, website URL, public email, contact page, location, and short business context.
6. Compute a lead fit score.
7. Generate short, honest, personalized email drafts.
8. Include a clear opt-out line in every draft.
9. Save leads and drafts in a database.
10. Ask the user to review and approve drafts before sending.
11. Send only approved emails through a configured email provider.
12. Respect daily sending limits, duplicate checks, and suppression lists.
13. Track replies and update lead status.

## 3. Required Campaign Parameters

The campaign parser must extract:

- `niche`: business category, such as restaurant, law firm, dental clinic, SaaS company, or agency.
- `location`: city, region, country, or target market.
- `target_count`: number of approved emails requested.
- `offer`: the service or product being promoted.
- `language`: email language.
- `approval_required`: whether the user must approve drafts before sending. Default must be true.
- `daily_send_limit`: maximum number of emails allowed per day.

If `target_count` is not specified, use a conservative default. If `offer` is not specified, read it from user configuration.

## 4. Security and Compliance Rules

Implementation agents must treat these rules as hard requirements:

- Use only public business data from official websites, public contact pages, or reputable public directories.
- Do not scrape personal emails from social media, private profiles, leaked datasets, or non-public sources.
- Do not fabricate email addresses.
- Do not send deceptive messages, false urgency, false claims, or guaranteed outcomes.
- Include a polite opt-out line in every email.
- Maintain a suppression list and never contact suppressed addresses again.
- Store the source URL where each email address was found.
- Never store provider credentials or API keys in markdown documentation files.
- Keep search, SMTP, and IMAP secrets out of the agent backend environment.
- Load email, inbox, and search-provider secrets only in the separate provider MCP backend process environment.
- Check duplicates before sending.
- Enforce daily sending limits.
- Ask for explicit user confirmation before sending batches larger than 20 emails.
- Preserve MIT license notices and copyright text when redistributing OpenClaw-derived code.
- Keep dependencies minimal and auditable.
- Do not distribute unknown third-party OpenClaw skills.
- Document all outbound network behavior.

The system should support compliance with relevant laws and regulations, including GDPR, CAN-SPAM, and similar regional rules. This document is not legal advice; the implementation must make compliance review practical by storing source URLs, opt-out state, timestamps, email content, and provider message IDs.

## 5. System Architecture

### 5.1 Frontend Dashboard

The dashboard must provide:

- Campaign creation form with niche, location, target count, offer, language, approval setting, and sending limits.
- Campaign status page showing discovery, drafting, approval, sending, and reply tracking progress.
- Lead table with business name, website, email, fit score, status, source URL, and actions.
- Draft review page where the user can preview, edit, approve, or reject each email.
- Suppression controls to add an email or domain to the do-not-contact list.
- Reply dashboard summarizing interested, not interested, pricing question, meeting request, unsubscribe, bounce, auto reply, and unknown replies.

Implemented stack: a dependency-light `dashboard/index.html` UI served by the Python standard-library agent backend in `scripts/api_server.py`.

### 5.2 Backend Services

The implementation must use two separate backend processes:

- Agent backend: campaign database, dashboard/API, scraping, scoring, draft generation, approval, compliance, duplicate checks, suppression checks, summaries, and CSV export.
- Provider MCP backend: provider-owned search, SMTP, and IMAP integrations. This is the only process that may receive provider credentials.

The agent backend must request provider data and provider actions through the provider MCP backend. It must not read search API keys, SMTP credentials, or IMAP credentials directly.

The agent backend must expose API endpoints for:

- Campaign creation and status updates.
- Lead discovery jobs.
- Lead scoring and filtering.
- Email draft generation.
- Draft approval and rejection.
- Email sending.
- Reply webhook ingestion.
- Suppression list management.
- CSV export.

The provider MCP backend must expose tools for:

- Provider status without revealing secret values.
- Candidate website search.
- Sending one approved email payload.
- Polling replies for sent campaign emails supplied by the agent.

Implemented stack: Python standard-library `http.server` backends. The OpenClaw agent backend runs from `scripts/agent_server.py`; the provider MCP backend runs from `../provider_server/mcp_servers/provider_mcp_server.py`.

Long-running discovery tasks currently run through a small in-process `ThreadPoolExecutor` and expose job state through `/api/jobs/{job_id}`.

### 5.3 OpenClaw Skill Layer

Create a custom OpenClaw skill directory for the lead finder and outreach workflow. Each skill must include a `SKILL.md` file that defines:

- Purpose and trigger phrases.
- Step-by-step workflow.
- Safety and compliance rules.
- Script/tool invocation rules.
- Required user approvals.
- Failure handling.

Recommended scripts:

- `provider_client.py`: call the provider MCP backend from agent-side scripts.
- `search_leads.py`: request provider-backed search results.
- `scrape_website.py`: fetch homepage, about page, and contact page.
- `extract_contact.py`: extract public emails, contact forms, address, and business context.
- `score_lead.py`: compute fit score and rejection reasons.
- `write_email.py`: generate compliant personalized drafts.
- `check_compliance.py`: validate draft and lead before approval or sending.
- `save_to_db.py`: persist campaigns, leads, drafts, replies, and suppression entries.
- `send_approved_email.py`: enforce approval/compliance/suppression/duplicates, then request provider-backed SMTP sending.
- `track_replies.py`: request provider-backed IMAP reply data, then ingest and classify replies.

Each script should perform one discrete action so agents can call it safely and inspect failures.

## 6. Database Requirements

Use PostgreSQL, Supabase, SQLite for MVP, or another relational database with equivalent constraints.

### 6.1 `campaigns`

Stores campaign-level parameters and state.

Required fields:

- `id`
- `niche`
- `location`
- `target_count`
- `offer`
- `language`
- `approval_required`
- `daily_send_limit`
- `status`
- `created_at`
- `updated_at`

### 6.2 `leads`

Stores discovered businesses.

Required fields:

- `id`
- `campaign_id`
- `business_name`
- `website_url`
- `email`
- `contact_page_url`
- `address`
- `location`
- `description`
- `fit_score`
- `source_url`
- `status`: `new`, `contact_form_only`, `draft`, `approved`, `sent`, `replied`, `rejected`, `opted_out`, or `failed`
- `rejection_reason`
- `created_at`
- `updated_at`

### 6.3 `email_drafts`

Stores generated outreach messages.

Required fields:

- `id`
- `campaign_id`
- `lead_id`
- `subject`
- `body`
- `status`: `draft`, `approved`, `rejected`, `sent`, or `failed`
- `compliance_status`
- `compliance_reason`
- `provider_message_id`
- `sent_at`
- `created_at`
- `updated_at`

### 6.4 `replies`

Stores inbound replies.

Required fields:

- `id`
- `campaign_id`
- `lead_id`
- `email_draft_id`
- `raw_reply_text`
- `sentiment`
- `intent`: `interested`, `not_interested`, `pricing_question`, `meeting_request`, `unsubscribe`, `bounce`, `auto_reply`, or `unknown`
- `next_action`
- `received_at`
- `created_at`

### 6.5 `suppression_list`

Stores addresses that must never be contacted.

Required fields:

- `id`
- `email`
- `domain`
- `reason`
- `source`
- `created_at`

## 7. Core Workflows

### 7.1 Campaign Parsing

1. Receive the user's prompt.
2. Extract niche, location, target count, offer, language, approval setting, and send limits.
3. Validate missing values.
4. Save a campaign record.
5. Confirm the campaign summary with the user before discovery if the action may trigger sending later.

### 7.2 Lead Discovery

1. Generate search queries using the niche and location.
2. Example queries:
   - `"[niche] [location] official website"`
   - `"[niche] [location] email"`
   - `"[niche] [location] contact"`
   - `"best [niche] in [location]"`
3. Query approved search providers, such as Google Custom Search, Bing Search, or SerpAPI.
4. Collect at least `target_count * 2` candidate URLs.
5. Deduplicate by domain.
6. Filter out social media and aggregator-only URLs where possible.
7. Prefer official business domains.

### 7.3 Website Scraping and Contact Extraction

For each candidate website:

1. Crawl the homepage.
2. If needed, crawl likely contact pages:
   - `/contact`
   - `/contact-us`
   - `/about`
   - `/about-us`
3. Use Playwright when pages require JavaScript rendering.
4. Use BeautifulSoup or an equivalent HTML parser for extraction.
5. Extract emails from visible text and `mailto:` links.
6. Extract business name from title, h1, schema metadata, or prominent header.
7. Extract a one-to-two sentence business context.
8. Store contact form URL if no public email is found.
9. Mark leads without email as `contact_form_only`.

### 7.4 Lead Scoring

Compute a 0-100 fit score:

- `+30` if the business clearly matches the niche.
- `+20` if the location matches the requested city or region.
- `+20` if the site appears to be a real business and has a plausible need for the offer.
- `+15` if a public email is present.
- `+5` if a contact page exists.
- `-50` if the email, domain, or business appears duplicated.
- `-50` if the email or domain appears on the suppression list.

Reject leads below the configured acceptance threshold. Default threshold: `60`.

Store rejected leads with a clear rejection reason.

### 7.5 Email Draft Generation

Each draft must:

- Be 80-140 words.
- Use a short, specific subject line.
- Reference a real observation from the business website.
- State the offer clearly and honestly.
- Include exactly one simple call to action.
- Include an opt-out line.
- Avoid exaggerated claims and false urgency.
- Avoid generic openers such as "I hope this email finds you well."

Recommended structure:

```text
Hi [Name or team],

[Specific observation about the business.]

[Clear offer and why it is relevant.]

[CTA.] If this is not relevant, reply "no" and I will not follow up.

[Sender name]
[Company]
```

### 7.6 Compliance Checking

Before a draft can be approved or sent, run a compliance check that verifies:

- The lead has a source URL.
- The email address was found publicly.
- The recipient is not suppressed.
- The draft contains an opt-out line.
- The message is relevant to the recipient.
- The subject line is not deceptive.
- The body does not claim false facts or guaranteed outcomes.
- The campaign respects sending limits.

Failed drafts must be marked rejected or blocked with a reason.

### 7.7 Approval and Sending

1. Present drafts to the user in the dashboard.
2. Allow edits before approval.
3. Send only drafts marked `approved`.
4. Check duplicate and suppression status immediately before sending.
5. Send through a configured provider such as Mailgun, Resend, SendGrid, Gmail, or another approved provider.
6. Store provider message ID.
7. Update lead and draft status.
8. Log failures without stopping the whole campaign.
9. Enforce daily sending limits. Recommended default: 25 emails per day.

### 7.8 Reply Tracking

1. Configure inbound reply webhooks or inbox polling.
2. Store raw reply text.
3. Classify reply intent as:
   - `interested`
   - `not_interested`
   - `pricing_question`
   - `meeting_request`
   - `unsubscribe`
   - `bounce`
   - `auto_reply`
   - `unknown`
4. Update lead status.
5. Add unsubscribe requests to the suppression list.
6. Optionally generate follow-up drafts for interested leads or non-responders.
7. Follow-ups must respect configured delays, maximum attempts, and suppression status.

## 8. Error Handling

Implementation agents must handle failures without losing campaign state:

- If search fails, log provider, query, and error.
- If website fetch fails, mark the candidate unreachable and continue.
- If no email is found, preserve the contact page URL and mark as `contact_form_only`.
- If draft generation fails, mark the lead as failed with reason.
- If compliance fails, block sending and log the reason.
- If email sending fails, store the provider error and continue with the next approved draft.
- If fewer valid leads are found than requested, report the shortfall and ask whether to expand the search.

## 9. Development Roadmap

### Phase 1: MVP

- Campaign parser.
- Web search integration.
- Website scraping.
- Public email extraction.
- Lead storage.
- Simple dashboard or CSV export.

### Phase 2: Draft Generation

- Lead scoring.
- Personalized email writer.
- Compliance checker.
- Draft review interface.
- Approve and reject actions.

### Phase 3: Email Sending

- Provider integration with Mailgun, Resend, SendGrid, Gmail, or equivalent.
- Duplicate prevention.
- Daily send limits.
- Suppression list.
- Sending logs.

### Phase 4: Reply Classification

- Reply webhooks or inbox polling.
- Reply intent classifier.
- Lead status updates.
- Next-action suggestions.

### Phase 5: Follow-Up Automation

- Scheduled follow-up drafts.
- Configurable delay, such as 3-5 days.
- Maximum follow-up attempts.
- Automatic stop on reply, bounce, or unsubscribe.

## 10. Commercialization Requirements

The solution may be sold as:

- Setup service: installation, API key configuration, database setup, and custom skill setup.
- Managed service: monthly campaign operation, lead generation, approvals, sending, and reply handling.
- Custom automation: CRM integration, advanced scoring, multi-channel outreach, agency workflows, and reporting.

When marketing the product, emphasize:

- Targeted research rather than bulk spam.
- Public data only.
- User approval before sending.
- Suppression list and opt-out handling.
- Auditable local OpenClaw skill code.
- Minimal dependencies.
- MIT license compliance.

## 11. Acceptance Criteria

The implementation is complete when:

- A user can create a campaign from natural language or dashboard input.
- The system can discover and store relevant business leads.
- Each stored lead includes source URL and status.
- The system can extract public emails or mark contact-form-only leads.
- The system can score and reject low-quality leads.
- The system can generate personalized compliant drafts.
- The user can review, edit, approve, or reject drafts before sending.
- The system sends only approved, compliant, non-duplicate emails.
- Suppressed emails and domains are never contacted.
- Daily sending limits are enforced.
- Replies are stored, classified, and reflected in lead status.
- Campaign summaries report found leads, extracted emails, approved drafts, sent emails, failures, replies, and opt-outs.

## 12. Agent Implementation Notes

- Keep scripts small, inspectable, and single-purpose.
- Prefer structured parsers over ad hoc string manipulation when practical.
- Store enough metadata to audit every sent email.
- Do not hide failures from the user.
- Do not skip approval unless the user explicitly configures auto-send and the batch is within safe limits.
- Build the MVP in a way that can later move from SQLite to PostgreSQL or Supabase without rewriting business logic.
- Treat security review as part of the product, not an afterthought.
