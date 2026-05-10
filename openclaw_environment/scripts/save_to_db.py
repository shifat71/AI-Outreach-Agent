"""Save a scraped lead JSON object into the campaign database."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Save one scraped lead JSON object")
    parser.add_argument("--campaign-id", type=int, required=True)
    parser.add_argument("--input-file", help="JSON file; defaults to stdin")
    args = parser.parse_args()

    if args.input_file:
        with open(args.input_file, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    emails = data.get("emails") or []
    email = emails[0] if emails else None
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    cmd = [
        sys.executable,
        os.path.join(root_dir, "scripts", "track.py"),
        "add-lead",
        "--campaign-id",
        str(args.campaign_id),
        "--url",
        data.get("url") or data.get("website_url") or "",
        "--business-name",
        data.get("business_name") or "",
        "--description",
        data.get("description") or "",
        "--source-url",
        data.get("email_source_url") or data.get("contact_page_url") or data.get("url") or "",
    ]
    if email:
        cmd.extend(["--email", email])
    if data.get("contact_page_url"):
        cmd.extend(["--contact-page-url", data["contact_page_url"]])
    if data.get("address"):
        cmd.extend(["--address", data["address"]])

    if not data.get("url") and not data.get("website_url"):
        raise SystemExit("ERROR: lead JSON must include url or website_url")

    result = subprocess.run(cmd, check=False, text=True, capture_output=True, cwd=root_dir)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
