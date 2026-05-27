"""HTML selector pour construire une cohorte handpicked.

Génère une page interactive listant les assets d'un (country, year) du run,
avec :
- regroupement par raw (1 card visible par défaut + déplier pour voir les
  autres crops du même raw),
- auto-balance pré-coché (mix composite_score × inner_feature_score × lot),
- compteur live X/30 sticky en haut,
- export JSON au format figé pour la suite (test runner + compare).

Usage::

    python -m scripts.crop_exp.cohort_selector \\
        --run-id 059dc8d90dad42558e3c6319a722fd35 \\
        --country DE --year 2010 \\
        --target 30 \\
        --output ml/state/crop_scores/cohorts/de2010_selector.html
"""

from __future__ import annotations

import argparse
import datetime
import json
import random
import sqlite3
import sys
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parents[2]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

API_BASE = "http://localhost:8042"


def load_assets(conn: sqlite3.Connection, run_id: str,
                country: str | None, year: int | None) -> list[dict]:
    sql = """
        SELECT a.id AS asset_id, a.bbox_json, a.storage_path AS crop_path,
               a.detection_method AS method,
               s.id AS source_id, s.source AS source, s.storage_path AS raw_path,
               s.width AS raw_w, s.height AS raw_h,
               s.is_lot_suspected AS is_lot, s.n_crops_detected AS n_crops,
               s.source_url AS source_url,
               s.listing_country AS country, s.listing_year AS year
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.run_id = ?
    """
    params: list[object] = [run_id]
    if country:
        sql += " AND s.listing_country = ?"
        params.append(country)
    if year is not None:
        sql += " AND s.listing_year = ?"
        params.append(year)
    sql += " ORDER BY a.fetched_at DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def load_sidecar(path: Path, key: str) -> dict[str, float]:
    if not path.exists():
        return {}
    recs = json.loads(path.read_text())
    return {r["asset_id"]: r.get(key, 0) for r in recs}


def enrich(assets: list[dict], run_id: str) -> list[dict]:
    """Joint composite + inner_feature_score quand dispos."""
    composite = load_sidecar(_ML_DIR / "state" / "crop_scores" / f"{run_id}.json",
                              "composite")
    # try {run}_inner_{country}_{year}.json first
    inner_paths = list((_ML_DIR / "state" / "crop_scores").glob(f"{run_id}_inner*.json"))
    inner: dict[str, float] = {}
    for p in inner_paths:
        inner.update(load_sidecar(p, "inner_feature_score"))
    for a in assets:
        a["composite"] = composite.get(a["asset_id"])
        a["inner_feature_score"] = inner.get(a["asset_id"])
        bbox = json.loads(a["bbox_json"]) if a["bbox_json"] else {}
        a["bbox"] = bbox
    return assets


def auto_balance(assets: list[dict], target: int,
                 seed: int = 42) -> list[str]:
    """Sélectionne `target` asset_ids pour un mix indicatif (composite bas/haut,
    inner haut, singles vs lots) en évitant 2× le même raw. Retourne les
    asset_ids présélectionnés.

    Stratégie :
      - 1/6 cat A présumés : composite bas (~bottom 10 %)
      - 1/6 cat B présumés : inner_feature_score haut (~top 15 %) ET single
      - 1/3 cat C présumés : lots (n_crops >= 5)
      - 1/3 cat D présumés : single, composite haut
      - rand fill si manquant
    """
    rng = random.Random(seed)
    seen_sources: set[str] = set()
    picked: list[str] = []

    def take_from(pool: list[dict], n: int) -> None:
        rng.shuffle(pool)
        for a in pool:
            if len(picked) >= target:
                return
            if a["source_id"] in seen_sources:
                continue
            picked.append(a["asset_id"])
            seen_sources.add(a["source_id"])
            if sum(1 for x in picked if x == a["asset_id"]) >= n:
                # n quota for this bucket reached (not strict, juste indicatif)
                pass

    # Buckets selon les signaux disponibles.
    with_composite = [a for a in assets if a["composite"] is not None]
    with_composite.sort(key=lambda a: a["composite"])
    n_a = max(3, target // 6)
    take_from(with_composite[: max(20, target // 3)], n_a)  # bas → cat A présumé

    with_inner = [a for a in assets if a.get("inner_feature_score") is not None
                  and (a.get("n_crops") or 99) == 1]
    with_inner.sort(key=lambda a: a["inner_feature_score"], reverse=True)
    n_b = max(3, target // 6)
    take_from(with_inner[: max(15, target // 3)], n_b)  # haut single → cat B

    lots = [a for a in assets if (a.get("n_crops") or 0) >= 5]
    n_c = max(6, target // 3)
    take_from(lots, n_c)

    singles_good = [a for a in assets
                    if (a.get("n_crops") or 99) == 1
                    and a["composite"] is not None]
    singles_good.sort(key=lambda a: a["composite"], reverse=True)
    n_d = max(6, target // 3)
    take_from(singles_good[: max(30, target // 2)], n_d)

    # Random fill si pas assez (ex: cohorte petite).
    if len(picked) < target:
        rest = [a for a in assets if a["asset_id"] not in picked
                and a["source_id"] not in seen_sources]
        take_from(rest, target - len(picked))

    return picked[:target]


HTML_TPL = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 0; background: #F4F3EE; color: #0E0E1F;
          font-family: system-ui; }}
  header {{ position: sticky; top: 0; z-index: 10;
             background: #fff; border-bottom: 1px solid #E2E0D6;
             padding: 14px 24px; display: flex; align-items: center; gap: 24px; }}
  header h1 {{ margin: 0; font-size: 16px; }}
  .counter {{ font: 700 24px ui-monospace, monospace; }}
  .counter.ok {{ color: #5C9F3D; }}
  .counter.over {{ color: #D14343; }}
  .counter.under {{ color: #55566C; }}
  header input[type=text] {{ padding: 6px 10px; border: 1px solid #E2E0D6;
                              border-radius: 6px; font-family: ui-monospace, monospace;
                              font-size: 12px; width: 360px; }}
  header button {{ padding: 8px 14px; border: 0; border-radius: 6px;
                    background: #0E0E1F; color: #fff; cursor: pointer;
                    font-weight: 600; }}
  header button:hover {{ background: #2A2A40; }}
  header button.secondary {{ background: #ECEBE4; color: #0E0E1F; }}
  header button:disabled {{ opacity: 0.4; cursor: not-allowed; }}
  .info {{ margin: 12px 24px; padding: 12px; background: #fff;
            border: 1px solid #E2E0D6; border-radius: 8px;
            font-size: 13px; line-height: 1.5; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 12px; padding: 16px 24px; }}
  .card {{ background: #fff; border: 2px solid transparent;
            border-radius: 10px; overflow: hidden;
            position: relative; cursor: pointer;
            transition: border-color 0.1s, transform 0.1s; }}
  .card:hover {{ transform: translateY(-2px); }}
  .card.selected {{ border-color: #5C9F3D; }}
  .card.selected::after {{ content: "✓"; position: absolute; top: 6px; right: 6px;
                            width: 28px; height: 28px; border-radius: 50%;
                            background: #5C9F3D; color: #fff;
                            font-size: 18px; font-weight: 700;
                            display: flex; align-items: center; justify-content: center; }}
  .card__stage {{ position: relative; aspect-ratio: 1/1;
                   background: #ECEBE4; display: flex;
                   align-items: center; justify-content: center; }}
  .card__crop {{ width: 100%; height: 100%; object-fit: cover; }}
  .card__raw {{ position: absolute; bottom: 6px; right: 6px;
                 width: 64px; height: 64px; border-radius: 8px;
                 border: 2px solid #fff;
                 box-shadow: 0 2px 6px rgba(0,0,0,0.25);
                 object-fit: cover; background: #ECEBE4; }}
  .card__meta {{ padding: 6px 10px; font: 500 11px ui-monospace, monospace;
                  color: #55566C; line-height: 1.4; }}
  .badge {{ display: inline-block; padding: 1px 5px; border-radius: 3px;
            font-size: 10px; margin-right: 4px; }}
  .badge.lot {{ background: #8255AC; color: #fff; }}
  .badge.single {{ background: #ECEBE4; color: #55566C; }}
  .badge.score {{ background: #5C9F3D22; color: #2A6F25;
                   font-family: ui-monospace, monospace; }}
  .group {{ margin: 20px 24px; padding: 14px; background: #fff;
             border: 1px solid #E2E0D6; border-radius: 10px; }}
  .group__header {{ display: flex; align-items: center; gap: 12px;
                     margin-bottom: 10px; font-size: 12px;
                     color: #55566C; font-family: ui-monospace, monospace; }}
  .group__header button {{ padding: 4px 10px; font-size: 11px;
                            border: 1px solid #E2E0D6; background: #F4F3EE;
                            border-radius: 4px; cursor: pointer; }}
  .group__grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }}
  .hidden {{ display: none; }}
</style></head>
<body>
<header>
  <h1>{title}</h1>
  <div>Sélectionnés : <span class="counter under" id="counter">0</span> / {target}</div>
  <input type="text" id="cohortName" value="{default_name}" />
  <button class="secondary" id="resetBtn">Reset auto-balance</button>
  <button class="secondary" id="clearBtn">Tout désélectionner</button>
  <button id="exportBtn" disabled>Export JSON</button>
</header>

<div class="info">
  <strong>{n_total}</strong> assets DE/2010 groupés par <strong>{n_groups}</strong> raws uniques.
  Une card visible par raw par défaut ; clique sur <em>« +X autres crops »</em>
  pour voir les variantes. <strong>{n_initial}</strong> cards pré-cochées par auto-balance
  (mix cat A/B/C/D présumées). Tu ajustes, vise {target}, puis <em>Export JSON</em>.
  <br><br>
  <strong>API requise</strong> : ouvre la page avec <code>{api_base}</code> up
  (sinon les images ne s'affichent pas).
  <br><br>
  Après export, déplace le fichier dans <code>ml/state/crop_scores/cohorts/</code>
  pour qu'il soit utilisable par <code>ccproxy_judge test --cohort &lt;path&gt;</code>.
</div>

<div id="groups"></div>

<script>
const ASSETS = {assets_json};
const GROUPS = {groups_json};
const INITIAL = new Set({initial_json});
const TARGET = {target};
const RUN_ID = "{run_id}";
const FILTER = {filter_json};
const API_BASE = "{api_base}";

const selected = new Set(INITIAL);
const counterEl = document.getElementById("counter");
const exportBtn = document.getElementById("exportBtn");
const cohortNameEl = document.getElementById("cohortName");

function updateCounter() {{
  const n = selected.size;
  counterEl.textContent = n;
  counterEl.classList.toggle("ok", n === TARGET);
  counterEl.classList.toggle("over", n > TARGET);
  counterEl.classList.toggle("under", n < TARGET);
  exportBtn.disabled = n === 0;
}}

function toggleAsset(assetId, cardEl) {{
  if (selected.has(assetId)) {{
    selected.delete(assetId);
    cardEl.classList.remove("selected");
  }} else {{
    selected.add(assetId);
    cardEl.classList.add("selected");
  }}
  updateCounter();
}}

function renderCard(asset) {{
  const c = document.createElement("div");
  c.className = "card" + (selected.has(asset.asset_id) ? " selected" : "");
  c.dataset.assetId = asset.asset_id;
  const lotBadge = (asset.n_crops || 0) >= 2
    ? `<span class="badge lot">lot ${{asset.n_crops}}</span>`
    : `<span class="badge single">single</span>`;
  const compBadge = asset.composite != null
    ? `<span class="badge score">c=${{asset.composite.toFixed(2)}}</span>` : "";
  const innerBadge = asset.inner_feature_score != null
    ? `<span class="badge score">i=${{asset.inner_feature_score.toFixed(1)}}</span>` : "";
  c.innerHTML = `
    <div class="card__stage">
      <img class="card__crop" src="${{API_BASE}}/sources/${{asset.source}}/assets/${{asset.asset_id}}/file" />
      <img class="card__raw" src="${{API_BASE}}/sources/${{asset.source}}/raws/${{asset.source_id}}/file" />
    </div>
    <div class="card__meta">
      <code>${{asset.asset_id.slice(0, 8)}}</code><br>
      ${{lotBadge}} ${{compBadge}} ${{innerBadge}}
    </div>
  `;
  c.addEventListener("click", () => toggleAsset(asset.asset_id, c));
  return c;
}}

function renderGroups() {{
  const root = document.getElementById("groups");
  root.innerHTML = "";
  for (const [sourceId, assetIds] of Object.entries(GROUPS)) {{
    const g = document.createElement("div");
    g.className = "group";
    const head = document.createElement("div");
    head.className = "group__header";
    head.innerHTML = `<span>raw=<code>${{sourceId.slice(0, 8)}}</code> · ${{assetIds.length}} crop(s)</span>`;
    g.appendChild(head);
    const grid = document.createElement("div");
    grid.className = "group__grid";
    g.appendChild(grid);

    // Show first crop always; hide others, with expand button.
    const main = ASSETS[assetIds[0]];
    grid.appendChild(renderCard(main));
    if (assetIds.length > 1) {{
      const moreWrap = document.createElement("div");
      moreWrap.className = "group__grid hidden";
      moreWrap.style.gridColumn = "1 / -1";
      moreWrap.style.marginTop = "8px";
      for (const aid of assetIds.slice(1)) {{
        moreWrap.appendChild(renderCard(ASSETS[aid]));
      }}
      g.appendChild(moreWrap);

      const btn = document.createElement("button");
      btn.textContent = `+ ${{assetIds.length - 1}} autres crops du même raw`;
      btn.addEventListener("click", () => {{
        moreWrap.classList.toggle("hidden");
        btn.textContent = moreWrap.classList.contains("hidden")
          ? `+ ${{assetIds.length - 1}} autres crops du même raw`
          : `− cacher`;
      }});
      head.appendChild(btn);
    }}
    root.appendChild(g);
  }}
}}

document.getElementById("resetBtn").addEventListener("click", () => {{
  selected.clear();
  for (const a of INITIAL) selected.add(a);
  renderGroups();
  updateCounter();
}});

document.getElementById("clearBtn").addEventListener("click", () => {{
  selected.clear();
  renderGroups();
  updateCounter();
}});

document.getElementById("exportBtn").addEventListener("click", () => {{
  const name = cohortNameEl.value.trim() || "cohort";
  const payload = {{
    name: name,
    created_at: new Date().toISOString(),
    source_run_id: RUN_ID,
    filter: FILTER,
    asset_ids: Array.from(selected),
    notes: ""
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)],
                       {{type: "application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name + ".json";
  a.click();
  URL.revokeObjectURL(url);
}});

renderGroups();
updateCounter();
</script>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--country", default=None)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--target", type=int, default=30)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    conn = sqlite3.connect(_ML_DIR / "state" / "eurio.db")
    conn.row_factory = sqlite3.Row
    assets = load_assets(conn, args.run_id, args.country, args.year)
    print(f"[selector] {len(assets)} assets")
    assets = enrich(assets, args.run_id)

    # Group by source_id.
    groups: dict[str, list[str]] = {}
    for a in assets:
        groups.setdefault(a["source_id"], []).append(a["asset_id"])
    print(f"[selector] {len(groups)} raws uniques")

    initial = auto_balance(assets, args.target)
    print(f"[selector] auto-balance pré-coche {len(initial)} cards")

    by_aid = {a["asset_id"]: {
        "asset_id": a["asset_id"],
        "source_id": a["source_id"],
        "source": a.get("source"),
        "n_crops": a.get("n_crops"),
        "is_lot": a.get("is_lot"),
        "composite": a.get("composite"),
        "inner_feature_score": a.get("inner_feature_score"),
    } for a in assets}

    default_name = (
        f"{(args.country or 'all').lower()}{args.year or ''}-handpicked-"
        f"{datetime.date.today().isoformat()}"
    )

    html = HTML_TPL.format(
        title=f"Cohort selector — {args.country or 'all'}/{args.year or 'any'}",
        target=args.target,
        n_total=len(assets),
        n_groups=len(groups),
        n_initial=len(initial),
        default_name=default_name,
        run_id=args.run_id,
        api_base=API_BASE,
        assets_json=json.dumps(by_aid),
        groups_json=json.dumps(groups),
        initial_json=json.dumps(initial),
        filter_json=json.dumps({"country": args.country, "year": args.year}),
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"[selector] wrote {out_path}")
    print(f"[selector] open with the bench API running on {API_BASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
