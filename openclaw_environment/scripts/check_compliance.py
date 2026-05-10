"""Validate an outreach draft before approval or sending."""
from __future__ import annotations

import argparse

from common import connect, now_iso
from lead_utils import compliance_check


def main() -> None:
    parser = argparse.ArgumentParser(description="Check outreach draft compliance")
    parser.add_argument("--draft-id", type=int)
    parser.add_argument("--lead-id", type=int)
    parser.add_argument("--subject")
    parser.add_argument("--body")
    parser.add_argument("--check-daily-limit", action="store_true")
    parser.add_argument("--no-update", action="store_true")
    args = parser.parse_args()

    if not args.draft_id and not args.lead_id:
        raise SystemExit("ERROR: provide --draft-id or --lead-id with --subject and --body")

    con = connect()

    draft = None
    if args.draft_id:
        draft = con.execute("SELECT * FROM email_drafts WHERE id=?", (args.draft_id,)).fetchone()
        if not draft:
            raise SystemExit(f"ERROR: no draft with id {args.draft_id}")
        lead_id = draft["lead_id"]
        subject = args.subject or draft["subject"]
        body = args.body or draft["body"]
    else:
        lead_id = args.lead_id
        subject = args.subject
        body = args.body

    if not subject or not body:
        raise SystemExit("ERROR: subject and body are required when no draft supplies them")

    lead = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        raise SystemExit(f"ERROR: no lead with id {lead_id}")

    status, reason = compliance_check(con, lead, subject, body, args.check_daily_limit)

    if draft and not args.no_update:
        con.execute(
            """
            UPDATE email_drafts
               SET compliance_status=?,
                   compliance_reason=?,
                   updated_at=?
             WHERE id=?
            """,
            (status, reason, now_iso(), args.draft_id),
        )
        con.commit()

    con.close()
    print(f"COMPLIANCE={status}")
    print(f"REASON={reason}")

    if status != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
