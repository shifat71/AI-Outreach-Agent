---
name: email-outreach
description: Ethical B2B lead discovery and outreach. Finds public business contacts, scores leads, writes compliant drafts, requires approval, sends approved emails, and tracks replies.
---

# Email Outreach Skill

Use this skill whenever the user asks to:
- find leads in a niche or location
- write personalized outreach emails
- run an outreach campaign
- send approved outreach emails
- check replies or campaign status

## Safety Rules

- Use public business data only.
- Prefer official business websites over directories and social pages.
- Never fabricate email addresses.
- Never scrape private profiles or personal social media emails.
- Never send to an address or domain on the suppression list.
- Never send a duplicate email to the same address.
- Every draft must include a clear opt-out line.
- Drafts must be short, honest, and specific to the business.
- Do not claim guaranteed results, false urgency, or a prior relationship.
- Store the source URL for every email address.
- Require user approval before sending, unless the user has explicitly configured auto-send and the batch is within safe limits.
- Confirm with the user before sending batches larger than 20 emails.

## Step 0: Load Configuration

Read `USER.md` for:
- sender details
- service offer
- CTA
- DB path

Do not read or write credentials in markdown files. Runtime provider secrets must be present only in the provider MCP backend process environment, never in the agent backend environment.

Run:

```bash
python3 scripts/init_db.py
```

If the provider MCP backend is unavailable or missing SMTP configuration, discovery from provider search and sending must stop until it is configured.

Provider-backed operations go through one provider MCP backend:

```bash
python3 ../provider_server/mcp_servers/provider_mcp_server.py --port 8770
```

The agent backend uses `OUTREACH_PROVIDER_MCP_URL`, defaulting to `http://127.0.0.1:8770/mcp`.

For dashboard-based operation, run:

```bash
python3 scripts/agent_server.py --port 8765
```

Open `http://127.0.0.1:8765`.

## Step 1: Parse Campaign

Extract:
- `niche`
- `location`
- `target_count`
- `offer`
- `language`
- `approval_required`
- `daily_send_limit`

If `target_count` is missing, default to 10. If `offer` is missing, use the service in `USER.md`.

Create the campaign:

For natural-language requests, parse and create in one step:

```bash
python3 scripts/parse_campaign.py \
  "Find 50 restaurants in Paris and write personalized outreach emails offering my explainer video service." \
  --create
```

Or create with explicit fields:

```bash
python3 scripts/track.py new-campaign \
  --niche "restaurants" \
  --location "Paris, France" \
  --target-count 50 \
  --offer "explainer video service" \
  --language "en" \
  --daily-send-limit 25
```

## Step 2: Discover Candidate Websites

Use the search helper when API keys are configured:

```bash
python3 scripts/search_leads.py \
  --niche "restaurants" \
  --location "Paris, France" \
  --count 100
```

Search query patterns:
- `[niche] [location] official website`
- `[niche] [location] contact email`
- `best [niche] in [location]`
- `[niche] near [location] website`

Filter out social and aggregator-only pages such as Facebook, Instagram, Yelp, TripAdvisor, Google Maps, and OpenTable. Keep direct business domains.

Collect at least `target_count * 2` candidate URLs when possible.

## Step 3: Scrape and Save Leads

For each candidate website:

```bash
python3 scripts/scrape_website.py --url "https://example.com"
```

The scraper checks the homepage plus likely contact/about pages and returns:
- business name
- public emails
- contact page URL
- description/context
- pages checked
- fetch errors

Save the result:

```bash
python3 scripts/save_to_db.py --campaign-id CAMPAIGN_ID < scraped_lead.json
```

Or save manually:

```bash
python3 scripts/track.py add-lead \
  --campaign-id CAMPAIGN_ID \
  --business-name "Business Name" \
  --url "https://example.com" \
  --email "hello@example.com" \
  --contact-page-url "https://example.com/contact" \
  --description "Short business context" \
  --source-url "https://example.com/contact"
```

If no email is found, save the contact page and let the lead status remain `contact_form_only`.

## Step 4: Score Leads

Score every saved lead:

```bash
python3 scripts/score_lead.py --lead-id LEAD_ID --threshold 60
```

The score uses:
- niche match
- location match
- real business signals
- public email presence
- contact page presence
- duplicate penalties
- suppression penalties

Reject low-scoring leads with a stored rejection reason.

## Step 5: Generate Drafts

Generate a personalized draft for each valid lead:

```bash
python3 scripts/write_email.py --lead-id LEAD_ID
```

Draft rules:
- 80-140 words preferred
- short, specific subject
- specific observation from the business website
- clear offer
- one CTA
- opt-out line
- no deceptive claims or false urgency

Run or re-run compliance checks when needed:

```bash
python3 scripts/check_compliance.py --draft-id DRAFT_ID
```

## Step 6: User Approval

List drafts:

```bash
python3 scripts/track.py list-drafts --campaign-id CAMPAIGN_ID
```

After the user reviews a draft, approve it:

```bash
python3 scripts/track.py approve-draft --draft-id DRAFT_ID
```

Or reject it:

```bash
python3 scripts/track.py reject-draft --draft-id DRAFT_ID --reason "Reason"
```

Do not send drafts that are not approved.

## Step 7: Send Approved Emails

Send one approved draft:

```bash
python3 scripts/send_approved_email.py --draft-id DRAFT_ID
```

This command checks:
- draft status is `approved`
- compliance still passes
- recipient is not suppressed
- recipient was not already contacted
- daily send limit is not reached

For dry-run verification:

```bash
python3 scripts/send_approved_email.py --draft-id DRAFT_ID --dry-run
```

If more than 20 emails are queued, pause and ask the user before sending the next batch.

## Step 8: Suppression List

Add an address or domain to suppression:

```bash
python3 scripts/track.py add-suppression \
  --email "person@example.com" \
  --reason "unsubscribe" \
  --source "manual"
```

List suppression entries:

```bash
python3 scripts/track.py list-suppression
```

Suppressed addresses and domains must never be contacted again.

## Step 9: Track Replies

Check replies:

```bash
python3 scripts/track_replies.py --campaign-id CAMPAIGN_ID
```

Replies are classified as:
- interested
- not_interested
- pricing_question
- meeting_request
- unsubscribe
- bounce
- auto_reply
- unknown

Unsubscribe replies must be added to the suppression list automatically.

## Step 10: Campaign Summary and Export

Run:

```bash
python3 scripts/track.py summary --campaign-id CAMPAIGN_ID
```

Export:

```bash
python3 scripts/track.py export \
  --campaign-id CAMPAIGN_ID \
  --output campaigns/campaign_CAMPAIGN_ID.csv
```

Report:
- businesses found
- emails extracted
- contact-form-only leads
- approved drafts
- sent emails
- failures
- replies
- opt-outs
