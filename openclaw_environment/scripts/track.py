"""Campaign tracking CLI. All campaign DB mutations go through here."""
from __future__ import annotations

import argparse
import csv
import os
import sys

from common import (
    classify_reply,
    connect,
    default_offer,
    domain_from_email,
    domain_from_url,
    normalize_email,
    now_iso,
    positive_int,
)
from lead_utils import compliance_check, is_suppressed
from provider_client import ProviderError, check_replies as provider_check_replies


def require_db():
    return connect()


def ensure_email(value: str | None) -> str | None:
    if value is None:
        return None
    email = normalize_email(value)
    if not email:
        raise SystemExit(f"ERROR: invalid email address: {value}")
    return email


def update_reply_state(con, lead_id: int, intent: str, email: str | None = None) -> None:
    if intent == "unsubscribe":
        con.execute("UPDATE leads SET status='opted_out', updated_at=? WHERE id=?", (now_iso(), lead_id))
        if email:
            con.execute(
                """
                INSERT OR IGNORE INTO suppression_list (email, reason, source)
                VALUES (?, 'unsubscribe reply', 'reply_tracking')
                """,
                (email,),
            )
    elif intent == "bounce":
        con.execute("UPDATE leads SET status='failed', updated_at=? WHERE id=?", (now_iso(), lead_id))
    elif intent not in {"auto_reply", "unknown"}:
        con.execute("UPDATE leads SET status='replied', updated_at=? WHERE id=?", (now_iso(), lead_id))


def cmd_new_campaign(args):
    try:
        target = positive_int(args.target_count or args.target, 10, "target_count")
        daily_send_limit = positive_int(args.daily_send_limit, 25, "daily_send_limit")
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    offer = args.offer or default_offer()
    approval_required = 0 if args.no_approval else 1
    c = require_db()
    cur = c.execute(
        """
        INSERT INTO campaigns (
            niche, location, target, target_count, offer, language,
            approval_required, daily_send_limit, status, updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            args.niche,
            args.location,
            target,
            target,
            offer,
            args.language,
            approval_required,
            daily_send_limit,
            "draft",
            now_iso(),
        ),
    )
    c.commit()
    cid = cur.lastrowid
    c.close()
    print(f"CAMPAIGN_ID={cid}")


def cmd_add_lead(args):
    c = require_db()
    campaign = c.execute("SELECT id FROM campaigns WHERE id=?", (args.campaign_id,)).fetchone()
    if not campaign:
        raise SystemExit(f"ERROR: no campaign with id {args.campaign_id}")

    email = ensure_email(args.email) if args.email else None
    name = args.business_name or args.name
    url = args.website_url or args.url
    context = args.description or args.context
    source_url = args.source_url or args.contact_page_url or url
    status = args.status or ("new" if email else "contact_form_only")

    try:
        cur = c.execute(
            """
            INSERT INTO leads (
                campaign_id, name, url, email, context, status,
                business_name, website_url, contact_page_url, address,
                location, description, fit_score, source_url,
                rejection_reason, updated_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                args.campaign_id,
                name,
                url,
                email,
                context,
                status,
                name,
                url,
                args.contact_page_url,
                args.address,
                args.location,
                context,
                args.fit_score,
                source_url,
                args.rejection_reason,
                now_iso(),
            ),
        )
        c.commit()
        print(f"LEAD_ID={cur.lastrowid}")
    except Exception as exc:
        if email and "UNIQUE" in str(exc).upper():
            row = c.execute("SELECT id FROM leads WHERE lower(email)=?", (email,)).fetchone()
            print(f"LEAD_ID={row['id']}  # duplicate email, skipped insert")
        else:
            raise
    finally:
        c.close()


def cmd_check_duplicate(args):
    email = ensure_email(args.email)
    c = require_db()
    sent = c.execute(
        "SELECT COUNT(*) AS n FROM sent_emails WHERE lower(to_email)=?", (email,)
    ).fetchone()["n"]
    lead = c.execute(
        "SELECT COUNT(*) AS n FROM leads WHERE lower(email)=?", (email,)
    ).fetchone()["n"]
    suppressed, reason = is_suppressed(c, email)
    c.close()
    print("DUPLICATE=true" if sent > 0 else "DUPLICATE=false")
    print("LEAD_EXISTS=true" if lead > 0 else "LEAD_EXISTS=false")
    print("SUPPRESSED=true" if suppressed else "SUPPRESSED=false")
    if reason:
        print(f"SUPPRESSION_REASON={reason}")


def cmd_add_suppression(args):
    email = ensure_email(args.email) if args.email else None
    domain = args.domain or (domain_from_email(email) if args.suppress_domain and email else None)
    if domain:
        domain = domain.lower().removeprefix("www.")
    if not email and not domain:
        raise SystemExit("ERROR: provide --email or --domain")

    c = require_db()
    c.execute(
        """
        INSERT OR IGNORE INTO suppression_list (email, domain, reason, source)
        VALUES (?,?,?,?)
        """,
        (email, domain, args.reason, args.source),
    )
    if email:
        c.execute(
            "UPDATE leads SET status='opted_out', updated_at=? WHERE lower(email)=?",
            (now_iso(), email),
        )
    if domain:
        c.execute(
            """
            UPDATE leads
               SET status='opted_out', updated_at=?
             WHERE lower(COALESCE(website_url, url, '')) LIKE ?
            """,
            (now_iso(), f"%{domain}%"),
        )
    c.commit()
    c.close()
    print("SUPPRESSION_ADDED=true")


def cmd_list_suppression(args):
    c = require_db()
    rows = c.execute(
        """
        SELECT id, email, domain, reason, source, created_at
          FROM suppression_list
         ORDER BY created_at DESC, id DESC
         LIMIT ?
        """,
        (args.limit,),
    ).fetchall()
    c.close()
    if not rows:
        print("No suppression entries.")
        return
    for row in rows:
        target = row["email"] or row["domain"]
        print(f"{row['id']}: {target} | {row['reason'] or 'no reason'} | {row['source'] or 'manual'}")


def cmd_approve_draft(args):
    c = require_db()
    draft = c.execute("SELECT * FROM email_drafts WHERE id=?", (args.draft_id,)).fetchone()
    if not draft:
        raise SystemExit(f"ERROR: no draft with id {args.draft_id}")
    lead = c.execute("SELECT * FROM leads WHERE id=?", (draft["lead_id"],)).fetchone()
    status, reason = compliance_check(c, lead, draft["subject"], draft["body"])
    if status != "passed":
        c.execute(
            """
            UPDATE email_drafts
               SET compliance_status=?, compliance_reason=?, updated_at=?
             WHERE id=?
            """,
            (status, reason, now_iso(), args.draft_id),
        )
        c.commit()
        c.close()
        print(f"APPROVED=false")
        print(f"REASON={reason}")
        raise SystemExit(2)

    c.execute(
        """
        UPDATE email_drafts
           SET status='approved',
               compliance_status='passed',
               compliance_reason='ok',
               updated_at=?
         WHERE id=?
        """,
        (now_iso(), args.draft_id),
    )
    c.execute(
        "UPDATE leads SET status='approved', updated_at=? WHERE id=?",
        (now_iso(), draft["lead_id"]),
    )
    c.commit()
    c.close()
    print("APPROVED=true")


def cmd_reject_draft(args):
    c = require_db()
    draft = c.execute("SELECT lead_id FROM email_drafts WHERE id=?", (args.draft_id,)).fetchone()
    if not draft:
        raise SystemExit(f"ERROR: no draft with id {args.draft_id}")
    c.execute(
        """
        UPDATE email_drafts
           SET status='rejected',
               compliance_reason=COALESCE(?, compliance_reason),
               updated_at=?
         WHERE id=?
        """,
        (args.reason, now_iso(), args.draft_id),
    )
    c.execute(
        "UPDATE leads SET status='rejected', rejection_reason=?, updated_at=? WHERE id=?",
        (args.reason or "draft rejected", now_iso(), draft["lead_id"]),
    )
    c.commit()
    c.close()
    print("REJECTED=true")


def cmd_list_drafts(args):
    c = require_db()
    params = []
    where = "WHERE 1=1"
    if args.campaign_id:
        where += " AND d.campaign_id=?"
        params.append(args.campaign_id)
    if args.status:
        where += " AND d.status=?"
        params.append(args.status)
    params.append(args.limit)
    rows = c.execute(
        f"""
        SELECT d.id, d.status, d.compliance_status, d.subject,
               l.business_name, l.email
          FROM email_drafts d
          JOIN leads l ON l.id=d.lead_id
          {where}
         ORDER BY d.created_at DESC, d.id DESC
         LIMIT ?
        """,
        params,
    ).fetchall()
    c.close()
    if not rows:
        print("No drafts found.")
        return
    for row in rows:
        print(
            f"{row['id']}: [{row['status']}/{row['compliance_status']}] "
            f"{row['business_name'] or 'Unknown'} <{row['email'] or 'no email'}> | {row['subject']}"
        )


def cmd_log_sent(args):
    c = require_db()
    lead = c.execute("SELECT * FROM leads WHERE id=?", (args.lead_id,)).fetchone()
    if not lead:
        raise SystemExit(f"ERROR: no lead with id {args.lead_id}")

    to_email = ensure_email(args.to_email or lead["email"])
    body = args.body or ""
    draft_id = args.draft_id
    if draft_id and not body:
        draft = c.execute("SELECT body FROM email_drafts WHERE id=?", (draft_id,)).fetchone()
        body = draft["body"] if draft else ""

    c.execute(
        """
        INSERT INTO sent_emails (
            lead_id, campaign_id, email_draft_id, to_email, subject,
            body, status, error, provider_message_id
        )
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            args.lead_id,
            lead["campaign_id"],
            draft_id,
            to_email,
            args.subject,
            body,
            args.status,
            args.error or None,
            args.provider_message_id,
        ),
    )

    if args.status == "success":
        c.execute("UPDATE leads SET status='sent', updated_at=? WHERE id=?", (now_iso(), args.lead_id))
        if draft_id:
            c.execute(
                """
                UPDATE email_drafts
                   SET status='sent', sent_at=datetime('now'),
                       provider_message_id=?, updated_at=?
                 WHERE id=?
                """,
                (args.provider_message_id, now_iso(), draft_id),
            )
    else:
        c.execute("UPDATE leads SET status='failed', updated_at=? WHERE id=?", (now_iso(), args.lead_id))
        if draft_id:
            c.execute(
                "UPDATE email_drafts SET status='failed', updated_at=? WHERE id=?",
                (now_iso(), draft_id),
            )
    c.commit()
    c.close()
    print(f"Logged: lead {args.lead_id} -> {args.status}")


def cmd_log_reply(args):
    from_email = ensure_email(args.from_email)
    raw = args.raw_reply_text or args.snippet or ""
    sentiment, intent = classify_reply(raw)
    c = require_db()
    lead = c.execute("SELECT * FROM leads WHERE id=?", (args.lead_id,)).fetchone()
    if not lead:
        raise SystemExit(f"ERROR: no lead with id {args.lead_id}")
    c.execute(
        """
        INSERT INTO replies (
            campaign_id, lead_id, email_draft_id, from_email, subject,
            snippet, raw_reply_text, sentiment, intent, next_action, received_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            lead["campaign_id"],
            args.lead_id,
            args.email_draft_id,
            from_email,
            args.subject,
            (raw or "")[:200],
            raw,
            sentiment,
            intent,
            args.next_action,
            args.received_at or now_iso(),
        ),
    )
    update_reply_state(c, args.lead_id, intent, from_email)
    c.commit()
    c.close()
    print(f"REPLY_LOGGED=true")
    print(f"INTENT={intent}")
    print(f"SENTIMENT={sentiment}")


def cmd_check_replies(args):
    c = require_db()
    params = []
    where = "WHERE se.status='success'"
    if args.campaign_id:
        where += " AND se.campaign_id=?"
        params.append(args.campaign_id)
    sent_rows = c.execute(
        f"""
        SELECT se.to_email, se.lead_id, se.email_draft_id, se.campaign_id
          FROM sent_emails se
          {where}
        """,
        params,
    ).fetchall()
    sent = [dict(row) for row in sent_rows]
    if not sent:
        c.close()
        print("No sent emails found for reply matching.")
        return

    try:
        provider_output = provider_check_replies(sent)
    except ProviderError as exc:
        c.close()
        print(f"ERROR: provider MCP reply check failed: {exc}", file=sys.stderr)
        sys.exit(1)

    found = 0
    for reply in provider_output.get("replies", []):
        from_addr = normalize_email(reply.get("from_email"))
        lead_id = reply.get("lead_id")
        if not from_addr or not lead_id:
            continue

        raw = reply.get("raw_reply_text") or reply.get("snippet") or ""
        sentiment = reply.get("sentiment")
        intent = reply.get("intent")
        if not sentiment or not intent:
            sentiment, intent = classify_reply(raw)
        c.execute(
            """
            INSERT INTO replies (
                campaign_id, lead_id, email_draft_id, from_email, subject,
                snippet, raw_reply_text, sentiment, intent, received_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                reply.get("campaign_id"),
                reply.get("lead_id"),
                reply.get("email_draft_id"),
                from_addr,
                reply.get("subject") or "",
                raw.strip()[:200],
                raw.strip(),
                sentiment,
                intent,
                reply.get("received_at") or now_iso(),
            ),
        )
        update_reply_state(c, int(lead_id), intent, from_addr)
        c.commit()
        print(f"REPLY from {from_addr}: {intent} | {(reply.get('subject') or '')[:60]}")
        found += 1

    c.close()

    if found == 0:
        print("No new replies found.")
    else:
        print(f"\n{found} reply/replies logged to DB.")


def cmd_summary(args):
    c = require_db()
    params = []
    where_leads = "WHERE 1=1"
    if args.campaign_id:
        campaign = c.execute(
            "SELECT niche, location, target_count FROM campaigns WHERE id=?", (args.campaign_id,)
        ).fetchone()
        if not campaign:
            print(f"No campaign with id {args.campaign_id}")
            c.close()
            return
        where_leads += " AND campaign_id=?"
        params.append(args.campaign_id)
        header = (
            f"Campaign #{args.campaign_id} | {campaign['niche']} in "
            f"{campaign['location']} (target: {campaign['target_count']})"
        )
    else:
        header = "All campaigns"

    lead_count = c.execute(f"SELECT COUNT(*) AS n FROM leads {where_leads}", params).fetchone()["n"]
    email_count = c.execute(
        f"SELECT COUNT(*) AS n FROM leads {where_leads} AND email IS NOT NULL", params
    ).fetchone()["n"]
    contact_only = c.execute(
        f"SELECT COUNT(*) AS n FROM leads {where_leads} AND status='contact_form_only'", params
    ).fetchone()["n"]
    approved = c.execute(
        """
        SELECT COUNT(*) AS n FROM email_drafts
        WHERE (? IS NULL OR campaign_id=?) AND status='approved'
        """,
        (args.campaign_id, args.campaign_id),
    ).fetchone()["n"]
    sent_ok = c.execute(
        """
        SELECT COUNT(*) AS n FROM sent_emails
        WHERE (? IS NULL OR campaign_id=?) AND status='success'
        """,
        (args.campaign_id, args.campaign_id),
    ).fetchone()["n"]
    sent_fail = c.execute(
        """
        SELECT COUNT(*) AS n FROM sent_emails
        WHERE (? IS NULL OR campaign_id=?) AND status='failed'
        """,
        (args.campaign_id, args.campaign_id),
    ).fetchone()["n"]
    replies = c.execute(
        """
        SELECT COUNT(*) AS n FROM replies
        WHERE (? IS NULL OR campaign_id=?)
        """,
        (args.campaign_id, args.campaign_id),
    ).fetchone()["n"]
    opt_outs = c.execute(
        f"SELECT COUNT(*) AS n FROM leads {where_leads} AND status='opted_out'", params
    ).fetchone()["n"]
    c.close()

    bar = "-" * 58
    print(f"\n{header}")
    print(bar)
    print(f"  Businesses found:        {lead_count}")
    print(f"  Emails extracted:        {email_count}")
    print(f"  Contact-form only:       {contact_only}")
    print(f"  Drafts approved:         {approved}")
    print(f"  Emails sent:             {sent_ok}")
    print(f"  Failures:                {sent_fail}")
    print(f"  Replies received:        {replies}")
    print(f"  Opt-outs:                {opt_outs}")
    print(bar)


def cmd_export(args):
    c = require_db()
    params = []
    where = "WHERE 1=1"
    if args.campaign_id:
        where += " AND l.campaign_id=?"
        params.append(args.campaign_id)

    rows = c.execute(
        f"""
        SELECT
            c.id AS campaign_id,
            c.niche,
            c.location AS campaign_location,
            l.business_name,
            l.website_url,
            l.email,
            l.contact_page_url,
            l.address,
            l.location AS lead_location,
            l.description,
            l.fit_score,
            l.source_url,
            l.status AS lead_status,
            l.rejection_reason,
            d.id AS draft_id,
            d.status AS draft_status,
            d.compliance_status,
            d.subject,
            se.status AS send_status,
            se.sent_at,
            r.intent AS reply_intent,
            r.received_at AS reply_received_at
        FROM leads l
        JOIN campaigns c ON c.id=l.campaign_id
        LEFT JOIN email_drafts d ON d.lead_id=l.id
        LEFT JOIN sent_emails se ON se.lead_id=l.id
        LEFT JOIN replies r ON r.lead_id=l.id
        {where}
        ORDER BY l.id
        """,
        params,
    ).fetchall()
    c.close()

    out = args.output or f"campaigns/export_{args.campaign_id or 'all'}.csv"
    os.makedirs(os.path.dirname(out), exist_ok=True)

    fieldnames = [
        "campaign_id",
        "niche",
        "campaign_location",
        "business_name",
        "website_url",
        "email",
        "contact_page_url",
        "address",
        "lead_location",
        "description",
        "fit_score",
        "source_url",
        "lead_status",
        "rejection_reason",
        "draft_id",
        "draft_status",
        "compliance_status",
        "subject",
        "send_status",
        "sent_at",
        "reply_intent",
        "reply_received_at",
    ]
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    print(f"Exported {len(rows)} rows to {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Outreach campaign tracker")
    sub = p.add_subparsers(dest="command", required=True)

    nc = sub.add_parser("new-campaign")
    nc.add_argument("--niche", required=True)
    nc.add_argument("--location", required=True)
    nc.add_argument("--target", type=int)
    nc.add_argument("--target-count", type=int)
    nc.add_argument("--offer")
    nc.add_argument("--language", default="en")
    nc.add_argument("--daily-send-limit", type=int, default=25)
    nc.add_argument("--no-approval", action="store_true")
    nc.set_defaults(func=cmd_new_campaign)

    al = sub.add_parser("add-lead")
    al.add_argument("--campaign-id", type=int, required=True)
    al.add_argument("--name")
    al.add_argument("--business-name")
    al.add_argument("--url", required=True)
    al.add_argument("--website-url")
    al.add_argument("--email")
    al.add_argument("--context")
    al.add_argument("--description")
    al.add_argument("--contact-page-url")
    al.add_argument("--address")
    al.add_argument("--location")
    al.add_argument("--source-url")
    al.add_argument("--fit-score", type=int, default=0)
    al.add_argument("--status")
    al.add_argument("--rejection-reason")
    al.set_defaults(func=cmd_add_lead)

    cd = sub.add_parser("check-duplicate")
    cd.add_argument("--email", required=True)
    cd.set_defaults(func=cmd_check_duplicate)

    sup = sub.add_parser("add-suppression")
    sup.add_argument("--email")
    sup.add_argument("--domain")
    sup.add_argument("--suppress-domain", action="store_true")
    sup.add_argument("--reason", default="manual")
    sup.add_argument("--source", default="manual")
    sup.set_defaults(func=cmd_add_suppression)

    lsup = sub.add_parser("list-suppression")
    lsup.add_argument("--limit", type=int, default=50)
    lsup.set_defaults(func=cmd_list_suppression)

    ad = sub.add_parser("approve-draft")
    ad.add_argument("--draft-id", type=int, required=True)
    ad.set_defaults(func=cmd_approve_draft)

    rd = sub.add_parser("reject-draft")
    rd.add_argument("--draft-id", type=int, required=True)
    rd.add_argument("--reason")
    rd.set_defaults(func=cmd_reject_draft)

    ld = sub.add_parser("list-drafts")
    ld.add_argument("--campaign-id", type=int)
    ld.add_argument("--status")
    ld.add_argument("--limit", type=int, default=50)
    ld.set_defaults(func=cmd_list_drafts)

    ls = sub.add_parser("log-sent")
    ls.add_argument("--lead-id", type=int, required=True)
    ls.add_argument("--draft-id", type=int)
    ls.add_argument("--to-email")
    ls.add_argument("--subject", required=True)
    ls.add_argument("--body")
    ls.add_argument("--status", required=True, choices=["success", "failed"])
    ls.add_argument("--error")
    ls.add_argument("--provider-message-id")
    ls.set_defaults(func=cmd_log_sent)

    lr = sub.add_parser("log-reply")
    lr.add_argument("--lead-id", type=int, required=True)
    lr.add_argument("--email-draft-id", type=int)
    lr.add_argument("--from-email", required=True)
    lr.add_argument("--subject")
    lr.add_argument("--snippet")
    lr.add_argument("--raw-reply-text")
    lr.add_argument("--next-action")
    lr.add_argument("--received-at")
    lr.set_defaults(func=cmd_log_reply)

    sm = sub.add_parser("summary")
    sm.add_argument("--campaign-id", type=int)
    sm.set_defaults(func=cmd_summary)

    cr = sub.add_parser("check-replies")
    cr.add_argument("--campaign-id", type=int)
    cr.set_defaults(func=cmd_check_replies)

    ex = sub.add_parser("export")
    ex.add_argument("--campaign-id", type=int)
    ex.add_argument("--output")
    ex.set_defaults(func=cmd_export)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
