"""Send one approved and compliant email draft."""
from __future__ import annotations

import argparse
import sys

from common import connect, normalize_email, now_iso, parse_user_md
from lead_utils import compliance_check, is_suppressed
from send_email import send


def main() -> None:
    parser = argparse.ArgumentParser(description="Send an approved outreach draft")
    parser.add_argument("--draft-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    con = connect()
    draft = con.execute("SELECT * FROM email_drafts WHERE id=?", (args.draft_id,)).fetchone()
    if not draft:
        raise SystemExit(f"ERROR: no draft with id {args.draft_id}")
    if draft["status"] != "approved":
        raise SystemExit(f"ERROR: draft {args.draft_id} is not approved")

    lead = con.execute("SELECT * FROM leads WHERE id=?", (draft["lead_id"],)).fetchone()
    if not lead:
        raise SystemExit(f"ERROR: draft {args.draft_id} has no lead")

    to_email = normalize_email(lead["email"])
    if not to_email:
        raise SystemExit("ERROR: lead has no valid email")

    suppressed, reason = is_suppressed(con, to_email, lead["website_url"] or lead["url"])
    if suppressed:
        raise SystemExit(f"ERROR: recipient is suppressed: {reason}")

    already_sent = con.execute(
        "SELECT COUNT(*) AS n FROM sent_emails WHERE lower(to_email)=? AND status='success'",
        (to_email,),
    ).fetchone()["n"]
    if already_sent:
        raise SystemExit(f"ERROR: {to_email} was already contacted")

    compliance_status, compliance_reason = compliance_check(
        con, lead, draft["subject"], draft["body"], check_daily_limit=True
    )
    if compliance_status != "passed":
        con.execute(
            """
            UPDATE email_drafts
               SET compliance_status=?, compliance_reason=?, updated_at=?
             WHERE id=?
            """,
            (compliance_status, compliance_reason, now_iso(), args.draft_id),
        )
        con.commit()
        raise SystemExit(f"ERROR: compliance failed: {compliance_reason}")

    if args.dry_run:
        con.close()
        print(f"DRY_RUN=true")
        print(f"READY_TO_SEND={to_email}")
        print(f"SUBJECT={draft['subject']}")
        return

    cfg = parse_user_md()
    try:
        provider_message_id = send(to_email, draft["subject"], draft["body"], cfg)
    except SystemExit as exc:
        con.execute(
            """
            INSERT INTO sent_emails (
                lead_id, campaign_id, email_draft_id, to_email,
                subject, body, status, error
            )
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                lead["id"],
                lead["campaign_id"],
                args.draft_id,
                to_email,
                draft["subject"],
                draft["body"],
                "failed",
                f"smtp send failed with exit code {exc.code}",
            ),
        )
        con.execute(
            "UPDATE email_drafts SET status='failed', updated_at=? WHERE id=?",
            (now_iso(), args.draft_id),
        )
        con.execute("UPDATE leads SET status='failed', updated_at=? WHERE id=?", (now_iso(), lead["id"]))
        con.commit()
        con.close()
        raise

    con.execute(
        """
        INSERT INTO sent_emails (
            lead_id, campaign_id, email_draft_id, to_email,
            subject, body, status, provider_message_id
        )
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            lead["id"],
            lead["campaign_id"],
            args.draft_id,
            to_email,
            draft["subject"],
            draft["body"],
            "success",
            provider_message_id,
        ),
    )
    con.execute(
        """
        UPDATE email_drafts
           SET status='sent',
               sent_at=datetime('now'),
               provider_message_id=?,
               updated_at=?
         WHERE id=?
        """,
        (provider_message_id, now_iso(), args.draft_id),
    )
    con.execute("UPDATE leads SET status='sent', updated_at=? WHERE id=?", (now_iso(), lead["id"]))
    con.commit()
    con.close()
    print(f"SENT=true")
    print(f"TO={to_email}")
    print(f"PROVIDER_MESSAGE_ID={provider_message_id}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
