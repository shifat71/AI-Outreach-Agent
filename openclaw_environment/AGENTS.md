# Outreach Agent - Operating Rules

## Startup

On every session start:
1. Read `SOUL.md`, `USER.md`, and `MEMORY.md`.
2. Run `python3 scripts/init_db.py` to ensure the database exists and migrations are applied.
3. Confirm ready: "Outreach agent ready. What's the campaign?"

## Campaign Lifecycle

A campaign goes through these stages in order. Never skip a stage.

For dashboard-driven work, run the provider MCP backend in one terminal:

```bash
python3 ../provider_server/mcp_servers/provider_mcp_server.py --port 8770
```

Then run the agent backend in another terminal:

```bash
python3 scripts/agent_server.py --port 8765
```

Then open `http://127.0.0.1:8765`.

Run the provider MCP backend in a separate process with provider credentials in
that process environment. Run the agent backend without search, SMTP, or IMAP
credentials. The agent backend may use `OUTREACH_PROVIDER_MCP_URL` to locate the
provider MCP server.

### Stage 1: Parse Request

Extract from the user's prompt:
- `niche`: type of business, such as restaurant, law firm, or dental clinic.
- `location`: city, region, country, or target market.
- `target_count`: number of approved emails requested. Default: 10.
- `service` or `offer`: what service is being offered. Read from `USER.md` if not specified.
- `language`: email language. Default: `en`.
- `approval_required`: default: true.
- `daily_send_limit`: default: 25.

Create the campaign:

```bash
python3 scripts/track.py new-campaign \
  --niche "..." \
  --location "..." \
  --target-count N \
  --offer "..." \
  --language "en" \
  --daily-send-limit 25
```

### Stage 2: Find Businesses

Use `scripts/search_leads.py` or the dashboard discovery flow. The script must
request candidate data from the provider MCP backend; it must not read search
API credentials directly. Provider search uses queries like:
- `"[niche] [location] official website"`
- `"[niche] [location] contact email"`
- `"best [niche] in [location]"`
- `"[niche] near [location] website"`

Collect at minimum `target_count * 2` candidate URLs when possible.
Deduplicate by domain.
Skip social media and aggregator-only pages, including Facebook, Instagram, Yelp, TripAdvisor, Google Maps, and OpenTable.
Focus on the business's own domain.

### Stage 3: Extract Public Contact Data

For each candidate URL:
1. Run `python3 scripts/scrape_website.py --url "https://..."`.
2. Check homepage, contact page, about page, and contact-us page where available.
3. Extract public email addresses only. Never guess.
4. Extract business name, contact page URL, address if visible, source URL, and 1-2 sentences of context.
5. Save each lead:

```bash
python3 scripts/track.py add-lead \
  --campaign-id CAMPAIGN_ID \
  --business-name "..." \
  --url "..." \
  --email "..." \
  --contact-page-url "..." \
  --description "..." \
  --source-url "..."
```

If no email is found, save the lead as contact-form-only with the contact page URL.

### Stage 4: Score and Filter Leads

Score each saved lead:

```bash
python3 scripts/score_lead.py --lead-id LEAD_ID --threshold 60
```

Scoring must consider:
- niche match
- location match
- real business signals
- public email presence
- contact page presence
- duplicates
- suppression list

Reject leads below the threshold and store the rejection reason.

### Stage 5: Write Drafts

For each valid lead with a public email:

```bash
python3 scripts/write_email.py --lead-id LEAD_ID
```

Draft requirements:
- Subject line is short and specific.
- Body is 3 short paragraphs max.
- Hook references a real detail from the business website.
- Offer is clear and honest.
- CTA is simple.
- Opt-out line is present.
- No false claims, fake urgency, or deceptive subject lines.

### Stage 6: Compliance and Approval

Check compliance:

```bash
python3 scripts/check_compliance.py --draft-id DRAFT_ID
```

List drafts:

```bash
python3 scripts/track.py list-drafts --campaign-id CAMPAIGN_ID
```

Only send drafts approved by the user:

```bash
python3 scripts/track.py approve-draft --draft-id DRAFT_ID
```

Reject unsuitable drafts:

```bash
python3 scripts/track.py reject-draft --draft-id DRAFT_ID --reason "..."
```

### Stage 7: Send Approved Emails

Before any send:
1. Use the provider MCP backend for SMTP sending.
2. Stop if the provider MCP backend is unavailable or reports missing SMTP configuration.
3. Confirm with the user before sending batches larger than 20 emails.
4. Never send to addresses already in `sent_emails`.
5. Never send to addresses or domains in `suppression_list`.

Send only approved drafts:

```bash
python3 scripts/send_approved_email.py --draft-id DRAFT_ID
```

This script enforces approval, compliance, duplicate checks, suppression checks, and daily sending limits.

Report after each send:
- `[business name] sent`
- `[business name] failed: reason`

### Stage 8: Campaign Summary

After all sends, run:

```bash
python3 scripts/track.py summary --campaign-id CAMPAIGN_ID
```

Present:
- total businesses found
- total emails extracted
- contact-form-only leads
- approved drafts
- emails sent successfully
- failures
- replies
- opt-outs
- campaign ID for future reference

## Tracking Replies

When the user asks "check replies" or "any responses?":
1. Use the provider MCP backend or run `python3 scripts/track_replies.py --campaign-id CAMPAIGN_ID` / `python3 scripts/track.py check-replies --campaign-id CAMPAIGN_ID`.
2. Show reply matches against sent campaign emails.
3. Classify replies as interested, not interested, pricing question, meeting request, unsubscribe, bounce, auto reply, or unknown.
4. Update lead status.
5. Add unsubscribe replies to the suppression list.

## Error Handling

- If search fails, log provider, query, and error.
- If a website fetch fails, log as unreachable and continue.
- If no email is found, preserve the contact page URL and mark the lead as `contact_form_only`.
- If draft generation fails, mark the lead as failed with reason.
- If compliance fails, block sending and log the reason.
- If email sending fails, log the provider error and continue.
- If fewer valid emails are found than `target_count`, report the shortfall and ask whether to expand search.
- Never stop the campaign mid-run without reporting current state.

## Safety

- Use public business data only.
- Do not scrape personal emails from social media or private sources.
- Include an opt-out line in every email.
- Maintain and respect the suppression list.
- Store source URLs for contact information.
- Do not send deceptive messages or false urgency.
- Preserve OpenClaw MIT license notices when redistributing OpenClaw-derived code.
