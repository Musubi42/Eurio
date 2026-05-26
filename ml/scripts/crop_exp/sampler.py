"""Génère un HTML statique multi-panneaux pour inspecter visuellement
les crops d'un run, organisés par (group × method). Sert d'oracle œil
humain pour le chantier docs/crop-forensics/.

Usage::

    python -m scripts.crop_exp.sampler --run-id <id> --output /tmp/sampler.html

Optionnel : --groups DE-2010,AT-2005 --methods yolo+hough,yolo+hough+polish
            --per-cell 8 --random-seed 42

Le HTML embarque CSS aligné sur BenchCropEvidenceCard.vue (mask + bordure
rouge/or + label dimensions). Ouvre dans Chrome headless pour screenshot.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from urllib import parse, request

_ML_DIR = Path(__file__).resolve().parents[2]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

API = "http://localhost:8042"


def fetch_crops(run_id: str, country: str, year: int, method: str | None,
                limit: int = 200) -> list[dict]:
    params = {"country": country, "year": str(year), "limit": str(limit),
              "sort": "recent"}
    if method:
        params["method"] = method
    qs = parse.urlencode(params)
    url = f"{API}/bench/runs/{run_id}/crops?{qs}"
    with request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    return data["cards"]


def card_html(c: dict) -> str:
    if not c.get("bbox_pct") or not c.get("raw_url"):
        return ""
    p = c["bbox_pct"]
    bbox = c.get("bbox") or {}
    dims = f"{int(bbox.get('w', 0))}×{int(bbox.get('h', 0))}"
    warn = "warn" if c.get("is_undercrop_suspect") else ""
    raw = API + c["raw_url"]
    crop = API + (c.get("crop_url") or "")
    return f"""
    <div class="card {warn}">
      <div class="card__stage">
        <div class="card__frame" style="aspect-ratio: {c['raw_width']} / {c['raw_height']};">
          <img class="card__raw" src="{raw}" loading="lazy" />
          <div class="card__mask" style="top:0;left:0;width:100%;height:{p['y']}%"></div>
          <div class="card__mask" style="top:{p['y']}%;left:0;width:{p['x']}%;height:{p['h']}%"></div>
          <div class="card__mask" style="top:{p['y']}%;left:{p['x']+p['w']}%;right:0;height:{p['h']}%"></div>
          <div class="card__mask" style="top:{p['y']+p['h']}%;left:0;width:100%;bottom:0"></div>
          <div class="card__bbox {warn}" data-dims="{dims}"
               style="left:{p['x']}%;top:{p['y']}%;width:{p['w']}%;height:{p['h']}%"></div>
        </div>
        <div class="card__crop-chip"><img src="{crop}" loading="lazy" /></div>
      </div>
      <div class="card__meta">
        <code>{c['asset_id'][:8]}</code> · crop {c['crop_index']}
        · raw {c['raw_width']}×{c['raw_height']}
      </div>
    </div>"""


PAGE_TPL = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Crop sampler {run_id}</title>
<style>
  :root {{
    --ink:#0E0E1F; --ink-400:#7A7B90; --ink-500:#55566C;
    --surface:#FAFAF8; --surface-1:#F4F3EE; --surface-2:#ECEBE4; --surface-3:#E2E0D6;
    --gold-300:#E0C688; --danger:#D14343;
  }}
  body {{ background: var(--surface-1); font-family: system-ui, sans-serif;
          padding: 20px; color: var(--ink); }}
  h1 {{ font-size: 18px; margin-bottom: 4px; }}
  .panels {{ display: flex; flex-direction: column; gap: 28px; }}
  .panel {{ background: var(--surface); border: 1px solid var(--surface-3);
            border-radius: 12px; padding: 16px; }}
  .panel h2 {{ font-size: 14px; margin-bottom: 12px;
                font-family: ui-monospace, monospace; color: var(--ink-500); }}
  .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(4, 1fr); }}
  .card {{ background: var(--surface-1); border: 1px solid var(--surface-3);
            border-radius: 12px; overflow: hidden; }}
  .card.warn {{ border-color: var(--danger);
                 box-shadow: 0 0 0 1px rgba(209,67,67,0.18); }}
  .card__stage {{ position: relative; aspect-ratio: 1/1;
                   display: flex; align-items: center; justify-content: center;
                   overflow: hidden;
                   background: linear-gradient(135deg, var(--surface-2), var(--surface-1)); }}
  .card__frame {{ position: relative; max-width: 100%; max-height: 100%; display: flex; }}
  .card__raw {{ display: block; width: 100%; height: 100%; object-fit: fill; }}
  .card__mask {{ position: absolute; background: rgba(14,14,31,0.62);
                  pointer-events: none; }}
  .card__bbox {{ position: absolute; pointer-events: none;
                  border: 2px solid var(--gold-300);
                  box-shadow: 0 0 0 1px rgba(0,0,0,0.55),
                              inset 0 0 0 1px rgba(0,0,0,0.55); }}
  .card__bbox.warn {{ border-color: #FF5959; }}
  .card__bbox::after {{ content: attr(data-dims);
                         position: absolute; top: -19px; left: -1px;
                         padding: 2px 6px;
                         font: 500 10px ui-monospace, monospace;
                         color: var(--ink); background: var(--gold-300);
                         border-radius: 3px 3px 3px 0; }}
  .card__bbox.warn::after {{ color: #fff; background: #FF5959; }}
  .card__crop-chip {{
    position: absolute; bottom: 8px; right: 8px;
    width: 56px; height: 56px; border-radius: 50%; overflow: hidden;
    border: 2px solid var(--surface);
    box-shadow: 0 2px 6px rgba(0,0,0,0.18);
  }}
  .card__crop-chip img {{ width: 100%; height: 100%; object-fit: cover; }}
  .card__meta {{ padding: 8px 10px; font-size: 11px;
                  color: var(--ink-500);
                  font-family: ui-monospace, monospace; }}
</style></head>
<body>
<h1>Crop sampler — run <code>{run_id_short}</code> · {n_panels} panels</h1>
<p style="font-size: 12px; color: var(--ink-400); margin-bottom: 24px">
  Chaque panneau = (group × method). Cards = échantillon aléatoire (seed {seed}).
  Bbox rouge = is_undercrop_suspect côté serveur (seuil par défaut). Crop chip
  bottom-right = sortie 224×224 finale.
</p>
<div class="panels">
{panels_html}
</div>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--groups", default="DE-2010,AT-2005,IT-2016,DE-2007",
                    help="comma-separated CC-YYYY")
    ap.add_argument("--methods",
                    default="yolo+hough,yolo+hough+polish,yolo+bbox,yolo+bbox+polish")
    ap.add_argument("--per-cell", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rnd = random.Random(args.seed)
    groups = [g.split("-", 1) for g in args.groups.split(",")]
    methods = args.methods.split(",")

    panels = []
    for country, year in groups:
        for method in methods:
            cards = fetch_crops(args.run_id, country, int(year), method, limit=200)
            if not cards:
                continue
            rnd.shuffle(cards)
            sample = cards[: args.per_cell]
            cells_html = "\n".join(card_html(c) for c in sample)
            n_total = len(cards)
            panels.append(f"""
            <section class="panel">
              <h2>{country} · {year} · 2 € · <b>{method}</b>
                  <span style="color:#A6A7B6">— {len(sample)} / {n_total} crops</span></h2>
              <div class="grid">{cells_html}</div>
            </section>""")

    html = PAGE_TPL.format(
        run_id=args.run_id,
        run_id_short=args.run_id[:8],
        n_panels=len(panels),
        seed=args.seed,
        panels_html="\n".join(panels),
    )
    Path(args.output).write_text(html, encoding="utf-8")
    print(f"[sampler] wrote {args.output} · {len(panels)} panels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
