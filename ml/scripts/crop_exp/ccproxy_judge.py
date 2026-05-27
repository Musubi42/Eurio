"""Juge vision via ccproxy — module commun smoke/batch/full.

Phases :
  Phase 1 (smoke)   : 1 paire (raw + crop), 1 appel, 1 HTML debug.
  Phase 2 (batch)   : N paires en 1 appel, 1 HTML debug grille.
  Phase 3 (full)    : loop par chunks de --batch-size paires, sidecar JSON.

L'ordre des images est CRITIQUE : (raw_k, crop_k) pour k=1..N, alternés.
Le texte décrit explicitement le mapping.

Usage::

    # Phase 1 smoke
    python -m scripts.crop_exp.ccproxy_judge smoke --asset-id <id>

    # Phase 2 batch (debug HTML, pas de persistance)
    python -m scripts.crop_exp.ccproxy_judge batch \\
        --run-id <id> --country DE --year 2010 --n 5

    # Phase 3 full (persiste sidecar)
    python -m scripts.crop_exp.ccproxy_judge full \\
        --run-id <id> --country DE --year 2010 --batch-size 5
"""

from __future__ import annotations

import argparse
import base64
import datetime
import io
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import request as urlreq

from PIL import Image

_ML_DIR = Path(__file__).resolve().parents[2]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from storage.local_cache import local_path

CCPROXY_URL = "http://localhost:3002/v1/chat/completions"
MODEL = "claude-sonnet-4-6"
MAX_RAW_SHORT_SIDE = 1024

# Margin baked-in dans les crops eBay producer (bench_listing_detection.py
# appelle _crop_mask_resize_int sans config → defaults legacy = 2 %).
PRODUCER_MARGIN_FRAC = 0.02

SYSTEM_PROMPT = """Tu es un juge expert en numismatique euro qui audite la
sortie d'un pipeline de détection automatique de pièces sur des photos
eBay.

CONTEXTE STRATÉGIQUE — pourquoi on fait ça :
Les crops servent à entraîner un modèle ArcFace de reconnaissance
fine-grained de pièces euro (chaque pièce a sa propre classe). La qualité
du crop conditionne directement la qualité du modèle. Deux axes
indépendants nous intéressent :
  (1) Qualité de la DÉTECTION (le pipeline a-t-il identifié la bonne
      pièce dans le raw ? cat A/B/C/R/D).
  (2) Qualité du FORMAT du crop (margin autour du rim — important pour
      ArcFace : la convention standard face recognition est ~20 % de
      marge autour de l'objet, MTCNN ×1.2 ; notre format legacy n'a
      que 2 % de marge, le rim touche presque le bord. Faut-il plus ?).

Pour chaque paire d'images, tu reçois :
  1. Le **raw** = la photo eBay originale, qui peut contenir n'importe
     quoi (1 pièce, plusieurs pièces, un blason, un timbre, du texte…).
  2. Le **crop** = le carré 224×224 que notre pipeline a extrait du raw
     en visant une pièce euro vue de face (obverse). Le crop EST une
     région du raw (zoom + recentrage + masque circulaire noir hors disque).

Ton job : juger la **qualité du crop dans le contexte du raw**, sur les
2 axes (détection + format).

Schéma de réponse JSON STRICT (un objet par paire, jamais de markdown,
jamais de texte hors JSON) :

{
  "asset": "AAAAAAAA",                 // identifiant court 8 char, copié verbatim de l'input
  "is_coin": true | false,             // l'objet principal du CROP est-il une pièce de monnaie ?
  "face": "obverse" | "reverse" | "edge" | "both" | "none",
  "is_lot": true | false,              // le RAW montre-t-il plusieurs pièces distinctes ?
  "n_coins_visible_in_raw": 0,         // nombre de pièces euro visibles dans le RAW (0 si aucune)
  "undercrop_severity": "none" | "mild" | "strong",
  "margin_assessment": "too_tight" | "ok" | "too_loose",
  "crop_quality": "good" | "acceptable" | "bad",
  "category": "A" | "B" | "C" | "R" | "D",
  "confidence": 0.0,                   // entre 0.0 et 1.0
  "reasoning_fr": "1 phrase de 10-20 mots"
}

Définitions précises :

- **is_coin** : true si l'objet principal du crop est une vraie pièce de
  monnaie métallique (pas un blason peint, sticker, timbre, capsule
  vide, label texte).
- **face** :
    - obverse = côté national (portrait, emblème, carte d'un pays)
    - reverse = côté commun européen (carte d'Europe + grand chiffre)
    - edge    = on voit la tranche
    - both    = on voit clairement les 2 faces (composite, rare)
    - none    = pas une pièce
- **is_lot** : true si le RAW montre 2+ pièces distinctes (album, set,
  planche, plusieurs exemplaires posés côte à côte).
- **n_coins_visible_in_raw** : compte approximatif des pièces euro
  visibles dans le RAW. 1 = single, >= 2 = lot.
- **undercrop_severity** (mesure la sévérité du bug détection cat B) :
    - none   = rim entier visible dans le crop
    - mild   = la pièce dépasse un peu (rim coupé sur 1-2 côtés)
    - strong = on ne voit qu'une portion intérieure (pas de rim du tout) ;
               typique du bug bimétal où Hough a voté le ring intérieur
- **margin_assessment** (mesure la marge entre le rim et le bord du crop —
  axe FORMAT, pertinent UNIQUEMENT quand undercrop_severity="none") :
    - too_tight  = le rim touche le bord du crop, 0-1 pixel de fond visible
                   (notre format legacy 2 % margin produit majoritairement ça)
    - ok         = quelques pixels de fond noir visibles entre le rim et le
                   bord (~5-15 % du rayon)
    - too_loose  = beaucoup de fond noir visible, la pièce occupe < 70 %
                   de la surface du crop
  → Si undercrop_severity != "none", écris quand même une valeur
     plausible mais elle ne sera pas utilisée dans les stats.
- **crop_quality** axe indépendant :
    - good       = la pièce dans le crop est lisible, nette, exploitable
    - acceptable = un peu blur, sombre ou décentré mais on identifie
    - bad        = inutilisable (flou, partiel, occlusion forte, non-pièce)
- **category** = verdict unique sur la DÉTECTION :
    - A = pas une pièce du tout (sticker, blason, label, texte, capsule vide)
    - B = pièce visible mais crop bien trop serré (strong undercrop)
    - C = lot multi-pièces (plusieurs pièces dans le raw)
    - R = pièce reverse (côté commun européen → inutile pour nous)
    - D = obverse bien cadrée (objectif final, à garder)
- **confidence** : 0.0=pas du tout sûr, 1.0=certain (sur category).
- **reasoning_fr** : 1 phrase, 10-20 mots, qui explique le verdict.

Quand on te donne N paires, tu réponds par un **JSON array** de N objets
dans l'ordre exact des paires, RIEN d'autre.
"""


@dataclass
class Pair:
    asset_id: str
    short_id: str
    crop_path: Path
    raw_path: Path
    bbox: dict


# ---------------------------------------------------------------------------
# DB + image loading
# ---------------------------------------------------------------------------

def fetch_pair(conn: sqlite3.Connection, asset_id: str) -> Pair:
    r = conn.execute(
        "SELECT a.id, a.storage_path AS crop_path, a.bbox_json, "
        "       s.storage_path AS raw_path "
        "  FROM image_assets a "
        "  JOIN source_images s ON s.id = a.source_image_id "
        " WHERE a.id = ?",
        (asset_id,),
    ).fetchone()
    if not r:
        raise ValueError(f"asset_id introuvable : {asset_id}")
    return Pair(
        asset_id=r["id"],
        short_id=r["id"][:8],
        crop_path=local_path("enrichment-crops", r["crop_path"]),
        raw_path=local_path("enrichment-raws", r["raw_path"]),
        bbox=json.loads(r["bbox_json"]) if r["bbox_json"] else {},
    )


def fetch_pairs(conn: sqlite3.Connection,
                run_id: str,
                country: str | None,
                year: int | None,
                limit: int | None) -> list[Pair]:
    sql = (
        "SELECT a.id, a.storage_path AS crop_path, a.bbox_json, "
        "       s.storage_path AS raw_path "
        "  FROM image_assets a "
        "  JOIN source_images s ON s.id = a.source_image_id "
        " WHERE a.run_id = ?"
    )
    params: list[object] = [run_id]
    if country:
        sql += " AND s.listing_country = ?"
        params.append(country)
    if year is not None:
        sql += " AND s.listing_year = ?"
        params.append(year)
    sql += " ORDER BY a.fetched_at DESC"
    rows = conn.execute(sql, params).fetchall()
    if limit:
        rows = rows[:limit]
    out: list[Pair] = []
    for r in rows:
        try:
            out.append(Pair(
                asset_id=r["id"],
                short_id=r["id"][:8],
                crop_path=local_path("enrichment-crops", r["crop_path"]),
                raw_path=local_path("enrichment-raws", r["raw_path"]),
                bbox=json.loads(r["bbox_json"]) if r["bbox_json"] else {},
            ))
        except FileNotFoundError as e:
            print(f"  ! skip {r['id'][:8]} : {e}")
    return out


def load_image_b64(path: Path, max_short_side: int | None = None) -> tuple[str, str]:
    """Retourne (b64, media_type). Resize si max_short_side fourni et plus petit."""
    if max_short_side is None:
        data = path.read_bytes()
        media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return base64.b64encode(data).decode(), media

    im = Image.open(path)
    im.load()
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")
    w, h = im.size
    short = min(w, h)
    if short > max_short_side:
        scale = max_short_side / short
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


def recrop_with_margin(pair: Pair, margin_frac: float,
                       edge_mode: str = "hard",
                       output_size: int = 224) -> bytes:
    """Re-crop le raw avec un margin_frac alternatif, en réutilisant le
    bbox du producer (isole la variable margin de la détection). Retourne
    les bytes PNG du nouveau crop."""
    import cv2  # local pour ne pas alourdir le import top-level

    from scan.normalize_snap import CropConfig, _crop_mask_resize_int

    bgr = cv2.imread(str(pair.raw_path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(f"raw illisible : {pair.raw_path}")
    bbox = pair.bbox
    cx = int(bbox["x"] + bbox["w"] / 2.0)
    cy = int(bbox["y"] + bbox["h"] / 2.0)
    r_rim = int(round(bbox["w"] / 2.0 / (1.0 + PRODUCER_MARGIN_FRAC)))

    cfg = CropConfig(margin_frac=margin_frac, edge_mode=edge_mode,
                     output_size=output_size)
    res = _crop_mask_resize_int(bgr, cx, cy, r_rim, method="recrop", config=cfg)
    if res.image is None:
        raise RuntimeError(f"recrop failed : {res.debug}")
    ok, buf = cv2.imencode(".png", res.image)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return bytes(buf)


# ---------------------------------------------------------------------------
# ccproxy call
# ---------------------------------------------------------------------------

def build_user_content(pairs: list[Pair],
                       recrop_margin: float | None = None,
                       edge_mode: str = "hard",
                       output_size: int = 224) -> tuple[list[dict], str]:
    """Construit la liste content (alternance image raw / image crop /
    finalement texte). Retourne (content, user_text).

    Si `recrop_margin` est fourni, le crop envoyé est régénéré sur le raw
    avec un `margin_frac` alternatif (le bbox du producer est réutilisé,
    seule la marge change). Le crop stocké en MinIO n'est PAS modifié."""
    content: list[dict] = []
    descriptions: list[str] = []
    for i, p in enumerate(pairs, start=1):
        raw_b64, raw_media = load_image_b64(p.raw_path, MAX_RAW_SHORT_SIDE)
        if recrop_margin is not None:
            crop_bytes = recrop_with_margin(p, recrop_margin,
                                             edge_mode=edge_mode,
                                             output_size=output_size)
            crop_b64 = base64.b64encode(crop_bytes).decode()
            crop_media = "image/png"
        else:
            crop_b64, crop_media = load_image_b64(p.crop_path, None)
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:{raw_media};base64,{raw_b64}"}})
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:{crop_media};base64,{crop_b64}"}})
        bbox = p.bbox
        descriptions.append(
            f"Paire {i} (Image {2*i-1} = raw, Image {2*i} = crop) : "
            f"asset='{p.short_id}', bbox=({int(bbox.get('x',0))},{int(bbox.get('y',0))},"
            f"w={int(bbox.get('w',0))},h={int(bbox.get('h',0))})"
        )

    if len(pairs) == 1:
        user_text = (
            f"Tu reçois UNE paire (raw, crop).\n"
            f"{descriptions[0]}\n\n"
            f"Réponds par UN seul objet JSON (pas un array)."
        )
    else:
        user_text = (
            f"Tu reçois {len(pairs)} paires (raw, crop) dans l'ordre.\n"
            f"Pour la paire k, Image {{2k-1}} = raw, Image {{2k}} = crop.\n\n"
            + "\n".join(descriptions)
            + f"\n\nRéponds par UN JSON array de {len(pairs)} objets dans "
              f"l'ordre EXACT des paires. Chaque objet doit copier l'`asset` "
              f"correspondant pour permettre la vérification."
        )

    content.append({"type": "text", "text": user_text})
    return content, user_text


def call_ccproxy(pairs: list[Pair], recrop_margin: float | None = None,
                  edge_mode: str = "hard", output_size: int = 224) -> dict:
    content, _ = build_user_content(pairs, recrop_margin=recrop_margin,
                                     edge_mode=edge_mode, output_size=output_size)
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    }
    t0 = time.monotonic()
    req = urlreq.Request(
        CCPROXY_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlreq.urlopen(req, timeout=300) as resp:
        body = resp.read().decode()
    dt = time.monotonic() - t0

    data = json.loads(body)
    raw_text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return {
        "latency_s": dt,
        "raw_text": raw_text,
        "usage": usage,
    }


def parse_response(raw_text: str, expected_pairs: list[Pair]) -> list[dict]:
    """Parse la réponse en list[dict]. Gère smoke (1 obj) et batch (array)."""
    txt = raw_text.strip()
    # Supprime éventuels code fences markdown si Claude se laisse aller.
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:]
        txt = txt.strip()
    parsed = json.loads(txt)
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError(f"Réponse non-list/non-dict : {type(parsed)}")

    # Re-map par short_id si Claude a renvoyé dans le mauvais ordre.
    by_short = {p.short_id: p for p in expected_pairs}
    out: list[dict] = []
    seen: set[str] = set()
    for obj in parsed:
        s = obj.get("asset")
        if s not in by_short:
            raise ValueError(f"asset '{s}' inattendu dans la réponse")
        if s in seen:
            raise ValueError(f"asset '{s}' dupliqué dans la réponse")
        seen.add(s)
        out.append(obj)
    missing = set(by_short.keys()) - seen
    if missing:
        raise ValueError(f"assets manquants dans la réponse : {missing}")
    # Réordonne pour matcher l'ordre d'input.
    by_short_resp = {o["asset"]: o for o in out}
    return [by_short_resp[p.short_id] for p in expected_pairs]


# ---------------------------------------------------------------------------
# HTML debug rendering
# ---------------------------------------------------------------------------

HTML_TPL = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font-family: system-ui; background: #FAFAF8; color: #0E0E1F;
          padding: 24px; max-width: 1400px; margin: 0 auto; }}
  h1 {{ font-size: 20px; margin-bottom: 6px; }}
  .meta {{ font-family: ui-monospace, monospace; font-size: 12px;
            color: #55566C; margin-bottom: 18px; }}
  .panel {{ background: #fff; border: 1px solid #E2E0D6;
             border-radius: 12px; padding: 18px; margin-bottom: 18px; }}
  .panel h2 {{ font-size: 14px; font-family: ui-monospace, monospace;
                margin: 0 0 12px; color: #55566C; }}
  pre {{ background: #F4F3EE; border-radius: 8px; padding: 12px;
          font-size: 12px; overflow-x: auto; white-space: pre-wrap; }}
  .pair {{ display: grid; grid-template-columns: 1fr 1fr 1.2fr;
            gap: 16px; margin-bottom: 24px;
            padding-bottom: 24px; border-bottom: 1px solid #ECEBE4; }}
  .pair:last-child {{ border-bottom: none; }}
  .pair img {{ max-width: 100%; max-height: 360px; object-fit: contain;
                background: #ECEBE4; border-radius: 8px; }}
  .pair .label {{ font-size: 11px; font-family: ui-monospace, monospace;
                   color: #7A7B90; margin-bottom: 4px; text-transform: uppercase; }}
  .verdict {{ font-family: ui-monospace, monospace; font-size: 12px; }}
  .verdict .cat {{ display: inline-block; padding: 3px 8px;
                    border-radius: 4px; color: #fff;
                    font-weight: 700; margin-right: 6px; }}
  .cat-A {{ background: #D14343; }}
  .cat-B {{ background: #E07A2A; }}
  .cat-C {{ background: #8255AC; }}
  .cat-R {{ background: #2A8F8F; }}
  .cat-D {{ background: #5C9F3D; }}
  details {{ margin-top: 12px; }}
  summary {{ cursor: pointer; font-size: 12px; color: #55566C; }}
</style></head>
<body>
<h1>{title}</h1>
<div class="meta">{meta}</div>

<div class="panel">
  <h2>Prompt envoyé (user text)</h2>
  <pre>{user_text}</pre>
  <details><summary>System prompt complet</summary><pre>{system_text}</pre></details>
</div>

<div class="panel">
  <h2>Paires envoyées + verdicts</h2>
  {pairs_html}
</div>

<div class="panel">
  <h2>JSON brut renvoyé</h2>
  <pre>{raw_response}</pre>
</div>
</body></html>
"""


def render_pair_html(pair: Pair, verdict: dict | None,
                     recrop_margin: float | None = None,
                     edge_mode: str = "hard",
                     output_size: int = 224) -> str:
    raw_b64, raw_media = load_image_b64(pair.raw_path, MAX_RAW_SHORT_SIDE)
    if recrop_margin is not None:
        crop_bytes = recrop_with_margin(pair, recrop_margin,
                                         edge_mode=edge_mode,
                                         output_size=output_size)
        crop_b64 = base64.b64encode(crop_bytes).decode()
        crop_media = "image/png"
    else:
        crop_b64, crop_media = load_image_b64(pair.crop_path, None)
    raw_src = f"data:{raw_media};base64,{raw_b64}"
    crop_src = f"data:{crop_media};base64,{crop_b64}"

    if verdict is None:
        verdict_html = "<div class='verdict'>(pas de verdict)</div>"
    else:
        cat = verdict.get("category", "?")
        verdict_html = f"""
          <div class="verdict">
            <span class="cat cat-{cat}">{cat}</span>
            <strong>conf={verdict.get('confidence', '?'):.2f}</strong><br><br>
            <strong>is_coin:</strong> {verdict.get('is_coin')}<br>
            <strong>face:</strong> {verdict.get('face')}<br>
            <strong>is_lot:</strong> {verdict.get('is_lot')}
              (n_coins_visible_in_raw={verdict.get('n_coins_visible_in_raw')})<br>
            <strong>undercrop:</strong> {verdict.get('undercrop_severity')}<br>
            <strong>margin:</strong> {verdict.get('margin_assessment')}<br>
            <strong>crop_quality:</strong> {verdict.get('crop_quality')}<br><br>
            <strong>reasoning:</strong><br>
            <em>{verdict.get('reasoning_fr', '')}</em>
          </div>
        """

    return f"""
      <div class="pair">
        <div>
          <div class="label">Raw — {pair.short_id}</div>
          <img src="{raw_src}" />
        </div>
        <div>
          <div class="label">Crop (224×224)</div>
          <img src="{crop_src}" />
        </div>
        <div>
          <div class="label">Verdict Claude</div>
          {verdict_html}
        </div>
      </div>
    """


def write_html_debug(out_path: Path, *, title: str, pairs: list[Pair],
                     verdicts: list[dict] | None, raw_response: str,
                     user_text: str, usage: dict, latency_s: float,
                     recrop_margin: float | None = None,
                     edge_mode: str = "hard",
                     output_size: int = 224) -> None:
    pairs_html = "\n".join(
        render_pair_html(p, (verdicts[i] if verdicts else None),
                          recrop_margin=recrop_margin,
                          edge_mode=edge_mode,
                          output_size=output_size)
        for i, p in enumerate(pairs)
    )
    meta = (
        f"model={MODEL} | latency={latency_s:.1f}s | "
        f"tokens in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')} | "
        f"cost=${usage.get('anthropic_cost_usd', 0):.4f} | "
        f"N pairs={len(pairs)}"
    )
    html = HTML_TPL.format(
        title=title,
        meta=meta,
        user_text=user_text.replace("<", "&lt;"),
        system_text=SYSTEM_PROMPT.replace("<", "&lt;"),
        pairs_html=pairs_html,
        raw_response=raw_response.replace("<", "&lt;"),
    )
    out_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_smoke(args: argparse.Namespace) -> int:
    conn = sqlite3.connect(_ML_DIR / "state" / "eurio.db")
    conn.row_factory = sqlite3.Row
    pair = fetch_pair(conn, args.asset_id)
    print(f"[smoke] asset={pair.short_id} crop={pair.crop_path.name} raw={pair.raw_path.name}")

    _, user_text = build_user_content([pair])
    print(f"[smoke] calling ccproxy…")
    resp = call_ccproxy([pair])
    print(f"[smoke] latency={resp['latency_s']:.1f}s "
          f"tokens in={resp['usage'].get('prompt_tokens')} "
          f"out={resp['usage'].get('completion_tokens')} "
          f"cost=${resp['usage'].get('anthropic_cost_usd', 0):.4f}")

    try:
        verdicts = parse_response(resp["raw_text"], [pair])
        print(f"[smoke] verdict: {json.dumps(verdicts[0], ensure_ascii=False, indent=2)}")
    except Exception as e:
        print(f"[smoke] ❌ parse failed: {e}")
        print(f"[smoke] raw response:\n{resp['raw_text']}")
        verdicts = None

    out_path = _ML_DIR / "state" / "crop_scores" / f"judge_smoke_{pair.short_id}.html"
    write_html_debug(
        out_path,
        title=f"Judge SMOKE — {pair.short_id}",
        pairs=[pair],
        verdicts=verdicts,
        raw_response=resp["raw_text"],
        user_text=user_text,
        usage=resp["usage"],
        latency_s=resp["latency_s"],
    )
    print(f"[smoke] HTML debug : {out_path}")
    return 0 if verdicts else 2


# ---------------------------------------------------------------------------
# Cohort I/O + markdown de suivi
# ---------------------------------------------------------------------------

_TEST_NAME_RE = __import__("re").compile(r"^t\d{2}_[a-z0-9_]+$")


def load_cohort(path: Path) -> dict:
    """Charge un fichier cohorte au format figé."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for k in ("name", "source_run_id", "asset_ids"):
        if k not in data:
            raise ValueError(f"cohorte mal formée : champ '{k}' manquant")
    return data


def cohort_dir(cohort: dict) -> Path:
    out = _ML_DIR / "state" / "crop_scores" / "judge_tests" / cohort["name"]
    out.mkdir(parents=True, exist_ok=True)
    return out


def cohort_md_path(cohort: dict, cohort_path: Path) -> Path:
    return cohort_path.with_suffix(".md")


def ensure_cohort_md(cohort: dict, cohort_path: Path) -> Path:
    """Crée le markdown de suivi si pas présent. Idempotent."""
    md_path = cohort_md_path(cohort, cohort_path)
    if md_path.exists():
        return md_path
    body = (
        f"# Cohorte `{cohort['name']}`\n\n"
        f"> Cohorte handpicked construite via le selector "
        f"`scripts/crop_exp/cohort_selector.py`.\n"
        f"> JSON canonique : `{cohort_path.relative_to(_ML_DIR.parent)}`\n\n"
        f"- **created_at** : {cohort.get('created_at', 'n/a')}\n"
        f"- **source_run_id** : `{cohort['source_run_id']}`\n"
        f"- **filter** : {json.dumps(cohort.get('filter', {}), ensure_ascii=False)}\n"
        f"- **N assets** : {len(cohort['asset_ids'])}\n"
        f"- **notes** : {cohort.get('notes', '')}\n\n"
        f"## Tests effectués\n\n"
        f"_(rempli automatiquement par `ccproxy_judge test`)_\n\n"
    )
    md_path.write_text(body, encoding="utf-8")
    return md_path


def append_test_to_md(md_path: Path, *, test_name: str, params: dict,
                      summary: dict, sidecar_rel: str, html_rel: str) -> None:
    from collections import Counter

    cat_dist = summary.get("cat_distribution", {})
    margin_dist = summary.get("margin_distribution", {})
    undercrop_dist = summary.get("undercrop_distribution", {})

    block = (
        f"### {test_name} — {summary['timestamp']}\n\n"
        f"- **params** : `{json.dumps(params, ensure_ascii=False)}`\n"
        f"- **batches** : {summary['n_batches']} × {summary['batch_size']} "
        f"= {summary['n_assets']} verdicts ({summary['n_errors']} erreurs)\n"
        f"- **coût** : ${summary['total_cost']:.4f} | "
        f"**latence** : {summary['total_latency']:.0f}s\n"
        f"- **category** : `{json.dumps(dict(sorted(cat_dist.items())))}`\n"
        f"- **margin_assessment** : `{json.dumps(dict(sorted(margin_dist.items())))}`\n"
        f"- **undercrop_severity** : `{json.dumps(dict(sorted(undercrop_dist.items())))}`\n"
        f"- **sidecar** : `{sidecar_rel}`\n"
        f"- **html** : `{html_rel}`\n\n"
    )
    cur = md_path.read_text(encoding="utf-8")
    md_path.write_text(cur + block, encoding="utf-8")


def fetch_pairs_for_cohort(conn: sqlite3.Connection, cohort: dict) -> list[Pair]:
    pairs: list[Pair] = []
    for aid in cohort["asset_ids"]:
        try:
            pairs.append(fetch_pair(conn, aid))
        except (ValueError, FileNotFoundError) as e:
            print(f"  ! skip {aid[:8]} : {e}")
    return pairs


# ---------------------------------------------------------------------------
# Commands : test + compare
# ---------------------------------------------------------------------------

def cmd_test(args: argparse.Namespace) -> int:
    if not _TEST_NAME_RE.match(args.test_name):
        print(f"❌ --test-name doit matcher /^t\\d{{2}}_[a-z0-9_]+$/ "
              f"(ex: t01_baseline, t02_margin_010). reçu : {args.test_name!r}")
        return 1

    cohort_path = Path(args.cohort).resolve()
    cohort = load_cohort(cohort_path)
    print(f"[test {args.test_name}] cohorte={cohort['name']} "
          f"({len(cohort['asset_ids'])} assets)")
    if args.recrop_margin is not None:
        print(f"  RECROP margin_frac={args.recrop_margin}, edge_mode={args.edge_mode}")

    conn = sqlite3.connect(_ML_DIR / "state" / "eurio.db")
    conn.row_factory = sqlite3.Row
    pairs = fetch_pairs_for_cohort(conn, cohort)
    print(f"[test] {len(pairs)} paires loaded")

    out_dir = cohort_dir(cohort)
    json_out = out_dir / f"{args.test_name}.json"
    html_out = out_dir / f"{args.test_name}.html"
    md_path = ensure_cohort_md(cohort, cohort_path)

    all_verdicts: list[dict] = []
    total_cost = 0.0
    total_latency = 0.0
    n_errors = 0
    aggregated_raw_text_parts: list[str] = []
    last_user_text = ""
    last_usage: dict = {}

    n_batches = (len(pairs) + args.batch_size - 1) // args.batch_size
    for bi in range(n_batches):
        batch = pairs[bi * args.batch_size:(bi + 1) * args.batch_size]
        try:
            _, user_text = build_user_content(
                batch, recrop_margin=args.recrop_margin,
                edge_mode=args.edge_mode, output_size=args.output_size,
            )
            last_user_text = user_text
            resp = call_ccproxy(batch, recrop_margin=args.recrop_margin,
                                edge_mode=args.edge_mode,
                                output_size=args.output_size)
            verdicts = parse_response(resp["raw_text"], batch)
            for p, v in zip(batch, verdicts):
                v["asset_id"] = p.asset_id
                all_verdicts.append(v)
            cost = resp["usage"].get("anthropic_cost_usd", 0) or 0
            total_cost += cost
            total_latency += resp["latency_s"]
            last_usage = resp["usage"]
            aggregated_raw_text_parts.append(resp["raw_text"])
            print(f"  batch {bi+1}/{n_batches} ({len(batch)} paires) ok — "
                  f"{resp['latency_s']:.1f}s ${cost:.4f}")
        except Exception as e:
            n_errors += 1
            print(f"  batch {bi+1}/{n_batches} ❌ {e}")
            for p in batch:
                all_verdicts.append({
                    "asset_id": p.asset_id,
                    "asset": p.short_id,
                    "claude_status": "error",
                    "error": str(e),
                })

    # Sidecar JSON.
    payload = {
        "test_name": args.test_name,
        "cohort_name": cohort["name"],
        "cohort_path": str(cohort_path.relative_to(_ML_DIR.parent)),
        "params": {
            "recrop_margin": args.recrop_margin,
            "edge_mode": args.edge_mode,
            "output_size": args.output_size,
            "batch_size": args.batch_size,
            "model": MODEL,
        },
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "n_assets": len(all_verdicts),
        "n_errors": n_errors,
        "total_cost": total_cost,
        "total_latency_s": total_latency,
        "verdicts": all_verdicts,
    }
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[test] sidecar → {json_out}")

    # HTML debug (toutes les paires, tous les verdicts).
    write_html_debug(
        html_out,
        title=f"Judge TEST {args.test_name} — {cohort['name']}"
               + (f" — recrop margin={args.recrop_margin}, edge={args.edge_mode}"
                  if args.recrop_margin is not None else " — baseline (legacy crops)"),
        pairs=pairs,
        verdicts=[v for v in all_verdicts if v.get("claude_status") != "error"],
        raw_response="\n\n----- batch separator -----\n\n".join(aggregated_raw_text_parts),
        user_text=last_user_text,
        usage=last_usage,
        latency_s=total_latency,
        recrop_margin=args.recrop_margin,
        edge_mode=args.edge_mode,
        output_size=args.output_size,
    )
    print(f"[test] html    → {html_out}")

    # Markdown summary.
    from collections import Counter
    ok_verdicts = [v for v in all_verdicts if v.get("claude_status") != "error"]
    summary = {
        "timestamp": payload["timestamp"],
        "n_batches": n_batches,
        "batch_size": args.batch_size,
        "n_assets": len(all_verdicts),
        "n_errors": n_errors,
        "total_cost": total_cost,
        "total_latency": total_latency,
        "cat_distribution": dict(Counter(v.get("category", "?") for v in ok_verdicts)),
        "margin_distribution": dict(Counter(v.get("margin_assessment", "?") for v in ok_verdicts)),
        "undercrop_distribution": dict(Counter(v.get("undercrop_severity", "?") for v in ok_verdicts)),
    }
    append_test_to_md(
        md_path,
        test_name=args.test_name,
        params=payload["params"],
        summary=summary,
        sidecar_rel=str(json_out.relative_to(_ML_DIR.parent)),
        html_rel=str(html_out.relative_to(_ML_DIR.parent)),
    )
    print(f"[test] md      → {md_path}")
    print(f"[test] total cost=${total_cost:.4f}  latency={total_latency:.0f}s  errors={n_errors}")
    print(f"[test] cat={summary['cat_distribution']} margin={summary['margin_distribution']}")
    return 0 if n_errors == 0 else 2


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

COMPARE_HTML_TPL = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font-family: system-ui; background: #FAFAF8; color: #0E0E1F;
          padding: 20px; max-width: 1900px; margin: 0 auto; }}
  h1 {{ font-size: 18px; margin-bottom: 4px; }}
  .meta {{ font-family: ui-monospace, monospace; font-size: 12px;
            color: #55566C; margin-bottom: 18px; }}
  table {{ border-collapse: collapse; width: 100%;
            background: #fff; border: 1px solid #E2E0D6; border-radius: 8px;
            overflow: hidden; }}
  th, td {{ padding: 8px 10px; text-align: left;
             border-bottom: 1px solid #ECEBE4;
             font-size: 12px; vertical-align: top; }}
  th {{ background: #F4F3EE; font-family: ui-monospace, monospace;
         font-weight: 600; color: #55566C; }}
  td.asset {{ font-family: ui-monospace, monospace; }}
  td img {{ width: 64px; height: 64px; object-fit: cover; border-radius: 4px; }}
  .cat {{ display: inline-block; padding: 1px 5px; border-radius: 3px;
           color: #fff; font-weight: 700; font-size: 10px; margin-right: 4px; }}
  .cat-A {{ background: #D14343; }}
  .cat-B {{ background: #E07A2A; }}
  .cat-C {{ background: #8255AC; }}
  .cat-R {{ background: #2A8F8F; }}
  .cat-D {{ background: #5C9F3D; }}
  .pill {{ display: inline-block; padding: 1px 5px; border-radius: 3px;
            font-size: 10px; background: #ECEBE4; color: #55566C;
            font-family: ui-monospace, monospace; }}
  .pill.up {{ background: #5C9F3D22; color: #2A6F25; }}
  .pill.down {{ background: #D1434322; color: #8A2222; }}
  .verdict {{ font-size: 11px; line-height: 1.5; }}
  .verdict em {{ color: #55566C; }}
  .deltas {{ background: #FFF5E0; padding: 12px; border: 1px solid #F0C77B;
              border-radius: 8px; margin-bottom: 14px; font-size: 13px; }}
</style></head>
<body>
<h1>{title}</h1>
<div class="meta">{meta}</div>

<div class="deltas">{deltas_html}</div>

<table>
  <thead><tr>{header_html}</tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</body></html>
"""


def cmd_compare(args: argparse.Namespace) -> int:
    cohort_path = Path(args.cohort).resolve()
    cohort = load_cohort(cohort_path)
    test_names = [t.strip() for t in args.tests.split(",")]
    out_dir = cohort_dir(cohort)

    tests: list[dict] = []
    for tn in test_names:
        p = out_dir / f"{tn}.json"
        if not p.exists():
            print(f"❌ test introuvable : {p}")
            return 1
        tests.append(json.loads(p.read_text(encoding="utf-8")))

    # Index verdicts par (test_name, asset_id).
    by_test: dict[str, dict[str, dict]] = {}
    for t in tests:
        by_test[t["test_name"]] = {v["asset_id"]: v for v in t["verdicts"]}

    conn = sqlite3.connect(_ML_DIR / "state" / "eurio.db")
    conn.row_factory = sqlite3.Row
    pairs = fetch_pairs_for_cohort(conn, cohort)

    # Verdict cell HTML.
    def vcell(v: dict | None) -> str:
        if v is None or v.get("claude_status") == "error":
            return "<em>n/a</em>"
        cat = v.get("category", "?")
        marg = v.get("margin_assessment", "?")
        und = v.get("undercrop_severity", "?")
        q = v.get("crop_quality", "?")
        return (
            f"<div class='verdict'>"
            f"<span class='cat cat-{cat}'>{cat}</span>"
            f"<span class='pill'>marg={marg}</span> "
            f"<span class='pill'>und={und}</span> "
            f"<span class='pill'>q={q}</span><br>"
            f"<em>{v.get('reasoning_fr', '').replace('<', '&lt;')}</em>"
            f"</div>"
        )

    # Header.
    headers = ["asset", "crop"] + [f"{t['test_name']}" for t in tests]
    header_html = "".join(f"<th>{h}</th>" for h in headers)

    # Rows.
    asset_source_map = {p.asset_id: p for p in pairs}
    rows: list[str] = []
    cohort_asset_order = cohort["asset_ids"]
    for aid in cohort_asset_order:
        pair = asset_source_map.get(aid)
        if not pair:
            continue
        img = (f"<img src='http://localhost:8042/sources/ebay/assets/{aid}/file' />")
        cells = [f"<td class='asset'>{aid[:8]}</td>", f"<td>{img}</td>"]
        for t in tests:
            cells.append(f"<td>{vcell(by_test[t['test_name']].get(aid))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    rows_html = "\n".join(rows)

    # Deltas synthétiques.
    from collections import Counter
    deltas_lines: list[str] = ["<strong>Deltas vs " + tests[0]['test_name'] + " (baseline)</strong><br>"]
    baseline = by_test[tests[0]["test_name"]]
    for t in tests[1:]:
        cur = by_test[t["test_name"]]
        margin_changes = Counter()
        cat_changes = Counter()
        for aid in cohort_asset_order:
            b = baseline.get(aid)
            c = cur.get(aid)
            if not b or not c:
                continue
            bm = b.get("margin_assessment")
            cm = c.get("margin_assessment")
            if bm != cm:
                margin_changes[(bm, cm)] += 1
            bcat = b.get("category")
            ccat = c.get("category")
            if bcat != ccat:
                cat_changes[(bcat, ccat)] += 1
        deltas_lines.append(
            f"<br><strong>{t['test_name']}</strong> "
            f"({json.dumps(t['params'], ensure_ascii=False)})<br>"
            f"&nbsp;&nbsp;margin: " +
            (", ".join(f"{a}→{b}: {n}" for (a, b), n in margin_changes.most_common())
             if margin_changes else "<em>aucun changement</em>") + "<br>"
            f"&nbsp;&nbsp;category: " +
            (", ".join(f"{a}→{b}: {n}" for (a, b), n in cat_changes.most_common())
             if cat_changes else "<em>aucun changement</em>")
        )
    deltas_html = "".join(deltas_lines)

    title = f"Compare {len(tests)} tests — {cohort['name']}"
    meta = f"tests: {', '.join(test_names)} · {len(cohort_asset_order)} assets"
    html = COMPARE_HTML_TPL.format(
        title=title, meta=meta,
        header_html=header_html, rows_html=rows_html,
        deltas_html=deltas_html,
    )
    out_html = out_dir / f"compare_{'_vs_'.join(test_names)}.html"
    out_html.write_text(html, encoding="utf-8")
    print(f"[compare] wrote {out_html}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("smoke")
    sp.add_argument("--asset-id", required=True)

    sp = sub.add_parser("test")
    sp.add_argument("--cohort", required=True,
                    help="Path to cohort JSON (ml/state/crop_scores/cohorts/*.json)")
    sp.add_argument("--test-name", required=True,
                    help="Format /^t\\d{2}_[a-z0-9_]+$/ (ex: t01_baseline, t02_margin_010).")
    sp.add_argument("--recrop-margin", type=float, default=None,
                    help="margin_frac alternatif pour re-crop. Si absent: crops legacy MinIO.")
    sp.add_argument("--edge-mode", choices=["hard", "feathered", "none"], default="hard")
    sp.add_argument("--output-size", type=int, default=224,
                    help="Taille du crop carré final (default 224).")
    sp.add_argument("--batch-size", type=int, default=10)

    sp = sub.add_parser("compare")
    sp.add_argument("--cohort", required=True)
    sp.add_argument("--tests", required=True,
                    help="Liste de test_names séparée par virgule. Le 1er = baseline.")

    args = ap.parse_args()
    if args.cmd == "smoke":
        return cmd_smoke(args)
    if args.cmd == "test":
        return cmd_test(args)
    if args.cmd == "compare":
        return cmd_compare(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
