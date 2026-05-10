"""Extract public contact details from an HTML document or URL."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from common import extract_emails


class ContactHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.title_parts = []
        self.h1_parts = []
        self.text_parts = []
        self.mailtos = []
        self.links = []
        self.address_parts = []
        self.meta_description = ""
        self._capture_title = False
        self._capture_h1 = False
        self._capture_address = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = {key.lower(): value for key, value in attrs if value}
        if tag == "title":
            self._capture_title = True
        elif tag == "h1":
            self._capture_h1 = True
        elif tag == "address":
            self._capture_address = True
        elif tag == "meta":
            name = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            if name in {"description", "og:description"} and attrs_dict.get("content"):
                self.meta_description = attrs_dict["content"].strip()
        elif tag == "a" and attrs_dict.get("href"):
            href = attrs_dict["href"].strip()
            absolute = urllib.parse.urljoin(self.base_url, href)
            if href.lower().startswith("mailto:"):
                self.mailtos.extend(extract_emails(urllib.parse.unquote(href)))
            else:
                self.links.append(absolute)

    def handle_endtag(self, tag):
        if tag == "title":
            self._capture_title = False
        elif tag == "h1":
            self._capture_h1 = False
        elif tag == "address":
            self._capture_address = False

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self._capture_title:
            self.title_parts.append(text)
        elif self._capture_h1:
            self.h1_parts.append(text)
        elif self._capture_address:
            self.address_parts.append(text)
        self.text_parts.append(text)


def fetch_url(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; OutreachAgent/1.0; public contact extraction)"
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            raise ValueError(f"unsupported content type: {content_type}")
        return response.read().decode("utf-8", errors="replace")


def first_sentences(text: str, limit: int = 2) -> str:
    compact = " ".join(text.split())
    parts = re.split(r"(?<=[.!?])\s+", compact)
    selected = " ".join(parts[:limit]).strip()
    return selected[:320]


def likely_contact_links(links: list[str], base_url: str) -> list[str]:
    base_host = urllib.parse.urlparse(base_url).netloc.lower()
    picked = []
    seen = set()
    for link in links:
        parsed = urllib.parse.urlparse(link)
        if parsed.netloc.lower() != base_host:
            continue
        lowered = parsed.path.lower()
        if any(token in lowered for token in ("contact", "about", "team")) and link not in seen:
            seen.add(link)
            picked.append(link)
    return picked[:8]


def extract_contact(html: str, url: str) -> dict:
    parser = ContactHTMLParser(url)
    parser.feed(html)
    visible_text = " ".join(parser.text_parts)
    emails = []
    for email in parser.mailtos + extract_emails(visible_text):
        if email not in emails:
            emails.append(email)

    title = " ".join(parser.title_parts).strip()
    h1 = " ".join(parser.h1_parts).strip()
    business_name = h1 or title.split("|")[0].split("-")[0].strip()
    description = parser.meta_description or first_sentences(visible_text)
    address = " ".join(parser.address_parts).strip()

    return {
        "url": url,
        "business_name": business_name,
        "emails": emails,
        "email_source_url": url if emails else None,
        "address": address,
        "description": description,
        "contact_links": likely_contact_links(parser.links, url),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract contact details from a page")
    parser.add_argument("--url")
    parser.add_argument("--input-file")
    args = parser.parse_args()

    if not args.url and not args.input_file:
        raise SystemExit("ERROR: provide --url or --input-file")

    try:
        if args.input_file:
            with open(args.input_file, encoding="utf-8") as f:
                html = f.read()
            url = args.url or "file://" + args.input_file
        else:
            url = args.url
            html = fetch_url(url)
        print(json.dumps(extract_contact(html, url), indent=2, sort_keys=True))
    except (urllib.error.URLError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
