"""HTTP MCP backend for provider-owned search, SMTP, and IMAP access.

Run this process separately from the agent backend. It is the only backend that
should receive provider credentials in its environment.
"""
from __future__ import annotations

import argparse
import email as email_lib
import json
import os
import re
import smtplib
import sys
import traceback
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp_servers"))

from common_mcp import tool_schema


EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PLACEHOLDER_RE = re.compile(r"^\[.*\]$")
BLOCKED_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "yelp.com",
    "tripadvisor.com",
    "zomato.com",
    "google.com",
    "maps.google.com",
    "foursquare.com",
    "opentable.com",
}


def is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    return bool(PLACEHOLDER_RE.match(value.strip()))


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    cleaned = email.strip().lower()
    return cleaned if EMAIL_RE.fullmatch(cleaned) else None


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def classify_reply(text: str | None) -> tuple[str, str]:
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


def configured(keys: tuple[str, ...]) -> dict:
    return {key: bool(os.environ.get(key)) for key in keys}


def require_env(keys: tuple[str, ...]) -> dict:
    values = {}
    missing = []
    for key in keys:
        value = os.environ.get(key)
        if not value:
            missing.append(key)
        values[key] = value
    if missing:
        raise ValueError(f"missing provider environment variables: {', '.join(missing)}")
    return values


def request_json(url: str, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def is_blocked(url: str) -> bool:
    domain = domain_from_url(url) or ""
    return any(domain == blocked or domain.endswith("." + blocked) for blocked in BLOCKED_DOMAINS)


def build_queries(niche: str, location: str) -> list[str]:
    return [
        f"{niche} {location} official website",
        f"{niche} {location} contact email",
        f"best {niche} in {location}",
        f"{niche} near {location} website",
    ]


def serpapi_search(query: str, limit: int) -> list[dict]:
    cfg = require_env(("SERPAPI_API_KEY",))
    params = urllib.parse.urlencode({"engine": "google", "q": query, "api_key": cfg["SERPAPI_API_KEY"], "num": limit})
    data = request_json(f"https://serpapi.com/search.json?{params}")
    return [
        {"title": item.get("title"), "url": item.get("link"), "snippet": item.get("snippet"), "provider": "serpapi"}
        for item in data.get("organic_results", [])
        if item.get("link")
    ]


def bing_search(query: str, limit: int) -> list[dict]:
    cfg = require_env(("BING_SEARCH_API_KEY",))
    params = urllib.parse.urlencode({"q": query, "count": limit})
    data = request_json(
        f"https://api.bing.microsoft.com/v7.0/search?{params}",
        headers={"Ocp-Apim-Subscription-Key": cfg["BING_SEARCH_API_KEY"]},
    )
    return [
        {"title": item.get("name"), "url": item.get("url"), "snippet": item.get("snippet"), "provider": "bing"}
        for item in data.get("webPages", {}).get("value", [])
        if item.get("url")
    ]


def discover_candidates(arguments: dict) -> dict:
    niche = str(arguments["niche"])
    location = str(arguments["location"])
    count = max(1, int(arguments.get("count") or 20))
    queries = build_queries(niche, location)
    results = []
    errors = []
    seen_domains = set()
    serpapi_configured = bool(os.environ.get("SERPAPI_API_KEY"))
    bing_configured = bool(os.environ.get("BING_SEARCH_API_KEY"))

    for query in queries:
        provider_results = []
        if serpapi_configured:
            try:
                provider_results = serpapi_search(query, count)
            except Exception as exc:
                errors.append({"provider": "serpapi", "query": query, "error": str(exc)})
        if not provider_results and bing_configured:
            try:
                provider_results = bing_search(query, count)
            except Exception as exc:
                errors.append({"provider": "bing", "query": query, "error": str(exc)})
        for item in provider_results:
            url = item["url"]
            domain = domain_from_url(url)
            if not domain or is_blocked(url) or domain in seen_domains:
                continue
            seen_domains.add(domain)
            item["query"] = query
            item["domain"] = domain
            results.append(item)
            if len(results) >= count:
                break
        if len(results) >= count:
            break

    return {
        "queries": queries,
        "provider_configured": serpapi_configured or bing_configured,
        "results": results,
        "errors": errors,
    }


def send_email(arguments: dict) -> dict:
    cfg = require_env(("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS"))
    to_email = normalize_email(arguments.get("to_email"))
    if not to_email:
        raise ValueError(f"invalid recipient email: {arguments.get('to_email')}")

    body = str(arguments.get("body") or "")
    signature = str(arguments.get("signature") or "").strip()
    full_body = f"{body}\n\n--\n{signature}" if signature else body
    subject = str(arguments.get("subject") or "")
    message_id = make_msgid(domain=cfg["SMTP_USER"].split("@")[-1])
    from_name = arguments.get("from_name") if not is_placeholder(arguments.get("from_name")) else None
    reply_to = arguments.get("reply_to") if not is_placeholder(arguments.get("reply_to")) else None

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{from_name or cfg['SMTP_USER']} <{cfg['SMTP_USER']}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = reply_to or cfg["SMTP_USER"]
    msg["Message-ID"] = message_id
    msg.attach(MIMEText(full_body, "plain"))

    with smtplib.SMTP(cfg["SMTP_HOST"], int(cfg["SMTP_PORT"])) as server:
        server.ehlo()
        server.starttls()
        server.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
        server.sendmail(cfg["SMTP_USER"], to_email, msg.as_string())

    return {"ok": True, "to_email": to_email, "provider_message_id": message_id}


def check_replies(arguments: dict) -> dict:
    cfg = require_env(("IMAP_HOST", "IMAP_PORT", "IMAP_USER", "IMAP_PASS"))
    sent_rows = arguments.get("sent") or []
    limit = max(1, int(arguments.get("limit") or 200))
    sent = {}
    for row in sent_rows:
        to_email = normalize_email(row.get("to_email"))
        if to_email:
            sent[to_email] = row
    if not sent:
        return {"ok": True, "replies": []}

    replies = []
    mail = None
    try:
        import imaplib

        mail = imaplib.IMAP4_SSL(cfg["IMAP_HOST"], int(cfg["IMAP_PORT"]))
        mail.login(cfg["IMAP_USER"], cfg["IMAP_PASS"])
        mail.select("INBOX")
        _, data = mail.search(None, "ALL")
        ids = data[0].split()[-limit:]

        for eid in ids:
            _, msg_data = mail.fetch(eid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw_msg = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw_msg)
            from_addr = normalize_email(email_lib.utils.parseaddr(msg["From"])[1])
            if not from_addr or from_addr not in sent:
                continue

            subject = msg.get("Subject", "")
            received_at = msg.get("Date", "")
            snippet = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        snippet = part.get_payload(decode=True).decode(errors="replace")
                        break
            else:
                payload = msg.get_payload(decode=True)
                snippet = payload.decode(errors="replace") if payload else ""

            sentiment, intent = classify_reply(snippet)
            sent_row = sent[from_addr]
            replies.append(
                {
                    "campaign_id": sent_row.get("campaign_id"),
                    "lead_id": sent_row.get("lead_id"),
                    "email_draft_id": sent_row.get("email_draft_id"),
                    "from_email": from_addr,
                    "subject": subject,
                    "snippet": snippet.strip()[:200],
                    "raw_reply_text": snippet.strip(),
                    "sentiment": sentiment,
                    "intent": intent,
                    "received_at": received_at,
                }
            )
    finally:
        if mail is not None:
            mail.logout()

    return {"ok": True, "replies": replies}


def provider_status(_: dict | None = None) -> dict:
    return {
        "search": configured(("SERPAPI_API_KEY", "BING_SEARCH_API_KEY")),
        "smtp": configured(("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS")),
        "imap": configured(("IMAP_HOST", "IMAP_PORT", "IMAP_USER", "IMAP_PASS")),
    }


TOOLS = [
    tool_schema(
        "provider_status",
        "Report configured provider credentials without revealing values.",
        {},
    ),
    tool_schema(
        "discover_candidates",
        "Search approved providers for candidate business websites.",
        {
            "niche": {"type": "string"},
            "location": {"type": "string"},
            "count": {"type": "integer", "minimum": 1},
        },
        required=["niche", "location", "count"],
    ),
    tool_schema(
        "send_email",
        "Send one plaintext email through provider-owned SMTP credentials.",
        {
            "to_email": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "from_name": {"type": "string"},
            "reply_to": {"type": "string"},
            "signature": {"type": "string"},
        },
        required=["to_email", "subject", "body"],
    ),
    tool_schema(
        "check_replies",
        "Poll provider-owned IMAP credentials and return replies matching supplied sent emails.",
        {
            "sent": {"type": "array", "items": {"type": "object"}},
            "limit": {"type": "integer", "minimum": 1},
        },
        required=["sent"],
    ),
]

HANDLERS = {
    "provider_status": provider_status,
    "discover_candidates": discover_candidates,
    "send_email": send_email,
    "check_replies": check_replies,
}


def mcp_response(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def handle_mcp_message(message: dict) -> dict | None:
    request_id = message.get("id")
    method = message.get("method")
    if method == "initialize":
        return mcp_response(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "outreach-provider", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return mcp_response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        if name not in HANDLERS:
            raise ValueError(f"unknown tool: {name}")
        output = HANDLERS[name](params.get("arguments") or {})
        return mcp_response(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(output, indent=2, sort_keys=True)}],
                "structuredContent": output,
            },
        )
    raise ValueError(f"unsupported method: {method}")


class ProviderHandler(BaseHTTPRequestHandler):
    server_version = "OutreachProviderMCP/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in {"/health", "/api/health"}:
            self.send_json({"ok": True, "provider": provider_status({})})
            return
        if self.path == "/mcp":
            self.send_json({"tools": TOOLS})
            return
        self.send_json({"error": "not found"}, status=404)

    def do_POST(self):
        if self.path != "/mcp":
            self.send_json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            message = json.loads(raw or "{}")
            response = handle_mcp_message(message)
            if response is None:
                self.send_json({"ok": True})
            else:
                self.send_json(response)
        except Exception as exc:
            self.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32000, "message": str(exc), "data": traceback.format_exc()},
                },
                status=500,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the provider MCP HTTP backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), ProviderHandler)
    print(f"Provider MCP server running at http://{args.host}:{args.port}/mcp")
    server.serve_forever()


if __name__ == "__main__":
    main()
