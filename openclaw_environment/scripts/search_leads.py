"""Search approved providers through the provider MCP backend."""
from __future__ import annotations

import argparse
import json
import sys

from provider_client import ProviderError, discover_candidates


def build_queries(niche: str, location: str) -> list[str]:
    return [
        f"{niche} {location} official website",
        f"{niche} {location} contact email",
        f"best {niche} in {location}",
        f"{niche} near {location} website",
    ]


def search(niche: str, location: str, count: int) -> dict:
    try:
        return discover_candidates(niche, location, count)
    except ProviderError as exc:
        return {
            "queries": build_queries(niche, location),
            "provider_configured": False,
            "results": [],
            "errors": [{"provider": "outreach-provider", "query": "", "error": str(exc)}],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Search for candidate business websites")
    parser.add_argument("--niche", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()

    output = search(args.niche, args.location, args.count)
    print(json.dumps(output, indent=2, sort_keys=True))
    for error in output["errors"]:
        print(
            f"ERROR: {error['provider']} failed for {error['query']}: {error['error']}",
            file=sys.stderr,
        )
    if not output["provider_configured"]:
        print(
            "ERROR: start the provider MCP server with SERPAPI_API_KEY or BING_SEARCH_API_KEY configured",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
