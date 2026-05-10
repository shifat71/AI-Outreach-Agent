"""Initialize or migrate the outreach SQLite database.

Safe to run multiple times.
"""
from __future__ import annotations

from common import add_column_if_missing, connect_or_create, get_db_path


def init(db_path: str | None = None) -> None:
    con = connect_or_create()
    cur = con.cursor()

    cur.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS campaigns (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            niche               TEXT NOT NULL,
            location            TEXT NOT NULL,
            target              INTEGER NOT NULL DEFAULT 10,
            target_count        INTEGER NOT NULL DEFAULT 10,
            offer               TEXT,
            language            TEXT NOT NULL DEFAULT 'en',
            approval_required   INTEGER NOT NULL DEFAULT 1,
            daily_send_limit    INTEGER NOT NULL DEFAULT 25,
            status              TEXT NOT NULL DEFAULT 'draft',
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS leads (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id         INTEGER NOT NULL REFERENCES campaigns(id),
            name                TEXT,
            url                 TEXT NOT NULL,
            email               TEXT,
            context             TEXT,
            status              TEXT DEFAULT 'new',
            business_name       TEXT,
            website_url         TEXT,
            contact_page_url    TEXT,
            address             TEXT,
            location            TEXT,
            description         TEXT,
            fit_score           INTEGER DEFAULT 0,
            source_url          TEXT,
            rejection_reason    TEXT,
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS email_drafts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id         INTEGER NOT NULL REFERENCES campaigns(id),
            lead_id             INTEGER NOT NULL REFERENCES leads(id),
            subject             TEXT NOT NULL,
            body                TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'draft',
            compliance_status   TEXT NOT NULL DEFAULT 'pending',
            compliance_reason   TEXT,
            provider_message_id TEXT,
            sent_at             TEXT,
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sent_emails (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id             INTEGER NOT NULL REFERENCES leads(id),
            campaign_id         INTEGER REFERENCES campaigns(id),
            email_draft_id      INTEGER REFERENCES email_drafts(id),
            to_email            TEXT NOT NULL,
            subject             TEXT NOT NULL,
            body                TEXT NOT NULL,
            status              TEXT NOT NULL,
            error               TEXT,
            provider_message_id TEXT,
            sent_at             TEXT DEFAULT (datetime('now')),
            created_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS replies (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id         INTEGER REFERENCES campaigns(id),
            lead_id             INTEGER NOT NULL REFERENCES leads(id),
            email_draft_id      INTEGER REFERENCES email_drafts(id),
            from_email          TEXT,
            subject             TEXT,
            snippet             TEXT,
            raw_reply_text      TEXT,
            sentiment           TEXT,
            intent              TEXT DEFAULT 'unknown',
            next_action         TEXT,
            received_at         TEXT,
            created_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS suppression_list (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            email               TEXT,
            domain              TEXT,
            reason              TEXT,
            source              TEXT,
            created_at          TEXT DEFAULT (datetime('now'))
        );
        """
    )

    # Migration-safe additions for databases created by older versions.
    for column, definition in {
        "target_count": "INTEGER NOT NULL DEFAULT 10",
        "offer": "TEXT",
        "language": "TEXT NOT NULL DEFAULT 'en'",
        "approval_required": "INTEGER NOT NULL DEFAULT 1",
        "daily_send_limit": "INTEGER NOT NULL DEFAULT 25",
        "status": "TEXT NOT NULL DEFAULT 'draft'",
        "updated_at": "TEXT",
    }.items():
        add_column_if_missing(con, "campaigns", column, definition)

    for column, definition in {
        "business_name": "TEXT",
        "website_url": "TEXT",
        "contact_page_url": "TEXT",
        "address": "TEXT",
        "location": "TEXT",
        "description": "TEXT",
        "fit_score": "INTEGER DEFAULT 0",
        "source_url": "TEXT",
        "rejection_reason": "TEXT",
        "updated_at": "TEXT",
    }.items():
        add_column_if_missing(con, "leads", column, definition)

    for column, definition in {
        "campaign_id": "INTEGER REFERENCES campaigns(id)",
        "email_draft_id": "INTEGER REFERENCES email_drafts(id)",
        "provider_message_id": "TEXT",
        "created_at": "TEXT",
    }.items():
        add_column_if_missing(con, "sent_emails", column, definition)

    for column, definition in {
        "campaign_id": "INTEGER REFERENCES campaigns(id)",
        "email_draft_id": "INTEGER REFERENCES email_drafts(id)",
        "raw_reply_text": "TEXT",
        "sentiment": "TEXT",
        "intent": "TEXT DEFAULT 'unknown'",
        "next_action": "TEXT",
        "created_at": "TEXT",
    }.items():
        add_column_if_missing(con, "replies", column, definition)

    cur.executescript(
        """
        UPDATE campaigns
           SET target_count = COALESCE(NULLIF(target_count, 10), target),
               status = COALESCE(status, 'draft'),
               language = COALESCE(language, 'en'),
               daily_send_limit = COALESCE(daily_send_limit, 25),
               approval_required = COALESCE(approval_required, 1)
         WHERE target IS NOT NULL;

        UPDATE leads
           SET business_name = COALESCE(business_name, name),
               website_url = COALESCE(website_url, url),
               description = COALESCE(description, context),
               source_url = COALESCE(source_url, url),
               status = CASE WHEN status = 'found' THEN 'new' ELSE COALESCE(status, 'new') END;

        UPDATE sent_emails
           SET campaign_id = (
                SELECT campaign_id FROM leads WHERE leads.id = sent_emails.lead_id
           )
         WHERE campaign_id IS NULL;

        UPDATE replies
           SET campaign_id = (
                SELECT campaign_id FROM leads WHERE leads.id = replies.lead_id
           ),
               raw_reply_text = COALESCE(raw_reply_text, snippet),
               intent = COALESCE(intent, 'unknown')
         WHERE campaign_id IS NULL OR raw_reply_text IS NULL OR intent IS NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS ux_leads_email
            ON leads(email) WHERE email IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ix_leads_campaign
            ON leads(campaign_id);

        CREATE INDEX IF NOT EXISTS ix_leads_domain
            ON leads(website_url);

        CREATE INDEX IF NOT EXISTS ix_drafts_campaign
            ON email_drafts(campaign_id);

        CREATE INDEX IF NOT EXISTS ix_drafts_lead
            ON email_drafts(lead_id);

        CREATE INDEX IF NOT EXISTS ix_sent_to_email
            ON sent_emails(to_email);

        CREATE UNIQUE INDEX IF NOT EXISTS ux_suppression_email
            ON suppression_list(email) WHERE email IS NOT NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS ux_suppression_domain
            ON suppression_list(domain) WHERE domain IS NOT NULL;
        """
    )

    con.commit()
    con.close()
    print(f"DB ready: {db_path or get_db_path()}")


if __name__ == "__main__":
    init(get_db_path())
