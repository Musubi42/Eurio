"""Sampler S6 : `inner_feature_score` restreint aux raws non-lot.

Joint le sidecar `_inner*.json` à `source_images.is_lot_suspected` et
filtre `lot=0` AVANT de trier. Hypothèse : si on isole les singles, le
TOP-N du score capture cat B authentique (sans cat C album).

Usage::

    python -m scripts.crop_exp.sampler_inner_singles \
        --run-id <id> --sidecar-suffix _inner_de_2010 --output /tmp/inner_de_2010_singles.html
"""

from __future__ import annotations

import argparse
import json
import sqlite3
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
    ap.add_argument("--sidecar-suffix", default="_inner")
    ap.add_argument("--filter", choices=["not-lot", "n-crops-1"],
                    default="not-lot",
                    help="not-lot = is_lot_suspected=0 ; n-crops-1 = n_crops_detected=1 (true single).")
    args = ap.parse_args()

    scores_path = _ML_DIR / "state" / "crop_scores" / f"{args.run_id}{args.sidecar_suffix}.json"
    records = json.loads(scores_path.read_text())

    # Joindre is_lot_suspected.
    conn = sqlite3.connect(_ML_DIR / "state" / "eurio.db")
    conn.row_factory = sqlite3.Row
    ids = [r["asset_id"] for r in records]
    meta_map: dict[str, tuple[int, int]] = {}
    for start in range(0, len(ids), 200):
        chunk = ids[start:start + 200]
        q = (
            "SELECT a.id AS aid, s.is_lot_suspected AS lot, "
            "       s.n_crops_detected AS nd "
            "FROM image_assets a JOIN source_images s ON s.id=a.source_image_id "
            f"WHERE a.id IN ({','.join('?' * len(chunk))})"
        )
        for r in conn.execute(q, chunk).fetchall():
            meta_map[r["aid"]] = (r["lot"], r["nd"])

    if args.filter == "not-lot":
        singles = [r for r in records if meta_map.get(r["asset_id"], (None, None))[0] == 0]
        label = "is_lot_suspected=0"
    else:
        singles = [r for r in records if meta_map.get(r["asset_id"], (None, None))[1] == 1]
        label = "n_crops_detected=1 (true single)"
    print(f"[sampler_inner_singles] filter={args.filter} ({label}) — "
          f"total={len(records)} → {len(singles)}")

    singles.sort(key=lambda r: r["inner_feature_score"])
    bottom = singles[: args.n]
    top = list(reversed(singles[-args.n:]))

    print("[sampler_inner_singles] fetching all cards…")
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
        "Score sampler — inner_feature_score × NOT is_lot_suspected (S6)",
    ).replace(
        "Score = rim_peak × continuity_penalty × disc_metalness.",
        "inner_feature_score sur raws SINGLE uniquement (is_lot_suspected=0). "
        "HAUT = bbox tiny dans grosse pièce, cat B attendu sans pollution album.",
    )
    html = html.replace('loading="lazy"', '')

    Path(args.output).write_text(html, encoding="utf-8")
    print(f"[sampler_inner_singles] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
