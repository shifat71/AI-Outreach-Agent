"""Shared utilities for the outreach agent scripts."""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
USER_MD = os.path.join(ROOT_DIR, "USER.md")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PLACEHOLDER_RE = re.compile(r"^\[.*\]$")
SECRET_CONFIG_KEYS = {
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASS",
    "IMAP_HOST",
    "IMAP_PORT",
    "IMAP_USER",
    "IMAP_PASS",
    "SERPAPI_API_KEY",
    "BING_SEARCH_API_KEY",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_user_md() -> dict:
    config = {}
    try:
        with open(USER_MD, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or ":" not in stripped:
                    continue
                key, value = stripped.split(":", 1)
                key = key.strip()
                if key in SECRET_CONFIG_KEYS:
                    continue
                config[key] = value.strip()
    except FileNotFoundError:
        pass
    return config


def is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    return bool(PLACEHOLDER_RE.match(value.strip()))


def default_offer() -> str | None:
    """Return the configured service offer when USER.md has a real value."""
    offer = parse_user_md().get("Service")
    return offer if offer and not is_placeholder(offer) else None


def positive_int(value: str | int | None, default: int, name: str) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if parsed < 1:
        raise ValueError(f"{name} must be at least 1")
    return parsed


def get_db_path() -> str:
    env_path = os.environ.get("OUTREACH_DB_PATH")
    if env_path:
        return os.path.abspath(env_path)

    config = parse_user_md()
    raw = config.get("DB_PATH")
    if raw and not is_placeholder(raw):
        return os.path.normpath(os.path.join(ROOT_DIR, raw))

    return os.path.join(ROOT_DIR, "campaigns", "outreach.db")


def connect() -> sqlite3.Connection:
    db_path = get_db_path()
    if not os.path.exists(db_path):
        raise SystemExit(f"ERROR: DB not found at {db_path}. Run: python3 scripts/init_db.py")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def connect_or_create() -> sqlite3.Connection:
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    cleaned = email.strip().lower()
    return cleaned if EMAIL_RE.fullmatch(cleaned) else None


def extract_emails(text: str | None) -> list[str]:
    if not text:
        return []
    seen = set()
    emails = []
    for match in EMAIL_RE.findall(text):
        email = normalize_email(match)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    return emails


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def domain_from_email(email: str | None) -> str | None:
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        return None
    return normalized.split("@", 1)[1]


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}


def add_column_if_missing(con: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in table_columns(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def truthy(value: str | bool | int | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def classify_reply(text: str | None) -> tuple[str, str]:
    """Return (sentiment, intent) from simple auditable keyword rules."""
    body = (text or "").lower()
    if not body:
        return "neutral", "unknown"

    unsubscribe_terms = ["unsubscribe", "remove me", "do not contact", "don't contact", "stop emailing"]
    bounce_terms = ["undeliverable", "delivery failed", "mail delivery", "address not found"]
    pricing_terms = ["price", "pricing", "cost", "quote", "rates"]
    meeting_terms = ["book", "schedule", "call", "meeting", "calendar"]
    interested_terms = ["interested", "tell me more", "send more", "sounds good", "yes"]
    not_interested_terms = ["not interested", "no thanks", "no thank", "not relevant", "no need"]
    auto_reply_terms = ["out of office", "automatic reply", "auto-reply", "vacation responder"]

    if any(term in body for term in unsubscribe_terms):
        return "negative", "unsubscribe"
    if any(term in body for term in bounce_terms):
        return "negative", "bounce"
    if any(term in body for term in auto_reply_terms):
        return "neutral", "auto_reply"
    if any(term in body for term in pricing_terms):
        return "positive", "pricing_question"
    if any(term in body for term in meeting_terms):
        return "positive", "meeting_request"
    if any(term in body for term in interested_terms):
        return "positive", "interested"
    if any(term in body for term in not_interested_terms):
        return "negative", "not_interested"
    return "neutral", "unknown"
