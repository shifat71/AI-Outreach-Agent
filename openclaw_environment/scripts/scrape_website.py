"""Fetch a business website and likely contact/about pages."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse

from extract_contact import extract_contact, fetch_url


COMMON_PATHS = ["/contact", "/contact-us", "/about", "/about-us"]


def same_origin_url(base_url: str, path: str) -> str:
    parsed = urllib.parse.urlparse(base_url if "://" in base_url else f"https://{base_url}")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def fetch_with_optional_rendering(url: str) -> str:
    try:
        return fetch_url(url)
    except Exception as static_exc:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            raise static_exc

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
            browser.close()
            return html


def scrape(url: str, max_pages: int) -> dict:
    start_url = url if "://" in url else f"https://{url}"
    pages = []
    errors = []
    candidates = [start_url]

    try:
        html = fetch_with_optional_rendering(start_url)
        first = extract_contact(html, start_url)
        pages.append(first)
        candidates.extend(first["contact_links"])
    except Exception as exc:
        errors.append({"url": start_url, "error": str(exc)})

    candidates.extend(same_origin_url(start_url, path) for path in COMMON_PATHS)

    seen = {start_url}
    for candidate in candidates:
        if candidate in seen or len(pages) >= max_pages:
            continue
        seen.add(candidate)
        try:
            html = fetch_with_optional_rendering(candidate)
            pages.append(extract_contact(html, candidate))
        except Exception as exc:
            errors.append({"url": candidate, "error": str(exc)})

    emails = []
    contact_pages = []
    business_name = ""
    description = ""
    address = ""
    email_source_url = None
    for page in pages:
        if not business_name and page.get("business_name"):
            business_name = page["business_name"]
        if not description and page.get("description"):
            description = page["description"]
        if not address and page.get("address"):
            address = page["address"]
        for email in page.get("emails", []):
            if email not in emails:
                emails.append(email)
                if not email_source_url:
                    email_source_url = page.get("email_source_url") or page["url"]
        if page["url"] != start_url and any(token in page["url"].lower() for token in ("contact", "about")):
            contact_pages.append(page["url"])

    return {
        "url": start_url,
        "business_name": business_name,
        "emails": emails,
        "email_source_url": email_source_url,
        "contact_page_url": contact_pages[0] if contact_pages else None,
        "address": address,
        "description": description,
        "pages_checked": [page["url"] for page in pages],
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape a business website for public contact data")
    parser.add_argument("--url", required=True)
    parser.add_argument("--max-pages", type=int, default=4)
    args = parser.parse_args()

    result = scrape(args.url, args.max_pages)
    if not result["pages_checked"]:
        print(json.dumps(result, indent=2, sort_keys=True))
        sys.exit(1)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
