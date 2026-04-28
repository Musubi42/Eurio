"""Dump current quota status for a source as JSON.

Usage:
    python -m api_quota_cli --source numista
    python -m api_quota_cli --source ebay
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from api_quota import QuotaTracker

# Known sources and their (window, limit). Phase D will move this to a registry.
SOURCES: dict[str, tuple[str, int]] = {
    "numista": ("monthly", 1800),
    "ebay": ("daily", 5000),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    args = parser.parse_args()

    window, limit = SOURCES[args.source]
    tracker = QuotaTracker(args.source, window, limit)
    total = tracker.total()
    per_key = tracker.status()

    payload = {
        **asdict(total),
        "per_key": [asdict(s) for s in per_key],
    }
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
