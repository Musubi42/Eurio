"""Build the QA core (3rd dump profile) — hermetic & frozen, derived from eurio.db.

Le dump QA est le 3e profil du pipeline (à côté du dump PROD `build_app_core`).
Différences vs PROD :
  1. SOURCE = eurio.db directement (via get_sqlite_con + les MÊMES builders que la
     projection Supabase) → offline, zéro réseau, fidèle au modèle « tout dérive
     d'eurio.db ».
  2. SUBSET = les ~15 pièces curées dans shared/fixtures/qa_curation.json.
  3. FIGÉ = generated_at forcé à parity_now (horloge figée partagée web↔android).
  4. IMAGES BUNDLÉES = les avers webp locaux (coin_canonical_images.local_path)
     sont copiés à côté des artefacts → captures de parité 100% hermétiques.

Sorties :
  admin/packages/proto/public/data/app_core_qa.json          (proto Vue, mode parité)
  admin/packages/proto/public/data/coin-images/<id>/obverse.webp
  app-android/src/qa/assets/app_core.db                       (Android buildType qa)
  app-android/src/qa/assets/coin-images/<id>/obverse.webp

Réutilise build_json() / build_sqlite() de build_app_core SANS modification : seule
la PRODUCTION du dict `core` change (filtré depuis eurio.db au lieu de Supabase).

Usage::
    python -m export.build_app_core_qa
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_ML_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _ML_ROOT.parent
if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))

from export.app_export.io import get_sqlite_con  # noqa: E402
from export.app_export.builders.coin import build_coin, build_shared_reverse  # noqa: E402
from export.app_export.builders.relational import (  # noqa: E402
    build_design_group,
    build_mint,
    build_coin_mint_release,
    build_coin_credit,
    build_coin_topic,
)
from export.app_export.builders.i18n import (  # noqa: E402
    build_coin_name_i18n,
    build_coin_description_i18n,
)
from export.app_export.builders.coin_price import build_coin_price  # noqa: E402
from export.build_app_core import build_json, build_sqlite, _OFFLINE_LANGS  # noqa: E402

_CURATION_PATH = _REPO_ROOT / "shared" / "fixtures" / "qa_curation.json"
_JSON_PATH = _REPO_ROOT / "admin" / "packages" / "proto" / "public" / "data" / "app_core_qa.json"
_PROTO_IMG_DIR = _REPO_ROOT / "admin" / "packages" / "proto" / "public" / "data" / "coin-images"
_ANDROID_DB_PATH = _REPO_ROOT / "app-android" / "src" / "qa" / "assets" / "app_core.db"
_ANDROID_IMG_DIR = _REPO_ROOT / "app-android" / "src" / "qa" / "assets" / "coin-images"

# Presets de seed du coffre (single-source web↔android, cf. docs/parity/qa-dump.md
# §6.4). Régénérés depuis la curation : FK-safe (eurio_id ⊆ subset) + addedAt figés
# sur parity_now. Lus tels quels par le web (store.seedFixture) ET l'android
# (MainActivity.seedFromFixture). Le symlink android src/qa/assets/fixtures pointe
# vers ce dossier → un seul fichier physique par preset.
_PRESET_POPULATED = _REPO_ROOT / "shared" / "fixtures" / "preset-populated.json"
_PRESET_PROFILE_DEMO = _REPO_ROOT / "shared" / "fixtures" / "preset-profile-demo.json"
_DAY_MS = 86_400_000

# Priorité de source d'avers (la plus fiable d'abord) — miroir d'upload_app_obverse.
_SOURCE_PRIORITY = {"bce_official": 0, "eurlex_jo": 1, "numista": 2}


def load_curation() -> tuple[list[str], str]:
    data = json.loads(_CURATION_PATH.read_text(encoding="utf-8"))
    ids = [c["eurio_id"] for c in data["coins"]]
    return ids, data["parity_now"]


def resolve_local_obverse(con: sqlite3.Connection, ids: list[str]) -> dict[str, str]:
    """eurio_id -> local_path (relatif repo) de l'avers, source la plus prioritaire."""
    rows = con.execute(
        "SELECT eurio_id, source, local_path FROM coin_canonical_images "
        "WHERE role='obverse' AND local_path IS NOT NULL AND eurio_id IN (%s)"
        % ",".join("?" * len(ids)),
        ids,
    ).fetchall()
    best: dict[str, tuple[int, str]] = {}
    for r in rows:
        prio = _SOURCE_PRIORITY.get(r["source"], 99)
        cur = best.get(r["eurio_id"])
        if cur is None or prio < cur[0]:
            best[r["eurio_id"]] = (prio, r["local_path"])
    return {eid: lp for eid, (_, lp) in best.items()}


def build_core_qa(con: sqlite3.Connection, ids: set[str]) -> dict[str, Any]:
    """Construit le dict `core` (même shape que build_app_core.fetch_core) mais
    depuis eurio.db, filtré au sous-ensemble curé. FR+EN seulement (offline_langs)."""
    langs = set(_OFFLINE_LANGS)
    coins = [r for r in build_coin(con) if r["eurio_id"] in ids]
    releases = [r for r in build_coin_mint_release(con) if r.get("parent_type_id") in ids]
    sr_ids = {c.get("shared_reverse_id") for c in coins} - {None}
    dg_ids = {c.get("design_group_id") for c in coins} - {None, ""}
    mint_ids = {r.get("mint_id") for r in releases} - {None}
    return {
        "coins": coins,
        "shared_reverse": [r for r in build_shared_reverse(con) if r["id"] in sr_ids],
        "design_group": [r for r in build_design_group(con) if r["id"] in dg_ids],
        "mint": [r for r in build_mint(con) if r["id"] in mint_ids],
        "coin_mint_release": releases,
        "coin_credit": [r for r in build_coin_credit(con) if r["eurio_id"] in ids],
        "coin_topic": [
            r for r in build_coin_topic(con) if r["eurio_id"] in ids and r.get("lang") in langs
        ],
        "coin_name_i18n": [
            r for r in build_coin_name_i18n(con) if r["eurio_id"] in ids and r.get("lang") in langs
        ],
        "coin_description_i18n": [
            r for r in build_coin_description_i18n(con)
            if r["eurio_id"] in ids and r.get("lang") in langs
        ],
        "coin_price": [
            r for r in build_coin_price(con) if r["eurio_id"] in ids and r.get("kind") == "market"
        ],
    }


def _parity_now_ms(parity_now: str) -> int:
    dt = datetime.fromisoformat(parity_now.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def _seed_collection(core: dict[str, Any], ids: list[str], parity_now_ms: int) -> list[dict[str, Any]]:
    """Une pièce par pays du sous-ensemble, dans l'ordre de curation. addedAt
    réparti à rebours depuis parity_now (24 h entre deux ajouts) → buckets « mois »
    et sparkline « 12 derniers mois » non plats, byte-identiques entre deux runs
    (même formule que l'ancien store.seedFixture web : base - (N-i)*24h)."""
    country_by_id = {c["eurio_id"]: c.get("country") for c in core["coins"]}
    picked: list[str] = []
    seen: set[str] = set()
    for eid in ids:
        country = country_by_id.get(eid)
        if country is None or country in seen:
            continue
        seen.add(country)
        picked.append(eid)
    n = len(picked)
    return [
        {
            "eurioId": eid,
            "addedAt": parity_now_ms - (n - i) * _DAY_MS,
            "valueAtAddCents": None,
            "condition": None,
            "note": None,
        }
        for i, eid in enumerate(picked)
    ]


def regenerate_presets(core: dict[str, Any], ids: list[str], parity_now: str) -> int:
    """Régénère les presets de seed du coffre depuis la curation. Single-source :
    le web (store.seedFixture) ET l'android (seedFromFixture) lisent ces mêmes
    fichiers → parité byte-exacte. Idempotent : seul `collection` est réécrit ;
    les métadonnées éditoriales (name, firstRun, levelOverride) d'un preset
    existant sont préservées."""
    collection = _seed_collection(core, ids, _parity_now_ms(parity_now))
    for path, name in ((_PRESET_POPULATED, "populated"), (_PRESET_PROFILE_DEMO, "profile-demo")):
        if path.exists():
            preset = json.loads(path.read_text(encoding="utf-8"))
        else:
            preset = {"name": name, "firstRun": False, "levelOverride": None}
        preset["collection"] = collection
        path.write_text(json.dumps(preset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(collection)


def copy_obverse(local_path: str, eid: str) -> None:
    src = _REPO_ROOT / local_path
    if not src.exists():
        raise SystemExit(f"[qa-dump] avers local introuvable pour {eid}: {src}")
    for base in (_PROTO_IMG_DIR, _ANDROID_IMG_DIR):
        dst = base / eid / "obverse.webp"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def main() -> int:
    ids, parity_now = load_curation()
    con = get_sqlite_con()
    try:
        core = build_core_qa(con, set(ids))
        found = {c["eurio_id"] for c in core["coins"]}
        missing = [i for i in ids if i not in found]
        if missing:
            raise SystemExit(f"[qa-dump] eurio_ids absents d'eurio.db: {missing}")

        obverse = resolve_local_obverse(con, ids)
        # Injecte obverse_image_url AVANT build_json (build_json copie dict(c)).
        # null = pas d'avers local → le proto bascule sur le fallback SVG (parité).
        for c in core["coins"]:
            eid = c["eurio_id"]
            c["obverse_image_url"] = (
                f"/data/coin-images/{eid}/obverse.webp" if eid in obverse else None
            )

        # JSON proto (generated_at figé sur parity_now).
        payload = build_json(core)
        payload["generated_at"] = parity_now
        _JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        _JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        # Images bundlées (proto public + android assets).
        for eid, lp in obverse.items():
            copy_obverse(lp, eid)

        # SQLite Android (même schéma que prod, subset).
        build_sqlite(core, _ANDROID_DB_PATH)

        # Presets de seed du coffre (single-source web↔android), figés sur parity_now.
        n_seed = regenerate_presets(core, ids, parity_now)
    finally:
        con.close()

    n_img = len(obverse)
    n_no = len(ids) - n_img
    print(f"[qa-dump] {len(core['coins'])} pièces · {n_img} avec image · {n_no} sans (fallback SVG)")
    print(f"[qa-dump] prix market: {len(core['coin_price'])} lignes")
    print(f"[qa-dump] presets seed régénérés: {n_seed} pièces (preset-populated + preset-profile-demo)")
    print(f"[qa-dump] wrote {_JSON_PATH.relative_to(_REPO_ROOT)}")
    print(f"[qa-dump] wrote {_ANDROID_DB_PATH.relative_to(_REPO_ROOT)}")
    print(f"[qa-dump] images → {_PROTO_IMG_DIR.relative_to(_REPO_ROOT)} + {_ANDROID_IMG_DIR.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
