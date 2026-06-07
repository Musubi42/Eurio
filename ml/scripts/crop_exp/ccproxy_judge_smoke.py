"""Smoke test : appel ccproxy en mode vision sur 1 crop, parse le JSON.

But du test : valider que (a) le prompt structuré produit un JSON parseable,
(b) le format des labels est cohérent, (c) le temps de réponse est viable.

Usage::

    python -m scripts.crop_exp.ccproxy_judge_smoke --asset-id <id>
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from urllib import request as urlreq

_ML_DIR = Path(__file__).resolve().parents[2]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from store import Store
from shared.storage.local_cache import local_path


CCPROXY_URL = "http://localhost:3002/v1/chat/completions"
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """Tu es un juge expert en numismatique euro qui évalue la
qualité d'un crop de pièce produit par un pipeline de détection automatique.

On te montre UNE image carrée 224×224 qui est censée être un crop centré
sur une pièce euro. Le crop a été produit en cherchant un cercle plausible
dans une photo eBay (raw) ; le pipeline peut s'être trompé.

Réponds STRICTEMENT par un objet JSON unique, sans markdown, sans
commentaire, avec EXACTEMENT ces champs :

{
  "is_coin": true|false,
  "face": "obverse" | "reverse" | "edge" | "both" | "none",
  "is_lot": true|false,
  "undercrop_severity": "none" | "mild" | "strong",
  "category": "A" | "B" | "C" | "R" | "D",
  "confidence": 0.0-1.0,
  "reasoning": "1 phrase courte"
}

Définitions :
- is_coin : true si l'objet principal est bien une pièce de monnaie (métal,
  ronde, gravures). false si c'est un blason, un sticker, un timbre, du
  texte, une capsule vide, etc.
- face : obverse = côté national (souvent un portrait, un emblème, une
  carte). reverse = côté commun européen (carte d'Europe + valeur). edge =
  tranche. both = on voit les deux faces (rare). none si pas une pièce.
- is_lot : true si on voit plusieurs pièces distinctes sur l'image (album,
  set, planche). false si c'est centré sur UNE seule pièce.
- undercrop_severity : "none" = le rim de la pièce est entièrement visible
  et le crop est tight. "mild" = la pièce sort légèrement du cadre OU le
  crop est un peu large. "strong" = le crop ne montre qu'une portion
  intérieure de la pièce (rim invisible — typique du bug bimétal où on
  vote le ring intérieur).
- category : verdict unique selon notre taxonomie crop-forensics :
    A = pas une pièce (sticker, blason, label, texte, timbre)
    B = pièce visible mais crop bien trop serré (rim manquant, inner feature)
    C = lot multi-pièces
    R = pièce reverse (côté commun européen — inutile pour nous)
    D = obverse bien cadrée (objectif final)
- confidence : à quel point tu es sûr de la catégorie (0=pas du tout, 1=certain).
- reasoning : une phrase de 10-15 mots, en français.
"""


def encode_image(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset-id", required=True)
    args = ap.parse_args()

    store = Store(_ML_DIR / "state" / "eurio.db")
    conn = store._connection()
    r = conn.execute(
        "SELECT storage_path FROM image_assets WHERE id=?",
        (args.asset_id,),
    ).fetchone()
    if not r:
        print(f"asset_id introuvable : {args.asset_id}")
        return 1

    crop_path = local_path("enrichment-crops", r["storage_path"])
    print(f"[ccproxy_judge_smoke] crop = {crop_path}")
    b64 = encode_image(crop_path)
    print(f"  b64 size = {len(b64)} chars")

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text",
                     "text": f"Crop asset_id={args.asset_id[:8]}. Juge selon les règles."},
                ],
            },
        ],
    }

    print("[ccproxy_judge_smoke] sending request…")
    t0 = time.monotonic()
    req = urlreq.Request(
        CCPROXY_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlreq.urlopen(req, timeout=120) as resp:
        body = resp.read().decode()
    dt = time.monotonic() - t0
    print(f"  response in {dt:.1f}s")

    data = json.loads(body)
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    print(f"  tokens in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')} "
          f"cost=${usage.get('anthropic_cost_usd', 0):.4f}")
    print()
    print("=== raw response ===")
    print(content)
    print()
    print("=== parsed JSON ===")
    try:
        parsed = json.loads(content)
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
    except json.JSONDecodeError as e:
        print(f"❌ JSON parse failed: {e}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
