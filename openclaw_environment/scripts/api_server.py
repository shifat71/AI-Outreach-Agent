"""Agent backend and REST API for the outreach workflow.

This dependency-light server is intended for local operation. It exposes the
same database workflow as the CLI: campaigns, leads, scoring, drafts, approval,
suppression, summaries, and dry-run sending checks. Provider integrations are
delegated to the separate provider MCP backend.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from urllib.parse import parse_qs, urlparse

from common import classify_reply, connect, default_offer, normalize_email, now_iso, parse_user_md, positive_int
from lead_utils import (
    compliance_check,
    generate_email_body,
    generate_subject,
    is_suppressed,
    score_lead,
)
from provider_client import ProviderError, provider_status
from scrape_website import scrape
from search_leads import search


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD_PATH = os.path.join(ROOT_DIR, "dashboard", "index.html")
EXECUTOR = ThreadPoolExecutor(max_workers=2)
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def dict_rows(rows):
    return [dict(row) for row in rows]


def campaign_summary(con, campaign_id: int | None = None) -> dict:
    params = []
    where = "WHERE 1=1"
    if campaign_id:
        where += " AND campaign_id=?"
        params.append(campaign_id)

    def count(query, values=()):
        return con.execute(query, values).fetchone()["n"]

    return {
        "businesses_found": count(f"SELECT COUNT(*) AS n FROM leads {where}", params),
        "emails_extracted": count(f"SELECT COUNT(*) AS n FROM leads {where} AND email IS NOT NULL", params),
        "contact_form_only": count(f"SELECT COUNT(*) AS n FROM leads {where} AND status='contact_form_only'", params),
        "approved_drafts": count(
            "SELECT COUNT(*) AS n FROM email_drafts WHERE (? IS NULL OR campaign_id=?) AND status='approved'",
            (campaign_id, campaign_id),
        ),
        "emails_sent": count(
            "SELECT COUNT(*) AS n FROM sent_emails WHERE (? IS NULL OR campaign_id=?) AND status='success'",
            (campaign_id, campaign_id),
        ),
        "failures": count(
            "SELECT COUNT(*) AS n FROM sent_emails WHERE (? IS NULL OR campaign_id=?) AND status='failed'",
            (campaign_id, campaign_id),
        ),
        "replies": count(
            "SELECT COUNT(*) AS n FROM replies WHERE (? IS NULL OR campaign_id=?)",
            (campaign_id, campaign_id),
        ),
        "opt_outs": count(f"SELECT COUNT(*) AS n FROM leads {where} AND status='opted_out'", params),
    }


def set_job(job_id: str, **updates) -> None:
    with JOBS_LOCK:
        JOBS.setdefault(job_id, {}).update(updates)


def discover_campaign_job(job_id: str, campaign_id: int, count: int | None, score_threshold: int) -> None:
    set_job(job_id, status="running", started_at=now_iso())
    con = connect()
    try:
        campaign = con.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not campaign:
            raise ValueError(f"campaign {campaign_id} not found")
        requested = count or int(campaign["target_count"]) * 2
        search_output = search(campaign["niche"], campaign["location"], requested)
        saved = 0
        failed = []
        for item in search_output["results"]:
            url = item["url"]
            try:
                scraped = scrape(url, 4)
                if not scraped["pages_checked"]:
                    failed.append({"url": url, "error": "unreachable"})
                    continue
                email = scraped["emails"][0] if scraped["emails"] else None
                status = "new" if email else "contact_form_only"
                cur = con.execute(
                    """
                    INSERT INTO leads (
                        campaign_id, name, url, email, context, status,
                        business_name, website_url, contact_page_url, address,
                        location, description, source_url, updated_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        campaign_id,
                        scraped.get("business_name") or item.get("title"),
                        scraped["url"],
                        email,
                        scraped.get("description"),
                        status,
                        scraped.get("business_name") or item.get("title"),
                        scraped["url"],
                        scraped.get("contact_page_url"),
                        scraped.get("address"),
                        campaign["location"],
                        scraped.get("description"),
                        scraped.get("email_source_url") or scraped.get("contact_page_url") or scraped["url"],
                        now_iso(),
                    ),
                )
                lead = con.execute("SELECT * FROM leads WHERE id=?", (cur.lastrowid,)).fetchone()
                score, lead_status, reasons = score_lead(con, lead, campaign, score_threshold)
                con.execute(
                    """
                    UPDATE leads
                       SET fit_score=?, status=?, rejection_reason=?, updated_at=?
                     WHERE id=?
                    """,
                    (score, lead_status, "; ".join(reasons) if lead_status == "rejected" else None, now_iso(), cur.lastrowid),
                )
                con.commit()
                saved += 1
                set_job(job_id, saved=saved)
            except Exception as exc:
                con.rollback()
                failed.append({"url": url, "error": str(exc)})
        set_job(
            job_id,
            status="completed",
            finished_at=now_iso(),
            provider_configured=search_output["provider_configured"],
            queries=search_output["queries"],
            search_errors=search_output["errors"],
            candidates=len(search_output["results"]),
            saved=saved,
            failures=failed,
        )
    except Exception as exc:
        set_job(job_id, status="failed", finished_at=now_iso(), error=str(exc))
    finally:
        con.close()


class OutreachHandler(BaseHTTPRequestHandler):
    server_version = "OutreachAgent/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_csv(self, filename: str, csv_text: str, status=200):
        body = csv_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def handle_error(self, exc: Exception):
        status = 400 if isinstance(exc, (ValueError, KeyError)) else 500
        self.send_json({"error": str(exc)}, status=status)

    def do_GET(self):
        try:
            self.route_get()
        except Exception as exc:
            self.handle_error(exc)

    def do_POST(self):
        try:
            self.route_post()
        except Exception as exc:
            self.handle_error(exc)

    def route_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in {"/", "/dashboard"}:
            with open(DASHBOARD_PATH, encoding="utf-8") as f:
                self.send_html(f.read())
            return

        if path == "/api/health":
            self.send_json({"ok": True})
            return

        if path == "/api/provider/status":
            try:
                self.send_json({"provider": provider_status()})
            except ProviderError as exc:
                self.send_json({"error": str(exc)}, status=503)
            return

        match = re.fullmatch(r"/api/jobs/([a-f0-9-]+)", path)
        if match:
            with JOBS_LOCK:
                job = dict(JOBS.get(match.group(1), {}))
            if not job:
                self.send_json({"error": "job not found"}, status=404)
                return
            self.send_json({"job": job})
            return

        con = connect()
        try:
            if path == "/api/campaigns":
                rows = con.execute(
                    """
                    SELECT id, niche, location, target_count, offer, language,
                           approval_required, daily_send_limit, status,
                           created_at, updated_at
                      FROM campaigns
                     ORDER BY created_at DESC, id DESC
                    """
                ).fetchall()
                self.send_json({"campaigns": dict_rows(rows)})
                return

            match = re.fullmatch(r"/api/campaigns/(\d+)/summary", path)
            if match:
                campaign_id = int(match.group(1))
                self.send_json({"summary": campaign_summary(con, campaign_id)})
                return

            match = re.fullmatch(r"/api/campaigns/(\d+)/leads", path)
            if match:
                campaign_id = int(match.group(1))
                rows = con.execute(
                    """
                    SELECT id, business_name, website_url, email, contact_page_url,
                           location, description, fit_score, source_url, status,
                           rejection_reason, created_at, updated_at
                      FROM leads
                     WHERE campaign_id=?
                     ORDER BY fit_score DESC, id DESC
                    """,
                    (campaign_id,),
                ).fetchall()
                self.send_json({"leads": dict_rows(rows)})
                return

            match = re.fullmatch(r"/api/campaigns/(\d+)/drafts", path)
            if match:
                campaign_id = int(match.group(1))
                rows = con.execute(
                    """
                    SELECT d.id, d.lead_id, d.subject, d.body, d.status,
                           d.compliance_status, d.compliance_reason,
                           d.provider_message_id, d.sent_at,
                           l.business_name, l.email
                      FROM email_drafts d
                      JOIN leads l ON l.id=d.lead_id
                     WHERE d.campaign_id=?
                     ORDER BY d.created_at DESC, d.id DESC
                    """,
                    (campaign_id,),
                ).fetchall()
                self.send_json({"drafts": dict_rows(rows)})
                return

            match = re.fullmatch(r"/api/campaigns/(\d+)/replies", path)
            if match:
                campaign_id = int(match.group(1))
                rows = con.execute(
                    """
                    SELECT r.id, r.lead_id, r.email_draft_id, r.from_email,
                           r.subject, r.snippet, r.raw_reply_text, r.sentiment,
                           r.intent, r.next_action, r.received_at, r.created_at,
                           l.business_name
                      FROM replies r
                      JOIN leads l ON l.id=r.lead_id
                     WHERE r.campaign_id=?
                     ORDER BY COALESCE(r.received_at, r.created_at) DESC, r.id DESC
                    """,
                    (campaign_id,),
                ).fetchall()
                intent_rows = con.execute(
                    """
                    SELECT COALESCE(intent, 'unknown') AS intent, COUNT(*) AS n
                      FROM replies
                     WHERE campaign_id=?
                     GROUP BY COALESCE(intent, 'unknown')
                    """,
                    (campaign_id,),
                ).fetchall()
                self.send_json({"replies": dict_rows(rows), "intent_counts": dict_rows(intent_rows)})
                return

            match = re.fullmatch(r"/api/campaigns/(\d+)/export", path)
            if match:
                campaign_id = int(match.group(1))
                rows = con.execute(
                    """
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
                    WHERE l.campaign_id=?
                    ORDER BY l.id
                    """,
                    (campaign_id,),
                ).fetchall()
                fieldnames = list(rows[0].keys()) if rows else [
                    "campaign_id", "niche", "campaign_location", "business_name",
                    "website_url", "email", "contact_page_url", "address",
                    "lead_location", "description", "fit_score", "source_url",
                    "lead_status", "rejection_reason", "draft_id", "draft_status",
                    "compliance_status", "subject", "send_status", "sent_at",
                    "reply_intent", "reply_received_at",
                ]
                output = StringIO()
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow(dict(row))
                self.send_csv(f"campaign_{campaign_id}.csv", output.getvalue())
                return

            if path == "/api/suppression":
                limit = int(query.get("limit", ["100"])[0])
                rows = con.execute(
                    """
                    SELECT id, email, domain, reason, source, created_at
                      FROM suppression_list
                     ORDER BY created_at DESC, id DESC
                     LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                self.send_json({"suppression": dict_rows(rows)})
                return
        finally:
            con.close()

        self.send_json({"error": "not found"}, status=404)

    def route_post(self):
        path = urlparse(self.path).path
        data = self.read_json()
        con = connect()
        try:
            if path == "/api/campaigns":
                target = positive_int(data.get("target_count"), 10, "target_count")
                daily_send_limit = positive_int(data.get("daily_send_limit"), 25, "daily_send_limit")
                cur = con.execute(
                    """
                    INSERT INTO campaigns (
                        niche, location, target, target_count, offer, language,
                        approval_required, daily_send_limit, status, updated_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        data["niche"],
                        data["location"],
                        target,
                        target,
                        data.get("offer") or default_offer(),
                        data.get("language") or "en",
                        1 if data.get("approval_required", True) else 0,
                        daily_send_limit,
                        "draft",
                        now_iso(),
                    ),
                )
                con.commit()
                self.send_json({"campaign_id": cur.lastrowid}, status=201)
                return

            match = re.fullmatch(r"/api/campaigns/(\d+)/discover", path)
            if match:
                campaign_id = int(match.group(1))
                count = positive_int(data.get("count"), 0, "count") if data.get("count") else None
                threshold = positive_int(data.get("threshold"), 60, "threshold")
                if not con.execute("SELECT id FROM campaigns WHERE id=?", (campaign_id,)).fetchone():
                    self.send_json({"error": "campaign not found"}, status=404)
                    return
                job_id = str(uuid.uuid4())
                with JOBS_LOCK:
                    JOBS[job_id] = {
                        "id": job_id,
                        "type": "discover",
                        "campaign_id": campaign_id,
                        "status": "queued",
                        "created_at": now_iso(),
                        "saved": 0,
                    }
                EXECUTOR.submit(discover_campaign_job, job_id, campaign_id, count, threshold)
                self.send_json({"job_id": job_id}, status=202)
                return

            match = re.fullmatch(r"/api/campaigns/(\d+)/leads", path)
            if match:
                campaign_id = int(match.group(1))
                email = normalize_email(data.get("email")) if data.get("email") else None
                status = data.get("status") or ("new" if email else "contact_form_only")
                cur = con.execute(
                    """
                    INSERT INTO leads (
                        campaign_id, name, url, email, context, status,
                        business_name, website_url, contact_page_url,
                        address, location, description, source_url, updated_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        campaign_id,
                        data.get("business_name"),
                        data["website_url"],
                        email,
                        data.get("description"),
                        status,
                        data.get("business_name"),
                        data["website_url"],
                        data.get("contact_page_url"),
                        data.get("address"),
                        data.get("location"),
                        data.get("description"),
                        data.get("source_url") or data.get("contact_page_url") or data["website_url"],
                        now_iso(),
                    ),
                )
                con.commit()
                self.send_json({"lead_id": cur.lastrowid}, status=201)
                return

            match = re.fullmatch(r"/api/leads/(\d+)/score", path)
            if match:
                lead_id = int(match.group(1))
                lead = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
                if not lead:
                    self.send_json({"error": "lead not found"}, status=404)
                    return
                campaign = con.execute("SELECT * FROM campaigns WHERE id=?", (lead["campaign_id"],)).fetchone()
                score, status, reasons = score_lead(con, lead, campaign, int(data.get("threshold") or 60))
                con.execute(
                    """
                    UPDATE leads
                       SET fit_score=?, status=?, rejection_reason=?, updated_at=?
                     WHERE id=?
                    """,
                    (score, status, "; ".join(reasons) if status == "rejected" else None, now_iso(), lead_id),
                )
                con.commit()
                self.send_json({"score": score, "status": status, "reasons": reasons})
                return

            match = re.fullmatch(r"/api/leads/(\d+)/drafts", path)
            if match:
                lead_id = int(match.group(1))
                lead = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
                if not lead:
                    self.send_json({"error": "lead not found"}, status=404)
                    return
                campaign = con.execute("SELECT * FROM campaigns WHERE id=?", (lead["campaign_id"],)).fetchone()
                config = parse_user_md()
                subject = data.get("subject") or generate_subject(lead, campaign)
                body = data.get("body") or generate_email_body(lead, campaign, config)
                compliance_status, compliance_reason = compliance_check(con, lead, subject, body)
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
                        lead_id,
                        subject,
                        body,
                        "draft",
                        compliance_status,
                        compliance_reason,
                        now_iso(),
                    ),
                )
                con.commit()
                self.send_json(
                    {
                        "draft_id": cur.lastrowid,
                        "subject": subject,
                        "body": body,
                        "compliance_status": compliance_status,
                        "compliance_reason": compliance_reason,
                    },
                    status=201,
                )
                return

            match = re.fullmatch(r"/api/drafts/(\d+)/approve", path)
            if match:
                self.approve_draft(con, int(match.group(1)))
                return

            match = re.fullmatch(r"/api/drafts/(\d+)", path)
            if match:
                draft_id = int(match.group(1))
                draft = con.execute("SELECT * FROM email_drafts WHERE id=?", (draft_id,)).fetchone()
                if not draft:
                    self.send_json({"error": "draft not found"}, status=404)
                    return
                lead = con.execute("SELECT * FROM leads WHERE id=?", (draft["lead_id"],)).fetchone()
                subject = data.get("subject") or draft["subject"]
                body = data.get("body") or draft["body"]
                compliance_status, compliance_reason = compliance_check(con, lead, subject, body)
                con.execute(
                    """
                    UPDATE email_drafts
                       SET subject=?, body=?, status='draft',
                           compliance_status=?, compliance_reason=?, updated_at=?
                     WHERE id=?
                    """,
                    (subject, body, compliance_status, compliance_reason, now_iso(), draft_id),
                )
                con.execute(
                    "UPDATE leads SET status='draft', updated_at=? WHERE id=? AND status NOT IN ('sent', 'replied', 'opted_out')",
                    (now_iso(), draft["lead_id"]),
                )
                con.commit()
                self.send_json(
                    {
                        "draft_id": draft_id,
                        "subject": subject,
                        "body": body,
                        "compliance_status": compliance_status,
                        "compliance_reason": compliance_reason,
                    }
                )
                return

            match = re.fullmatch(r"/api/drafts/(\d+)/reject", path)
            if match:
                draft_id = int(match.group(1))
                reason = data.get("reason") or "draft rejected"
                draft = con.execute("SELECT lead_id FROM email_drafts WHERE id=?", (draft_id,)).fetchone()
                if not draft:
                    self.send_json({"error": "draft not found"}, status=404)
                    return
                con.execute(
                    "UPDATE email_drafts SET status='rejected', compliance_reason=?, updated_at=? WHERE id=?",
                    (reason, now_iso(), draft_id),
                )
                con.execute(
                    "UPDATE leads SET status='rejected', rejection_reason=?, updated_at=? WHERE id=?",
                    (reason, now_iso(), draft["lead_id"]),
                )
                con.commit()
                self.send_json({"rejected": True})
                return

            match = re.fullmatch(r"/api/drafts/(\d+)/send", path)
            if match:
                draft_id = int(match.group(1))
                dry_run = bool(data.get("dry_run", True))
                cmd = [
                    sys.executable,
                    os.path.join(ROOT_DIR, "scripts", "send_approved_email.py"),
                    "--draft-id",
                    str(draft_id),
                ]
                if dry_run:
                    cmd.append("--dry-run")
                result = subprocess.run(cmd, cwd=ROOT_DIR, text=True, capture_output=True)
                self.send_json(
                    {
                        "ok": result.returncode == 0,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    },
                    status=200 if result.returncode == 0 else 400,
                )
                return

            if path == "/api/suppression":
                email = normalize_email(data.get("email")) if data.get("email") else None
                domain = (data.get("domain") or "").lower().removeprefix("www.") or None
                if not email and not domain:
                    raise ValueError("email or domain is required")
                con.execute(
                    """
                    INSERT OR IGNORE INTO suppression_list (email, domain, reason, source)
                    VALUES (?,?,?,?)
                    """,
                    (email, domain, data.get("reason") or "manual", data.get("source") or "dashboard"),
                )
                if email:
                    con.execute(
                        "UPDATE leads SET status='opted_out', updated_at=? WHERE lower(email)=?",
                        (now_iso(), email),
                    )
                if domain:
                    con.execute(
                        """
                        UPDATE leads
                           SET status='opted_out', updated_at=?
                         WHERE lower(COALESCE(website_url, url, '')) LIKE ?
                        """,
                        (now_iso(), f"%{domain}%"),
                    )
                con.commit()
                self.send_json({"suppressed": True}, status=201)
                return

            if path == "/api/replies":
                lead_id = int(data["lead_id"])
                lead = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
                if not lead:
                    self.send_json({"error": "lead not found"}, status=404)
                    return
                raw = data.get("raw_reply_text") or data.get("snippet") or ""
                sentiment, intent = classify_reply(raw)
                from_email = normalize_email(data.get("from_email")) if data.get("from_email") else None
                cur = con.execute(
                    """
                    INSERT INTO replies (
                        campaign_id, lead_id, email_draft_id, from_email, subject,
                        snippet, raw_reply_text, sentiment, intent, next_action, received_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        lead["campaign_id"],
                        lead_id,
                        data.get("email_draft_id"),
                        from_email,
                        data.get("subject"),
                        raw[:200],
                        raw,
                        sentiment,
                        intent,
                        data.get("next_action"),
                        data.get("received_at") or now_iso(),
                    ),
                )
                if intent == "unsubscribe":
                    con.execute("UPDATE leads SET status='opted_out', updated_at=? WHERE id=?", (now_iso(), lead_id))
                    if from_email:
                        con.execute(
                            """
                            INSERT OR IGNORE INTO suppression_list (email, reason, source)
                            VALUES (?, 'unsubscribe reply', 'reply_api')
                            """,
                            (from_email,),
                        )
                elif intent == "bounce":
                    con.execute("UPDATE leads SET status='failed', updated_at=? WHERE id=?", (now_iso(), lead_id))
                elif intent not in {"auto_reply", "unknown"}:
                    con.execute("UPDATE leads SET status='replied', updated_at=? WHERE id=?", (now_iso(), lead_id))
                con.commit()
                self.send_json(
                    {
                        "reply_id": cur.lastrowid,
                        "intent": intent,
                        "sentiment": sentiment,
                    },
                    status=201,
                )
                return
        finally:
            con.close()

        self.send_json({"error": "not found"}, status=404)

    def approve_draft(self, con, draft_id: int):
        draft = con.execute("SELECT * FROM email_drafts WHERE id=?", (draft_id,)).fetchone()
        if not draft:
            self.send_json({"error": "draft not found"}, status=404)
            return
        lead = con.execute("SELECT * FROM leads WHERE id=?", (draft["lead_id"],)).fetchone()
        status, reason = compliance_check(con, lead, draft["subject"], draft["body"])
        if status != "passed":
            con.execute(
                "UPDATE email_drafts SET compliance_status=?, compliance_reason=?, updated_at=? WHERE id=?",
                (status, reason, now_iso(), draft_id),
            )
            con.commit()
            self.send_json({"approved": False, "reason": reason}, status=400)
            return
        suppressed, suppression_reason = is_suppressed(con, lead["email"], lead["website_url"] or lead["url"])
        if suppressed:
            self.send_json({"approved": False, "reason": suppression_reason}, status=400)
            return
        con.execute(
            """
            UPDATE email_drafts
               SET status='approved', compliance_status='passed',
                   compliance_reason='ok', updated_at=?
             WHERE id=?
            """,
            (now_iso(), draft_id),
        )
        con.execute("UPDATE leads SET status='approved', updated_at=? WHERE id=?", (now_iso(), draft["lead_id"]))
        con.commit()
        self.send_json({"approved": True})


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the outreach agent backend and dashboard/API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), OutreachHandler)
    print(f"Outreach agent backend running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
