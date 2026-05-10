"""Wrapper for reply tracking."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Check inbox replies for sent campaign emails")
    parser.add_argument("--campaign-id", type=int)
    args = parser.parse_args()

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    cmd = [sys.executable, os.path.join(root_dir, "scripts", "track.py"), "check-replies"]
    if args.campaign_id:
        cmd.extend(["--campaign-id", str(args.campaign_id)])
    raise SystemExit(subprocess.run(cmd, cwd=root_dir).returncode)


if __name__ == "__main__":
    main()
