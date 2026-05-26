"""Sampler bottom/top sur near_white_ratio (S4 — anti-A révisée).

Trie par `near_white_ratio` = fraction de pixels V > 220 dans le disque
intérieur (80 % du rayon). Proxy "fond blanc / sticker / strip".

BOTTOM N = near_white_ratio bas = contenu métallique → devrait être cat D.
TOP N    = near_white_ratio élevé = contenu très blanc → devrait être cat A.

Usage::

    python -m scripts.crop_exp.sampler_bg --run-id <id> --output /tmp/bg.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parents[2]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

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

    scores_path = _ML_DIR / "state" / "crop_scores" / f"{args.run_id}_bg.json"
    if not scores_path.exists():
        print(f"Sidecar absent : {scores_path}")
        print("Lancer score_crops_bg.py d'abord.")
        return 1

    records = json.loads(scores_path.read_text())
    records.sort(key=lambda r: r["near_white_ratio"])
    bottom = records[: args.n]   # contenu métallique → devrait être cat D
    top = list(reversed(records[-args.n:]))  # contenu très blanc → devrait être cat A

    print("[sampler_bg] fetching all cards…")
    all_cards = fetch_all_cards(args.run_id)
    print(f"  got {len(all_cards)} cards")

    def render(group: list[dict]) -> str:
        return "\n".join(
            card_html(all_cards[r["asset_id"]], r["near_white_ratio"])
            for r in group if r["asset_id"] in all_cards
        )

    html = PAGE_TPL.format(
        n=args.n,
        bottom_html=render(bottom),
        top_html=render(top),
    )
    html = html.replace(
        "Score sampler — composite is_coin (Approche A)",
        "Score sampler — near_white_ratio (S4 anti-A révisée)",
    ).replace(
        "Score = rim_peak × continuity_penalty × disc_metalness.",
        "near_white_ratio = fraction pixels V > 220 dans disque intérieur (80 % rayon). "
        "BAS = métallique (cat D). HAUT = blanc/sticker/strip (cat A attendu).",
    )

    Path(args.output).write_text(html, encoding="utf-8")
    print(f"[sampler_bg] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
