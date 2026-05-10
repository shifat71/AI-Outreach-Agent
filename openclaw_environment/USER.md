# My Profile

## Sender Details
Name: [YOUR FULL NAME]
Email: [YOUR EMAIL ADDRESS]
Role: [YOUR JOB TITLE, e.g. "Founder", "Sales Manager"]
Company: [YOUR COMPANY NAME]
Website: [YOUR WEBSITE URL]
Phone: [OPTIONAL — only include if you want it in emails]

## My Service Offer
<!-- Describe what you offer in 2-3 sentences. The agent uses this to personalize each email. -->
Service: [e.g. "Professional website design and SEO for local businesses. I help small business owners get more customers online with fast, mobile-friendly websites starting from $500."]

## Target Niche (default)
<!-- The agent will use this if you don't specify in your prompt -->
Default niche: [e.g. "restaurants"]
Default location: [e.g. "Paris, France"]

## Call to Action
<!-- What should recipients do? The agent uses this in every email. -->
CTA: [e.g. "Reply to this email to get a free website audit" / "Book a 15-min call at calendly.com/yourlink"]

## Runtime Provider Configuration
Do not store credentials in markdown files.

Outbound email, reply tracking, and search-provider secrets must be provided only to the provider MCP backend process environment:
- SMTP: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`
- IMAP: `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASS`
- Search: `SERPAPI_API_KEY` or `BING_SEARCH_API_KEY`

## Campaign Database
DB_PATH: ./campaigns/outreach.db
