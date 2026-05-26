"""Sampler bottom/top sur unified_score (v2). Identique à sampler_by_score
mais lit le sidecar v2 et trie par unified_score.

Usage::

    python -m scripts.crop_exp.sampler_v2 --run-id <id> --output /tmp/v2.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib import parse, request

_ML_DIR = Path(__file__).resolve().parents[2]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

# Réutilise les helpers du sampler v1 (card_html, PAGE_TPL, fetch_all_cards).
from scripts.crop_exp.sampler_by_score import (  # noqa: E402
    API,
    PAGE_TPL,
    card_html,
    fetch_all_cards,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()

    scores_path = _ML_DIR / "state" / "crop_scores" / f"{args.run_id}_v2.json"
    if not scores_path.exists():
        print(f"v2 sidecar absent : {scores_path}")
        print("Run score_crops_v2.py d'abord.")
        return 1
    records = json.loads(scores_path.read_text())
    records.sort(key=lambda r: r["unified_score"])
    bottom = records[: args.n]
    top = list(reversed(records[-args.n:]))

    print("[sampler_v2] fetching all cards…")
    all_cards = fetch_all_cards(args.run_id)
    print(f"  got {len(all_cards)} cards")

    def render(group: list[dict]) -> str:
        return "\n".join(
            card_html(all_cards[r["asset_id"]], r["unified_score"])
            for r in group if r["asset_id"] in all_cards
        )

    # Reprend le PAGE_TPL v1 mais override le titre/intro pour v2.
    html = PAGE_TPL.format(
        n=args.n,
        bottom_html=render(bottom),
        top_html=render(top),
    )
    # Patch léger : remplacer "Approche A" titre par "v2 unified".
    html = html.replace(
        "Score sampler — composite is_coin (Approche A)",
        "Score sampler — unified_score (v2 = composite × area_ratio_factor)",
    ).replace(
        "Score = rim_peak × continuity_penalty × disc_metalness.",
        "unified_score = composite v1 × clip(area_ratio / 0.15, 0, 1). "
        "Punit les undercrops (cat B) malgré rim/metal corrects.",
    )
    Path(args.output).write_text(html, encoding="utf-8")
    print(f"[sampler_v2] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
