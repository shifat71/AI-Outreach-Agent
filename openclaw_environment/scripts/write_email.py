"""Generate and store a personalized outreach email draft for a lead."""
from __future__ import annotations

import argparse

from common import connect, now_iso, parse_user_md
from lead_utils import compliance_check, generate_email_body, generate_subject


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an outreach email draft")
    parser.add_argument("--lead-id", type=int, required=True)
    parser.add_argument("--subject", help="Override generated subject")
    parser.add_argument("--body", help="Override generated body")
    parser.add_argument("--approve", action="store_true", help="Approve immediately if compliance passes")
    args = parser.parse_args()

    con = connect()
    lead = con.execute("SELECT * FROM leads WHERE id=?", (args.lead_id,)).fetchone()
    if not lead:
        raise SystemExit(f"ERROR: no lead with id {args.lead_id}")

    campaign = con.execute("SELECT * FROM campaigns WHERE id=?", (lead["campaign_id"],)).fetchone()
    if not campaign:
        raise SystemExit(f"ERROR: lead {args.lead_id} has no campaign")

    config = parse_user_md()
    subject = args.subject or generate_subject(lead, campaign)
    body = args.body or generate_email_body(lead, campaign, config)

    compliance_status, compliance_reason = compliance_check(con, lead, subject, body)
    approval_required = bool(campaign["approval_required"])
    if args.approve and approval_required:
        raise SystemExit("ERROR: campaign requires user approval; create the draft, then approve it explicitly")
    draft_status = "approved" if args.approve and compliance_status == "passed" else "draft"

    cur = con.execute(
        """
        INSERT INTO email_drafts (
            campaign_id, lead_id, subject, body, status,
            compliance_status, compliance_reason, updated_at
        )
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            lead["campaign_id"],
            args.lead_id,
            subject,
            body,
            draft_status,
            compliance_status,
            compliance_reason,
            now_iso(),
        ),
    )
    draft_id = cur.lastrowid

    if compliance_status == "passed":
        con.execute(
            "UPDATE leads SET status='draft', updated_at=? WHERE id=? AND status NOT IN ('sent', 'replied', 'opted_out')",
            (now_iso(), args.lead_id),
        )

    con.commit()
    con.close()

    print(f"DRAFT_ID={draft_id}")
    print(f"STATUS={draft_status}")
    print(f"COMPLIANCE={compliance_status}")
    print(f"REASON={compliance_reason}")
    print(f"SUBJECT={subject}")


if __name__ == "__main__":
    main()
