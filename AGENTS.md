# Workspace Operating Rules

This workspace contains two separate projects:

- `openclaw_environment/`: run OpenClaw agent workflows here.
- `provider_server/`: run provider MCP server work here.

For outreach campaigns, enter `openclaw_environment/` and follow its `AGENTS.md`.

The OpenClaw environment must not receive provider credentials. Search API keys, SMTP credentials, and IMAP credentials belong only in the `provider_server/` process environment.
