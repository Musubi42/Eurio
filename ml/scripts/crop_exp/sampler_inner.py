"""Sampler bottom/top sur inner_feature_score (S5 — anti-B).

Trie par `inner_feature_score` = raw_max_circle_diameter / bbox_max_dim
(via Hough relancé sur le RAW + filtre "circle contient le bbox").

TOP N = ratio élevé = bbox tiny dans une grosse pièce → cat B attendu.
BOTTOM N = ratio ≈ 1 → bbox capte déjà la pièce entière (cat D) OU pas
  de circle contenant (cat A/C/D bien-cropés).

Usage::

    python -m scripts.crop_exp.sampler_inner --run-id <id> --output /tmp/inner.html
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
    PAGE_TPL,
    card_html,
    fetch_all_cards,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--sidecar-suffix", default="_inner",
                    help="Suffixe du sidecar (ex: _inner_de_2010).")
    args = ap.parse_args()

    scores_path = _ML_DIR / "state" / "crop_scores" / f"{args.run_id}{args.sidecar_suffix}.json"
    if not scores_path.exists():
        print(f"Sidecar absent : {scores_path}")
        print("Lancer score_crops_inner.py d'abord.")
        return 1

    records = json.loads(scores_path.read_text())
    records.sort(key=lambda r: r["inner_feature_score"])
    bottom = records[: args.n]
    top = list(reversed(records[-args.n:]))

    print("[sampler_inner] fetching all cards…")
    all_cards = fetch_all_cards(args.run_id)
    print(f"  got {len(all_cards)} cards")

    def render(group: list[dict]) -> str:
        return "\n".join(
            card_html(all_cards[r["asset_id"]], r["inner_feature_score"])
            for r in group if r["asset_id"] in all_cards
        )

    html = PAGE_TPL.format(
        n=args.n,
        bottom_html=render(bottom),
        top_html=render(top),
    )
    html = html.replace(
        "Score sampler — composite is_coin (Approche A)",
        "Score sampler — inner_feature_score (S5 anti-B)",
    ).replace(
        "Score = rim_peak × continuity_penalty × disc_metalness.",
        "inner_feature_score = raw_max_hough_circle_diameter / bbox_max_dim "
        "(circle doit contenir le bbox). HAUT = bbox tiny dans grosse pièce "
        "(cat B undercrop bimétal attendu). BAS = bbox déjà collé à la pièce (cat D).",
    )

    # Retirer loading="lazy" pour permettre les screenshots full-page.
    html = html.replace('loading="lazy"', '')

    Path(args.output).write_text(html, encoding="utf-8")
    print(f"[sampler_inner] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
