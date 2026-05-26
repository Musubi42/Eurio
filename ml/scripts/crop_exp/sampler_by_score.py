"""Sampler trié par score is_coin (Approche A). Affiche les BOTTOM N et
les TOP N du composite, côte à côte, pour évaluer si le score capture
les bons cas.

Usage::

    python -m scripts.crop_exp.sampler_by_score --run-id <id> --output /tmp/scored.html
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

API = "http://localhost:8042"


def fetch_card(run_id: str, asset_id: str) -> dict | None:
    # We need the raw + bbox info. We fetch all crops once and index.
    raise NotImplementedError("use bulk fetch")


def fetch_all_cards(run_id: str) -> dict[str, dict]:
    # Fetch a big page (the run has ~1700 crops, default limit 200; need to paginate)
    by_id: dict[str, dict] = {}
    offset = 0
    while True:
        params = {"limit": "200", "offset": str(offset), "sort": "recent"}
        url = f"{API}/bench/runs/{run_id}/crops?{parse.urlencode(params)}"
        with request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
        cards = data["cards"]
        if not cards:
            break
        for c in cards:
            by_id[c["asset_id"]] = c
        if offset + 200 >= data["cards_total"]:
            break
        offset += 200
    return by_id


def card_html(c: dict, score: float) -> str:
    if not c.get("bbox_pct") or not c.get("raw_url"):
        return ""
    p = c["bbox_pct"]
    bbox = c.get("bbox") or {}
    dims = f"{int(bbox.get('w', 0))}×{int(bbox.get('h', 0))}"
    raw = API + c["raw_url"]
    crop = API + (c.get("crop_url") or "")
    return f"""
    <div class="card">
      <div class="score">{score:.1f}</div>
      <div class="card__stage">
        <div class="card__frame" style="aspect-ratio: {c['raw_width']} / {c['raw_height']};">
          <img class="card__raw" src="{raw}" loading="lazy" />
          <div class="card__mask" style="top:0;left:0;width:100%;height:{p['y']}%"></div>
          <div class="card__mask" style="top:{p['y']}%;left:0;width:{p['x']}%;height:{p['h']}%"></div>
          <div class="card__mask" style="top:{p['y']}%;left:{p['x']+p['w']}%;right:0;height:{p['h']}%"></div>
          <div class="card__mask" style="top:{p['y']+p['h']}%;left:0;width:100%;bottom:0"></div>
          <div class="card__bbox" data-dims="{dims}"
               style="left:{p['x']}%;top:{p['y']}%;width:{p['w']}%;height:{p['h']}%"></div>
        </div>
        <div class="card__crop-chip"><img src="{crop}" loading="lazy" /></div>
      </div>
      <div class="card__meta">
        <code>{c['asset_id'][:8]}</code> · {c.get('detection_method','?')}<br>
        {c.get('listing_country','?')} {c.get('listing_year','?')}
      </div>
    </div>"""


PAGE_TPL = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Score sampler</title>
<style>
  :root {{
    --ink:#0E0E1F; --ink-400:#7A7B90; --ink-500:#55566C;
    --surface:#FAFAF8; --surface-1:#F4F3EE; --surface-2:#ECEBE4; --surface-3:#E2E0D6;
    --gold-300:#E0C688; --danger:#D14343;
  }}
  body {{ background: var(--surface-1); font-family: system-ui;
          padding: 20px; color: var(--ink); }}
  h1 {{ font-size: 18px; }}
  .col {{ display: flex; flex-direction: column; gap: 28px; }}
  .panel {{ background: var(--surface); border: 1px solid var(--surface-3);
            border-radius: 12px; padding: 16px; }}
  .panel.bad {{ border-color: var(--danger); box-shadow: 0 0 0 1px rgba(209,67,67,0.18); }}
  .panel.good {{ border-color: #6DA56D; box-shadow: 0 0 0 1px rgba(109,165,109,0.18); }}
  .panel h2 {{ font-size: 14px; margin-bottom: 12px;
                font-family: ui-monospace, monospace; color: var(--ink-500); }}
  .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(6, 1fr); }}
  .card {{ position: relative; background: var(--surface-1);
            border: 1px solid var(--surface-3); border-radius: 12px; overflow: hidden; }}
  .score {{ position: absolute; top: 6px; left: 6px; z-index: 9;
             padding: 2px 7px; border-radius: 4px;
             background: #0E0E1F; color: #fff;
             font: 600 11px ui-monospace, monospace; }}
  .card__stage {{ position: relative; aspect-ratio: 1/1;
                   display: flex; align-items: center; justify-content: center;
                   overflow: hidden; background: var(--surface-2); }}
  .card__frame {{ position: relative; max-width: 100%; max-height: 100%; display: flex; }}
  .card__raw {{ display: block; width: 100%; height: 100%; object-fit: fill; }}
  .card__mask {{ position: absolute; background: rgba(14,14,31,0.62); }}
  .card__bbox {{ position: absolute; border: 2px solid #FF5959;
                  box-shadow: 0 0 0 1px rgba(0,0,0,0.55), inset 0 0 0 1px rgba(0,0,0,0.55); }}
  .card__bbox::after {{ content: attr(data-dims);
                         position: absolute; top: -19px; left: -1px;
                         padding: 2px 6px;
                         font: 500 10px ui-monospace, monospace;
                         color: #fff; background: #FF5959;
                         border-radius: 3px 3px 3px 0; }}
  .card__crop-chip {{ position: absolute; bottom: 8px; right: 8px;
                       width: 56px; height: 56px; border-radius: 50%; overflow: hidden;
                       border: 2px solid var(--surface);
                       box-shadow: 0 2px 6px rgba(0,0,0,0.18); }}
  .card__crop-chip img {{ width: 100%; height: 100%; object-fit: cover; }}
  .card__meta {{ padding: 6px 8px; font-size: 10px;
                  color: var(--ink-500); font-family: ui-monospace, monospace; }}
</style></head>
<body>
<h1>Score sampler — composite is_coin (Approche A)</h1>
<p style="font-size:12px;color:var(--ink-400);margin-bottom:24px">
  Score = rim_peak × continuity_penalty × disc_metalness.
  BAS = pas une pièce / mauvais crop. HAUT = vraie pièce bien cadrée.
</p>
<div class="col">
  <section class="panel bad">
    <h2>BOTTOM {n} (score le plus bas — devraient être de mauvais crops)</h2>
    <div class="grid">{bottom_html}</div>
  </section>
  <section class="panel good">
    <h2>TOP {n} (score le plus haut — devraient être de vrais crops bien cadrés)</h2>
    <div class="grid">{top_html}</div>
  </section>
</div>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()

    # Load scores sidecar.
    scores_path = _ML_DIR / "state" / "crop_scores" / f"{args.run_id}.json"
    records = json.loads(scores_path.read_text())
    # Sort by composite ascending.
    records.sort(key=lambda r: r["composite"])
    bottom = records[: args.n]
    top = list(reversed(records[-args.n :]))

    # Fetch all cards via API.
    print("[sampler_by_score] fetching all cards…")
    all_cards = fetch_all_cards(args.run_id)
    print(f"  got {len(all_cards)} cards")

    def render(group: list[dict]) -> str:
        return "\n".join(
            card_html(all_cards[r["asset_id"]], r["composite"])
            for r in group if r["asset_id"] in all_cards
        )

    html = PAGE_TPL.format(
        n=args.n,
        bottom_html=render(bottom),
        top_html=render(top),
    )
    Path(args.output).write_text(html, encoding="utf-8")
    print(f"[sampler_by_score] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
