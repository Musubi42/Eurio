"""Migration one-shot vers le mode « local + sync » (local-sync).

Le trou historique : la classification faite en local (Mac/PC) n'a jamais
atteint le canonique VPS. Ce CLI rattrape la divergence AVANT de basculer :

1. tire une réplique fraîche du canonique (fichier temporaire) ;
2. diffe la base locale contre elle sur les COLONNES AUTORITATIVES
   (``image_assets`` : resolution_status, training_eligible, eurio_id, face,
   quality_reason, resolved_at ; ``review_queue`` : status, lane, decided_*) ;
3. pour chaque asset divergent, émet dans la base locale un event synthétique
   ``actor='system', reason='bootstrap_backfill'`` portant les valeurs LOCALES
   (fields complets) → le prochain cycle de sync les pousse au canonique.

Dry-run par défaut (affiche le diff) ; ``--apply`` pour émettre les events.
Séquence PO complète : docs/work-in-progress/local-sync/ (Mac d'abord — sa
divergence monte —, seed du fichier de travail depuis la réplique, backfill
par-dessus, premier sync ; puis le PC).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from store import Store, emit_field_event

from .replica import pull_replica

_ASSET_COLS = (
    "resolution_status", "training_eligible", "eurio_id",
    "face", "quality_reason", "resolved_at",
)
_RQ_COLS = (
    "status", "lane", "lane_source", "kind", "decided_eurio_id", "decided_face",
    "decided_variant_kind", "decided_at", "decided_by", "decision_notes",
)


def _connect_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _diff(local: sqlite3.Connection, canon: sqlite3.Connection) -> dict[str, dict]:
    """{asset_id: {"table.colonne": valeur_locale}} pour tout ce qui diverge.

    Périmètre = assets présents DES DEUX côtés (un asset local inconnu du
    canonique remonte par ``/ingest/run``, pas par le backfill) et divergence
    au niveau du champ (on ne pousse que ce qui diffère — pas de bruit LWW).
    """
    canon_cols = {r[1] for r in canon.execute("PRAGMA table_info(review_queue)")}
    rq_cols = [c for c in _RQ_COLS if c in canon_cols]
    out: dict[str, dict] = {}

    rows = local.execute(
        f"SELECT id, {', '.join(_ASSET_COLS)} FROM image_assets"  # noqa: S608
    ).fetchall()
    for row in rows:
        remote = canon.execute(
            f"SELECT {', '.join(_ASSET_COLS)} FROM image_assets WHERE id=?",  # noqa: S608
            (row["id"],),
        ).fetchone()
        if remote is None:
            continue
        fields = {
            f"image_assets.{c}": row[c]
            for c in _ASSET_COLS if row[c] != remote[c]
        }
        if fields:
            out.setdefault(row["id"], {}).update(fields)

    rq_rows = local.execute(
        f"SELECT image_asset_id, {', '.join(rq_cols)} FROM review_queue"  # noqa: S608
    ).fetchall()
    for row in rq_rows:
        remote = canon.execute(
            f"SELECT {', '.join(rq_cols)} FROM review_queue "  # noqa: S608
            "WHERE image_asset_id=?",
            (row["image_asset_id"],),
        ).fetchone()
        if remote is None:
            # Row locale sans équivalent canonique : si l'asset existe au
            # canonique, les fields suffisent (le replay UPSERT la créera).
            asset_known = canon.execute(
                "SELECT 1 FROM image_assets WHERE id=?",
                (row["image_asset_id"],),
            ).fetchone()
            if asset_known is None:
                continue
            fields = {f"review_queue.{c}": row[c] for c in rq_cols}
        else:
            fields = {
                f"review_queue.{c}": row[c]
                for c in rq_cols if row[c] != remote[c]
            }
        if fields:
            out.setdefault(row["image_asset_id"], {}).update(fields)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m client.sync_bootstrap", description=__doc__,
    )
    parser.add_argument(
        "--db", default=os.environ.get("EURIO_DB_PATH", "state/eurio.db"),
        help="base qui REÇOIT les events de rattrapage (défaut : EURIO_DB_PATH "
             "ou state/eurio.db)",
    )
    parser.add_argument(
        "--from", dest="from_db", default=None,
        help="base portant les DÉCISIONS locales à sauver (défaut : --db). "
             "Cas post-seed : --from <sauvegarde> --db <fichier seedé> — le "
             "canonique de référence devient alors --db lui-même.",
    )
    parser.add_argument(
        "--replica", default=None,
        help="réplique canonique de référence déjà sur disque (sinon : --db si "
             "--from est fourni, sinon pull automatique en tmp)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="émet les events de rattrapage (défaut : dry-run, affiche le diff)",
    )
    args = parser.parse_args(argv)

    local_path = Path(args.db)
    if not local_path.exists():
        print(f"base cible introuvable : {local_path}")
        return 1
    source_path = Path(args.from_db) if args.from_db else local_path
    if not source_path.exists():
        print(f"base source (--from) introuvable : {source_path}")
        return 1

    if args.replica:
        replica_path = Path(args.replica)
    elif args.from_db:
        # Post-seed : le fichier cible vient d'être écrasé par la réplique →
        # il EST l'état canonique de référence.
        replica_path = local_path
    else:
        tmp = Path(tempfile.mkdtemp(prefix="eurio-bootstrap-")) / "canon.db"
        print(f"pull réplique canonique → {tmp} …")
        replica_path = pull_replica(tmp)

    canon = _connect_ro(replica_path)
    local_ro = _connect_ro(source_path)
    diff = _diff(local_ro, canon)
    local_ro.close()
    canon.close()

    n_fields = sum(len(f) for f in diff.values())
    print(f"divergence locale → canonique : {len(diff)} asset(s), {n_fields} champ(s)")
    for asset_id, fields in sorted(diff.items())[:40]:
        print(f"  {asset_id}: {json.dumps(fields, ensure_ascii=False)}")
    if len(diff) > 40:
        print(f"  … et {len(diff) - 40} autres (dry-run tronqué à 40)")

    if not args.apply:
        print("\ndry-run — rien n'a été écrit. Relance avec --apply pour émettre "
              "les events de rattrapage.")
        return 0

    store = Store(local_path)
    conn = store._connection()  # noqa: SLF001
    for asset_id, fields in sorted(diff.items()):
        emit_field_event(
            conn, asset_id=asset_id, reason="bootstrap_backfill",
            actor="system", fields=fields,
        )
    conn.commit()
    print(f"\n{len(diff)} event(s) bootstrap_backfill émis → pousse-les avec "
          "`go-task ml:db:sync` (ou laisse le worker faire).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
