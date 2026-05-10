"""Send a single plain-text email through the provider MCP backend.

Prefer scripts/send_approved_email.py for campaign outreach. This script is kept
as a low-level sender and performs basic duplicate/suppression/opt-out checks
unless --skip-safety-checks is passed.
"""
from __future__ import annotations

import argparse
import sys

from common import connect, is_placeholder, normalize_email, parse_user_md
from lead_utils import has_opt_out, is_suppressed
from provider_client import ProviderError, send_email as provider_send_email


def build_signature(cfg: dict) -> str:
    parts = [cfg.get("Name", ""), cfg.get("Company", ""), cfg.get("Website", "")]
    return "\n".join(p for p in parts if p and not is_placeholder(p))


def basic_safety_check(to_email: str, body: str) -> None:
    if not has_opt_out(body):
        print("ERROR: email body is missing an opt-out line", file=sys.stderr)
        sys.exit(4)

    try:
        con = connect()
    except SystemExit:
        return

    sent = con.execute(
        "SELECT COUNT(*) AS n FROM sent_emails WHERE lower(to_email)=? AND status='success'",
        (to_email,),
    ).fetchone()["n"]
    suppressed, reason = is_suppressed(con, to_email)
    con.close()

    if sent > 0:
        print(f"ERROR: {to_email} was already contacted", file=sys.stderr)
        sys.exit(5)
    if suppressed:
        print(f"ERROR: {to_email} is suppressed: {reason}", file=sys.stderr)
        sys.exit(6)


def send(to_email: str, subject: str, body: str, cfg: dict | None = None) -> str:
    cfg = cfg or {}
    normalized = normalize_email(to_email)
    if not normalized:
        print(f"ERROR: invalid recipient email: {to_email}", file=sys.stderr)
        sys.exit(2)

    try:
        result = provider_send_email(
            normalized,
            subject,
            body,
            from_name=cfg.get("Name"),
            reply_to=cfg.get("Email"),
            signature=build_signature(cfg),
        )
        message_id = result["provider_message_id"]
        print(f"OK: Email sent to {normalized}")
        print(f"PROVIDER_MESSAGE_ID={message_id}")
        return message_id
    except ProviderError as exc:
        print(f"ERROR: provider MCP send failed: {exc}", file=sys.stderr)
        sys.exit(3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a plain-text email via SMTP")
    parser.add_argument("--to", required=True, help="Recipient email address")
    parser.add_argument("--subject", required=True, help="Email subject line")
    parser.add_argument("--body", required=True, help="Plain-text email body")
    parser.add_argument("--skip-safety-checks", action="store_true")
    args = parser.parse_args()

    to_email = normalize_email(args.to)
    if not to_email:
        print(f"ERROR: invalid recipient email: {args.to}", file=sys.stderr)
        sys.exit(2)

    if not args.skip_safety_checks:
        basic_safety_check(to_email, args.body)

    send(to_email, args.subject, args.body, parse_user_md())


if __name__ == "__main__":
    main()
