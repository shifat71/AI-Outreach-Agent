# Provider Server Operating Rules

This project owns provider integrations and provider credentials.

- Keep search, SMTP, and IMAP credentials only in this process environment.
- Do not add campaign database writes here.
- Do not bypass OpenClaw-side approval, compliance, duplicate, suppression, or daily-limit checks.
- Provider tools may return provider results, statuses, and errors, but never secret values.
- Validate with `python3 -m py_compile mcp_servers/*.py tests/*.py` and `python3 -m unittest tests/test_provider_mcp_server.py`.
