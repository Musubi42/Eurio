"""Génération des pièces manquantes depuis `referential_catalog` — Chunk 2b.

Harmonisation des données (docs/data-harmonization/).

L'audit (Chunk 2a) a montré que `coins` est 159 commémoratives 2 € en retard
sur le catalogue Numista. Ce script aligne `coins` :

  1. **Génération** : pour chaque type Numista 2 € commémo absent de `coins`,
     crée une pièce canonique (eurio_id via `compute_eurio_id`, images dans
     `coin_canonical_images`). Création pure → pas d'entrée au journal.
  2. **Cas BE 2017** : la pièce `be-2017-2eur-200-years-ghent-university` porte
     le `numista_id` 108778 qui est en réalité *Liège*. On la renomme d'après
     son vrai type Numista ; le type Ghent (124813) est créé par l'étape 1.
     L'ancien id est consigné au journal `eurio_id_migrations` (split →
     needs_rematch) pour que les dérivés (gold du bench, etc.) soient re-jugés.

Idempotent : un eurio_id déjà présent est ignoré (collision) ; le cas BE 2017
ne s'applique que si l'ancien id existe encore.

Usage::

    python -m scripts.generate_missing_coins --dry-run
    python -m scripts.generate_missing_coins
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from referential.eurio_referential import compute_eurio_id, slugify  # noqa: E402
from state.store import Store  # noqa: E402

DEFAULT_DB = ROOT / "state" / "eurio.db"
COUNTRY_MAPPING = ROOT / "datasets" / "country_mapping.json"
DATASETS = ROOT / "datasets"

# Cas concret du kickoff : l'entrée bâclée 2017 (slug Gand, numista de Liège).
BE_2017_BAD_ID = "be-2017-2eur-200-years-ghent-university"

# Tables filles dont la PK/FK porte l'eurio_id — re-pointées lors d'un rename.
EURIO_ID_CHILD_TABLES = (
    "coin_names_i18n", "coin_aliases", "coin_cross_refs", "coin_observations",
    "coin_canonical_images", "coin_national_variants", "cohort_members",
)

EXTRA_NAME_TO_ISO2 = {"Germany, Federal Republic of": "DE", "Germany": "DE"}


def _name_to_iso2() -> dict[str, str]:
    mapping = json.loads(COUNTRY_MAPPING.read_text())
    out = {v["name"]: iso2 for iso2, v in mapping.items()}
    out.update(EXTRA_NAME_TO_ISO2)
    return out


def extract_theme(name: str) -> str:
    """Thème (forme d'affichage) depuis un nom Numista.

    « 2 Euros - Philippe (200 years of the University of Ghent) »
        → « 200 years of the University of Ghent »
    « 2 Euros (Treaty of Rome) » → « Treaty of Rome »
    Sans parenthèses : le nom débarrassé de la dénomination en tête.
    """
    groups = re.findall(r"\(([^()]+)\)", name or "")
    if groups:
        return groups[-1].strip()
    return re.sub(r"^\s*\d+\s*Euros?\s*[-–—]?\s*", "", name or "").strip()


def _iso2_of(catalog_country: str | None, name_to_iso2: dict[str, str]) -> str | None:
    return name_to_iso2.get(catalog_country or "")


def _canonical_image_rows(eurio_id: str, nid: str, entry: dict) -> list[tuple]:
    rows: list[tuple] = []
    for role in ("obverse", "reverse"):
        url = entry.get(f"{role}_image_url")
        if not url:
            continue
        local = DATASETS / nid / f"{role}.jpg"
        rows.append(
            (eurio_id, "numista", role, url, str(local.relative_to(ROOT)) if local.is_file() else None)
        )
    return rows


def generate_missing(conn: sqlite3.Connection, *, dry_run: bool) -> dict:
    """Crée une pièce canonique pour chaque type Numista 2 € commémo sans coin."""
    name_to_iso2 = _name_to_iso2()
    existing_ids = {r[0] for r in conn.execute("SELECT eurio_id FROM coins")}
    linked = {
        int(r[0]) for r in conn.execute(
            "SELECT numista_id FROM coins WHERE numista_id IS NOT NULL"
        )
    }
    catalog = conn.execute(
        "SELECT source_native_id, raw_json FROM referential_catalog "
        "WHERE source='numista' AND type='commemorative' AND face_value=2.0"
    ).fetchall()

    now = datetime.now(timezone.utc).isoformat()
    coin_rows: list[tuple] = []
    image_rows: list[tuple] = []
    collisions: list[dict] = []
    unmapped: list[dict] = []
    staged: set[str] = set()

    for cat in catalog:
        nid = cat["source_native_id"]
        if int(nid) in linked:
            continue  # déjà rattaché à une pièce
        entry = json.loads(cat["raw_json"])
        iso2 = _iso2_of(entry.get("country"), name_to_iso2)
        if not iso2:
            unmapped.append({"numista_id": nid, "country": entry.get("country")})
            continue
        year = entry.get("year")
        theme = extract_theme(entry.get("name", ""))
        eurio_id = compute_eurio_id(iso2, year, 2.0, slugify(theme) or "unknown")
        if eurio_id in existing_ids or eurio_id in staged:
            collisions.append({"numista_id": nid, "eurio_id": eurio_id, "theme": theme})
            continue
        staged.add(eurio_id)
        coin_rows.append(
            (
                eurio_id, iso2, json.loads(COUNTRY_MAPPING.read_text()).get(iso2, {}).get("name"),
                year, 2.0, 1, theme, int(nid), "numista", nid, "EUR",
                1 if iso2 in ("VA", "MC") else 0,
                entry.get("obverse_description"), "referenced", now, now,
            )
        )
        image_rows.extend(_canonical_image_rows(eurio_id, nid, entry))

    summary = {
        "n_catalog_unlinked": len(catalog) - len([c for c in catalog if int(c["source_native_id"]) in linked]),
        "n_generated": len(coin_rows),
        "n_canonical_images": len(image_rows),
        "n_collisions": len(collisions),
        "collisions": collisions,
        "n_unmapped": len(unmapped),
        "unmapped": unmapped,
    }
    if dry_run:
        return summary

    conn.executemany(
        "INSERT INTO coins (eurio_id, country, country_name, year, face_value, "
        "is_commemorative, theme, numista_id, ref_source, ref_native_id, currency, "
        "collector_only, design_description, status, imported_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        coin_rows,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO coin_canonical_images "
        "(eurio_id, source, role, url, local_path) VALUES (?, ?, ?, ?, ?)",
        image_rows,
    )
    return summary


def _rename_coin(conn: sqlite3.Connection, old: str, new: str, new_theme: str) -> None:
    """Renomme un eurio_id : la pièce + toutes ses tables filles.

    Séquence compatible FK activées (pas d'ON UPDATE CASCADE sur les enfants,
    et `PRAGMA foreign_keys` serait un no-op dans une transaction) :
    insère la nouvelle ligne, re-pointe les enfants vers elle, supprime
    l'ancienne (désormais sans enfant → la cascade ne supprime rien).
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(coins)")]
    vals = dict(conn.execute("SELECT * FROM coins WHERE eurio_id=?", (old,)).fetchone())
    vals["eurio_id"] = new
    vals["theme"] = new_theme
    vals["updated_at"] = datetime.now(timezone.utc).isoformat()
    conn.execute(
        f"INSERT INTO coins ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        [vals[c] for c in cols],
    )
    for table in EURIO_ID_CHILD_TABLES:
        conn.execute(f"UPDATE {table} SET eurio_id=? WHERE eurio_id=?", (new, old))
    conn.execute("DELETE FROM coins WHERE eurio_id=?", (old,))


def fix_be_2017(conn: sqlite3.Connection, *, dry_run: bool) -> dict:
    """Renomme la pièce 2017 mal étiquetée d'après son vrai type Numista."""
    coin = conn.execute(
        "SELECT eurio_id, numista_id FROM coins WHERE eurio_id=?", (BE_2017_BAD_ID,)
    ).fetchone()
    if coin is None:
        return {"applied": False, "reason": "ancien id absent — déjà corrigé"}

    nid = str(coin["numista_id"])
    cat = conn.execute(
        "SELECT raw_json FROM referential_catalog WHERE source='numista' AND source_native_id=?",
        (nid,),
    ).fetchone()
    if cat is None:
        return {"applied": False, "reason": f"numista {nid} absent du catalogue"}

    real_theme = extract_theme(json.loads(cat["raw_json"]).get("name", ""))
    new_id = compute_eurio_id("BE", 2017, 2.0, slugify(real_theme) or "unknown")
    # L'autre face du split : le type Ghent, créé par generate_missing().
    ghent_id = "be-2017-2eur-200-years-of-the-university-of-ghent"

    plan = {
        "applied": not dry_run,
        "old_id": BE_2017_BAD_ID,
        "renamed_to": new_id,
        "real_theme": real_theme,
        "numista_id": nid,
        "split_sibling": ghent_id,
    }
    if dry_run:
        return plan

    _rename_coin(conn, BE_2017_BAD_ID, new_id, real_theme)

    batch = f"be-2017-split-{uuid.uuid4().hex[:8]}"
    reason = "Entrée 2017 bâclée : slug Gand, numista_id 108778 = Liège. Audit Chunk 2a."
    journal = [
        (batch, "retire", BE_2017_BAD_ID, None, "needs_rematch", "pending", reason, "chunk-2b"),
        (batch, "split", BE_2017_BAD_ID, ghent_id, "needs_rematch", "pending", reason, "chunk-2b"),
        (batch, "split", BE_2017_BAD_ID, new_id, "needs_rematch", "pending", reason, "chunk-2b"),
    ]
    conn.executemany(
        "INSERT INTO eurio_id_migrations "
        "(batch_id, kind, old_eurio_id, new_eurio_id, resolution, status, reason, decided_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        journal,
    )
    plan["journal_batch"] = batch
    return plan


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="N'écrit rien.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    return ap.parse_args(argv)


def _backup(db_path: Path) -> Path:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = db_path.with_name(f"{db_path.name}.bak-prechunk2b-{ts}")
    shutil.copy2(db_path, dst)
    return dst


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.dry_run:
        print(f"Backup : {_backup(args.db).name}")
    store = Store(args.db)
    conn = store._connection()  # noqa: SLF001

    if not args.dry_run:
        conn.execute("BEGIN")
    try:
        gen = generate_missing(conn, dry_run=args.dry_run)
        be = fix_be_2017(conn, dry_run=args.dry_run)
        if not args.dry_run:
            conn.execute("COMMIT")
    except Exception:
        if not args.dry_run:
            conn.execute("ROLLBACK")
        raise

    violations = []
    if not args.dry_run:
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()

    report = {
        "dry_run": args.dry_run,
        "generation": gen,
        "be_2017": be,
        "fk_violations": len(violations),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if violations:
        print("\n⚠️  Violations FK !", file=sys.stderr)
        return 1
    print(f"\n✅ {'dry-run — rien écrit' if args.dry_run else 'génération appliquée'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
