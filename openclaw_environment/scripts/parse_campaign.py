"""Parse a natural-language campaign request into structured parameters."""
from __future__ import annotations

import argparse
import json
import re

from common import connect, default_offer, now_iso, positive_int


LANGUAGES = {
    "english": "en",
    "en": "en",
    "spanish": "es",
    "es": "es",
    "french": "fr",
    "fr": "fr",
    "german": "de",
    "de": "de",
    "italian": "it",
    "it": "it",
    "portuguese": "pt",
    "pt": "pt",
}


def parse_target_count(prompt: str) -> int:
    match = re.search(r"\b(?:find|get|collect|source|discover|write|contact)\s+(\d{1,4})\b", prompt, re.I)
    if match:
        return positive_int(match.group(1), 10, "target_count")
    match = re.search(r"\b(\d{1,4})\s+(?:leads|emails|businesses|prospects)\b", prompt, re.I)
    if match:
        return positive_int(match.group(1), 10, "target_count")
    return 10


def parse_language(prompt: str) -> str:
    match = re.search(r"\b(?:in|language:?)\s+(english|spanish|french|german|italian|portuguese|en|es|fr|de|it|pt)\b", prompt, re.I)
    if not match:
        return "en"
    return LANGUAGES[match.group(1).lower()]


def parse_offer(prompt: str) -> str | None:
    patterns = [
        r"\boffering\s+(?:my|our|a|an|the)?\s*(?P<offer>.+?)(?:[.!?]|$)",
        r"\bfor\s+(?:my|our|a|an|the)?\s*(?P<offer>[^.!?]+?\bservice)\b",
        r"\bto promote\s+(?:my|our|a|an|the)?\s*(?P<offer>.+?)(?:[.!?]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, prompt, re.I)
        if match:
            offer = re.sub(r"\s+", " ", match.group("offer")).strip(" ,")
            if offer:
                return offer
    return default_offer()


def parse_niche_location(prompt: str, target_count: int) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", prompt).strip()
    count_prefix = rf"(?:{target_count}\s+)?"
    patterns = [
        rf"\b(?:find|get|collect|source|discover|contact)\s+{count_prefix}(?P<niche>.+?)\s+(?:in|near|around|from)\s+(?P<location>.+?)(?:\s+(?:and|to|for|offering|with|who|that)\b|[.!?]|$)",
        rf"\b(?P<niche>.+?)\s+(?:in|near|around|from)\s+(?P<location>.+?)(?:\s+(?:and|to|for|offering|with|who|that)\b|[.!?]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.I)
        if match:
            niche = match.group("niche").strip(" ,")
            location = match.group("location").strip(" ,")
            niche = re.sub(r"^(?:approved\s+emails?\s+for|leads?\s+for)\s+", "", niche, flags=re.I)
            if niche and location:
                return niche, location
    raise ValueError("could not parse niche and location from prompt")


def parse_daily_limit(prompt: str) -> int:
    match = re.search(r"\b(?:daily\s+send\s+limit|daily\s+limit|limit)\s*(?:of|to|:)?\s*(\d{1,3})\b", prompt, re.I)
    if match:
        return positive_int(match.group(1), 25, "daily_send_limit")
    match = re.search(r"\b(\d{1,3})\s+(?:emails?\s+)?per\s+day\b", prompt, re.I)
    if match:
        return positive_int(match.group(1), 25, "daily_send_limit")
    return 25


def parse_approval_required(prompt: str) -> bool:
    lowered = prompt.lower()
    if any(term in lowered for term in ("auto-send", "autosend", "without approval", "no approval")):
        return False
    return True


def parse_campaign(prompt: str) -> dict:
    target_count = parse_target_count(prompt)
    niche, location = parse_niche_location(prompt, target_count)
    return {
        "niche": niche,
        "location": location,
        "target_count": target_count,
        "offer": parse_offer(prompt),
        "language": parse_language(prompt),
        "approval_required": parse_approval_required(prompt),
        "daily_send_limit": parse_daily_limit(prompt),
    }


def create_campaign(params: dict) -> int:
    con = connect()
    cur = con.execute(
        """
        INSERT INTO campaigns (
            niche, location, target, target_count, offer, language,
            approval_required, daily_send_limit, status, updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            params["niche"],
            params["location"],
            params["target_count"],
            params["target_count"],
            params.get("offer"),
            params["language"],
            1 if params.get("approval_required", True) else 0,
            params["daily_send_limit"],
            "draft",
            now_iso(),
        ),
    )
    con.commit()
    campaign_id = cur.lastrowid
    con.close()
    return campaign_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a campaign request")
    parser.add_argument("prompt", nargs="*", help="Campaign request text")
    parser.add_argument("--prompt", dest="prompt_flag", help="Campaign request text")
    parser.add_argument("--create", action="store_true", help="Create the campaign record after parsing")
    args = parser.parse_args()

    prompt = args.prompt_flag or " ".join(args.prompt)
    if not prompt:
        raise SystemExit("ERROR: provide a campaign prompt")

    try:
        params = parse_campaign(prompt)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    if args.create:
        params["campaign_id"] = create_campaign(params)

    print(json.dumps(params, indent=2, sort_keys=True))
    if args.create:
        print(f"CAMPAIGN_ID={params['campaign_id']}")


if __name__ == "__main__":
    main()
