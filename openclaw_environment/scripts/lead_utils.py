"""Lead scoring, draft generation, and compliance helpers."""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping

from common import domain_from_email, domain_from_url, is_placeholder, normalize_email


IGNORED_EMAIL_PARTS = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "sentry",
    "mailchimp",
}

OPT_OUT_TERMS = [
    "reply \"no\"",
    "reply 'no'",
    "reply no",
    "not follow up",
    "unsubscribe",
    "opt out",
    "remove you",
    "remove me",
]

CTA_TERMS = [
    "reply",
    "book",
    "schedule",
    "call",
    "would you",
    "are you open",
    "interested",
]

DECEPTIVE_TERMS = [
    "guaranteed",
    "guarantee",
    "risk-free",
    "last chance",
    "urgent",
    "act now",
    "limited time",
    "100%",
]


def row_to_dict(row: sqlite3.Row | Mapping | None) -> dict:
    if row is None:
        return {}
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return dict(row)


def clean_words(value: str | None) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(w) > 2]


def is_ignored_email(email: str | None) -> bool:
    normalized = normalize_email(email)
    if not normalized:
        return True
    return any(part in normalized for part in IGNORED_EMAIL_PARTS)


def is_suppressed(con: sqlite3.Connection, email: str | None, website_url: str | None = None) -> tuple[bool, str | None]:
    normalized = normalize_email(email)
    domain = domain_from_email(normalized) or domain_from_url(website_url)

    if normalized:
        row = con.execute("SELECT reason FROM suppression_list WHERE email=?", (normalized,)).fetchone()
        if row:
            return True, row["reason"] or "email is suppressed"

    if domain:
        row = con.execute("SELECT reason FROM suppression_list WHERE domain=?", (domain,)).fetchone()
        if row:
            return True, row["reason"] or "domain is suppressed"

    return False, None


def duplicate_penalty(
    con: sqlite3.Connection,
    email: str | None,
    website_url: str | None,
    lead_id: int | None = None,
) -> tuple[int, list[str]]:
    reasons = []
    penalty = 0
    normalized = normalize_email(email)
    domain = domain_from_url(website_url)

    if normalized:
        params = [normalized]
        query = "SELECT COUNT(*) AS n FROM leads WHERE lower(email)=?"
        if lead_id:
            query += " AND id<>?"
            params.append(lead_id)
        if con.execute(query, params).fetchone()["n"] > 0:
            penalty -= 50
            reasons.append("duplicate email")

        if con.execute("SELECT COUNT(*) AS n FROM sent_emails WHERE lower(to_email)=?", (normalized,)).fetchone()["n"] > 0:
            penalty -= 50
            reasons.append("email was already contacted")

    if domain:
        params = [f"%{domain}%"]
        query = "SELECT COUNT(*) AS n FROM leads WHERE lower(COALESCE(website_url, url, '')) LIKE ?"
        if lead_id:
            query += " AND id<>?"
            params.append(lead_id)
        if con.execute(query, params).fetchone()["n"] > 0:
            penalty -= 50
            reasons.append("duplicate domain")

    return penalty, reasons


def score_lead(
    con: sqlite3.Connection,
    lead: Mapping,
    campaign: Mapping,
    threshold: int = 60,
) -> tuple[int, str, list[str]]:
    lead = row_to_dict(lead)
    campaign = row_to_dict(campaign)

    niche = campaign.get("niche") or ""
    location = campaign.get("location") or ""
    business_name = lead.get("business_name") or lead.get("name") or ""
    website_url = lead.get("website_url") or lead.get("url") or ""
    email = lead.get("email")
    contact_page_url = lead.get("contact_page_url")
    description = lead.get("description") or lead.get("context") or ""
    lead_location = lead.get("location") or ""

    haystack = " ".join([business_name, website_url, description, lead_location]).lower()
    score = 0
    reasons = []

    niche_words = clean_words(niche)
    if niche_words and any(word in haystack for word in niche_words):
        score += 30
        reasons.append("niche match")

    location_words = clean_words(location)
    if location_words and any(word in haystack for word in location_words):
        score += 20
        reasons.append("location match")

    if website_url and (business_name or description):
        score += 20
        reasons.append("real business signal")

    if normalize_email(email) and not is_ignored_email(email):
        score += 15
        reasons.append("public email present")

    if contact_page_url:
        score += 5
        reasons.append("contact page present")

    suppressed, suppression_reason = is_suppressed(con, email, website_url)
    if suppressed:
        score -= 50
        reasons.append(suppression_reason or "suppressed")

    penalty, duplicate_reasons = duplicate_penalty(con, email, website_url, lead.get("id"))
    score += penalty
    reasons.extend(duplicate_reasons)

    score = max(0, min(100, score))
    if score < threshold:
        status = "rejected"
    elif not normalize_email(email):
        status = "contact_form_only"
    else:
        status = "new"
    return score, status, reasons


def has_opt_out(body: str | None) -> bool:
    text = (body or "").lower()
    return any(term in text for term in OPT_OUT_TERMS)


def contains_deceptive_terms(text: str | None) -> list[str]:
    lowered = (text or "").lower()
    return [term for term in DECEPTIVE_TERMS if term in lowered]


def draft_word_count(body: str | None) -> int:
    return len(re.findall(r"\b\w+\b", body or ""))


def compliance_check(
    con: sqlite3.Connection,
    lead: Mapping,
    subject: str,
    body: str,
    check_daily_limit: bool = False,
) -> tuple[str, str]:
    lead = row_to_dict(lead)
    reasons = []

    email = normalize_email(lead.get("email"))
    website_url = lead.get("website_url") or lead.get("url")
    source_url = lead.get("source_url") or website_url
    campaign_id = lead.get("campaign_id")

    if not source_url:
        reasons.append("missing contact source URL")
    if not email:
        reasons.append("missing valid recipient email")
    elif is_ignored_email(email):
        reasons.append("recipient email is not suitable for outreach")

    suppressed, suppression_reason = is_suppressed(con, email, website_url)
    if suppressed:
        reasons.append(suppression_reason or "recipient is suppressed")

    if not has_opt_out(body):
        reasons.append("missing opt-out line")

    deceptive = contains_deceptive_terms(" ".join([subject or "", body or ""]))
    if deceptive:
        reasons.append("contains risky claim or urgency term: " + ", ".join(sorted(set(deceptive))))

    if (subject or "").strip().lower().startswith(("re:", "fwd:")):
        reasons.append("subject implies a prior conversation")

    words = draft_word_count(body)
    if words < 80:
        reasons.append("draft is below the required 80-word minimum")
    if words > 140:
        reasons.append("draft exceeds the required 140-word maximum")
    if "?" not in body and not any(term in (body or "").lower() for term in CTA_TERMS):
        reasons.append("draft is missing a simple call to action")
    if (body or "").count("?") > 1:
        reasons.append("draft appears to contain more than one call to action")

    business_name = (lead.get("business_name") or lead.get("name") or "").lower()
    description = (lead.get("description") or lead.get("context") or "").lower()
    lower_body = (body or "").lower()
    if business_name and business_name not in lower_body and not any(word in lower_body for word in clean_words(description)[:5]):
        reasons.append("draft lacks a clear business-specific reference")

    if check_daily_limit and campaign_id:
        campaign = con.execute(
            "SELECT daily_send_limit FROM campaigns WHERE id=?", (campaign_id,)
        ).fetchone()
        limit = campaign["daily_send_limit"] if campaign else 25
        sent_today = con.execute(
            """
            SELECT COUNT(*) AS n
              FROM sent_emails
             WHERE campaign_id=?
               AND status='success'
               AND date(sent_at)=date('now')
            """,
            (campaign_id,),
        ).fetchone()["n"]
        if sent_today >= limit:
            reasons.append(f"daily send limit reached ({sent_today}/{limit})")

    if reasons:
        return "failed", "; ".join(reasons)
    return "passed", "ok"


def generate_subject(lead: Mapping, campaign: Mapping) -> str:
    lead = row_to_dict(lead)
    campaign = row_to_dict(campaign)
    name = lead.get("business_name") or lead.get("name") or "your team"
    location = lead.get("location") or campaign.get("location") or ""
    if location:
        return f"Idea for {name} in {location}".strip()[:70]
    return f"Idea for {name}".strip()[:70]


def generate_email_body(lead: Mapping, campaign: Mapping, config: Mapping) -> str:
    lead = row_to_dict(lead)
    campaign = row_to_dict(campaign)

    name = lead.get("business_name") or lead.get("name") or "your team"
    description = lead.get("description") or lead.get("context") or "what you offer"
    configured_offer = config.get("Service")
    configured_cta = config.get("CTA")
    configured_sender = config.get("Name")
    offer = campaign.get("offer") or (
        configured_offer if not is_placeholder(configured_offer) else None
    ) or "helping local businesses improve their online presence"
    cta = (
        configured_cta if not is_placeholder(configured_cta) else None
    ) or "Would you be open to a quick reply if this is relevant?"
    sender = (configured_sender if not is_placeholder(configured_sender) else None) or "Thanks"

    short_context = " ".join(description.split())[:180].rstrip(" .")

    return (
        f"Hi {name} team,\n\n"
        f"I noticed {short_context}. That gave me a real sense of what people can expect from your business.\n\n"
        f"I help businesses with {offer}. For a team like yours, a concise marketing asset or outreach message can make that first impression clearer without adding more work for you.\n\n"
        f"{cta} If this is not relevant, reply \"no\" and I will not follow up.\n\n"
        f"{sender}"
    )
