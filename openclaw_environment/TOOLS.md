# Tool Usage Guide

## web_search
Use for finding business websites.
- Prefer queries with "website" or "official site" to get direct domains over directories
- Run 3-5 search queries per campaign to get enough candidates
- Extract URLs from results, ignore aggregator sites

## web_fetch
Use for reading individual business websites.
- Always fetch the homepage first
- If no email found, try appending `/contact`, `/about`, `/contact-us` to the base URL
- Extract: business name, email addresses, brief description of what they do
- Regex for emails: `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`

## browser
Use when web_fetch fails (JS-heavy sites) or you need to interact with a contact form.
- Navigate to URL, take screenshot to verify page loaded
- Use browser to find emails hidden in JS-rendered content
- Do NOT use browser to fill and submit contact forms unless user explicitly asks

## exec
Use to run the Python helper scripts in `scripts/`:
- `python3 scripts/init_db.py` — initialize DB (run once per session start)
- `python3 scripts/parse_campaign.py "Find 50 restaurants in Paris..."` — parse a natural-language campaign request; add `--create` to save it
- `python3 scripts/search_leads.py --niche X --location Y --count N` — request candidate discovery from the provider MCP backend
- `python3 scripts/scrape_website.py --url X` — fetch homepage/contact/about pages and extract public contact data
- `python3 scripts/save_to_db.py --campaign-id N` — save scraped lead JSON from stdin
- `python3 scripts/score_lead.py --lead-id N` — compute and store lead fit score
- `python3 scripts/write_email.py --lead-id N` — generate and store a compliant draft
- `python3 scripts/check_compliance.py --draft-id N` — validate a draft before approval or sending
- `python3 scripts/send_approved_email.py --draft-id N` — send one approved, compliant, non-duplicate draft
- `python3 scripts/send_email.py --to X --subject X --body X` — low-level provider-backed sender; prefer `send_approved_email.py` for campaigns
- `python3 scripts/track.py <command>` — manage campaign data
- `python3 ../provider_server/mcp_servers/provider_mcp_server.py --port 8770` — run the sibling provider MCP backend with provider credentials in that process environment
- `python3 scripts/agent_server.py --port 8765` — run the agent backend, dashboard, and REST API without provider credentials

## MCP servers
Use the provider MCP backend for provider-backed operations:
- `python3 ../provider_server/mcp_servers/provider_mcp_server.py --port 8770` — HTTP MCP server for search, SMTP sending, and IMAP reply polling.
- `OUTREACH_PROVIDER_MCP_URL=http://127.0.0.1:8770/mcp` — optional agent-side URL override.

Provider server code lives in the sibling `../provider_server` project. The OpenClaw environment talks to it through `OUTREACH_PROVIDER_MCP_URL`.

Never save provider credentials in markdown files. Keep secrets only in the provider MCP server launcher environment.

## code_execution
Use for:
- Parsing raw HTML/text to extract emails when web_fetch returns messy content
- Counting results, deduplicating URL lists
- Generating campaign statistics

## cron
Use when user asks to "check replies every hour" or schedule follow-up campaigns.
- Example: `cron.create("check-replies", "0 * * * *", "check for email replies in campaign DB")`
