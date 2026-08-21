"""Rejoue la détection sur les annonces eBay dont AUCUNE image n'a rendu de crop.

Outil O7 (`docs/work-in-progress/pipeline-propre/outils/O7-reprocess-zero-crops.md`,
décision D5) : 2 950 annonces sur 7 662 n'ont produit aucun crop, 70 % montrent
une pièce seule plein cadre, et la passe de récupération `score_recover`
(`vision/score_recover.py`) récupère 76 % d'entre elles à la sonde — mais elle
n'a jamais tourné en prod. Ce script l'active, **le dit** (témoin `recover=ON`
dans le log), cible les annonces perdues par état de la classe visée dans la
banque, puis enchaîne la chaîne aval INCHANGÉE (resolve → auto_validate →
enqueue) et pousse le run au canonique comme n'importe quel run.

Zéro appel eBay : les raws sont en MinIO. Zéro écriture SQL custom : tout passe
par `run_detect_crop(retry_zero_crops=True)` et les steps de l'orchestrateur.

Usage (depuis ml/, venv — ou `go-task ml:src:ebay:reprocess-zero -- …`) ::

    .venv/bin/python -m scripts.reprocess_zero_crops --dry-run              # périmètre
    .venv/bin/python -m scripts.reprocess_zero_crops --dry-run --scope all
    .venv/bin/python -m scripts.reprocess_zero_crops --limit 20 --seed 42   # essai
    .venv/bin/python -m scripts.reprocess_zero_crops                        # déficit
    .venv/bin/python -m scripts.reprocess_zero_crops --listing-ids ebay_v1|1107…|0
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from shared.bank_classes import bank_class_ids  # noqa: E402
from sources._base.dedup import _link_source_image_run  # noqa: E402
from sources._base.orchestrator import _maybe_push_run  # noqa: E402
from sources._base.run_logger import start_run  # noqa: E402
from sources._base.steps.auto_validate import run_auto_validate_dino  # noqa: E402
from sources._base.steps.detect_crop import run_detect_crop  # noqa: E402
from sources._base.steps.enqueue import run_enqueue  # noqa: E402
from sources._base.steps.resolve import run_resolve  # noqa: E402
from store import Store, resolve_db_path  # noqa: E402
from vision import normalize_snap  # noqa: E402

logger = logging.getLogger("scripts.reprocess_zero_crops")

SOURCE_ID = "ebay"
ANCHORS_KIND = "2eur_all"

# Cible du chantier : 8 exemplaires `fps` par `class_id` de banque
# (`dino_class_references`, anchors_kind='2eur_all') — décision D1 de
# docs/work-in-progress/pipeline-propre/DECISIONS.md. En dessous, la classe est
# déficitaire et ses annonces perdues valent d'être rejouées (D3 : on ne gonfle
# pas la file des classes pleines). Ne pas recopier ce chiffre ailleurs.
TARGET_EXEMPLARS = 8
# Plafond dur de la banque (`DEFAULT_EXEMPLARS_PER_CLASS`, D1) — sert uniquement
# à séparer « pleine (≥ 10) » de « 8-9 » dans le bilan du périmètre.
FULL_EXEMPLARS = 10

# Défaut résolu par `store.resolve_db_path` : la base que le RESTE de la machine
# lit (`EURIO_DB_PATH` — la réplique sous Direction A), jamais un chemin codé en
# dur. Repli hors devShell : `state/eurio.replica.db` (arbitrage 2026-08-19,
# docstring de `store.resolve_db_path`).
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.replica.db")

CLASS_STATES = ("deficit", "near", "full", "unresolvable")


@dataclass
class LostListing:
    """Une annonce eBay sans aucun crop présent, et l'état de la classe visée."""

    listing: str                         # `substr(source_ref, 1, instr('_img')-1)`
    target_eurio_id: str | None
    listing_country: str | None
    class_state: str                     # l'un de CLASS_STATES
    n_fps: int | None                    # exemplaires fps de la classe de banque (None si unresolvable)
    images: dict[str, str] = field(default_factory=dict)   # source_ref → source_image id

    @property
    def n_images(self) -> int:
        return len(self.images)


def _fps_per_class(conn) -> dict[str, int]:
    """`class_id` → nb d'exemplaires `fps` dans la banque 2eur_all. Une classe
    présente dans la banque (canonique seule) compte 0."""
    rows = conn.execute(
        "SELECT class_id, SUM(method = 'fps') AS n_fps FROM dino_class_references "
        " WHERE anchors_kind = ? GROUP BY class_id",
        (ANCHORS_KIND,),
    ).fetchall()
    return {r["class_id"]: int(r["n_fps"] or 0) for r in rows}


def _class_state(conn, target_eurio_id: str | None, fps: dict[str, int],
                 cache: dict[str, tuple[str, int | None]]) -> tuple[str, int | None]:
    """État de la classe de banque visée par `target_eurio_id`.

    Passe par `bank_class_ids` : une courante non représentante de son groupe
    n'est PAS indexée sous son eurio_id (cf. shared/bank_classes.py) — un filtre
    naïf la dirait « introuvable » et l'exclurait du déficit en silence.
    """
    if not target_eurio_id:
        return "unresolvable", None
    if target_eurio_id in cache:
        return cache[target_eurio_id]
    known = [cid for cid in bank_class_ids(conn, target_eurio_id) if cid in fps]
    if not known:
        state: tuple[str, int | None] = ("unresolvable", None)
    else:
        n = sum(fps[cid] for cid in known)
        if n < TARGET_EXEMPLARS:
            state = ("deficit", n)
        elif n >= FULL_EXEMPLARS:
            state = ("full", n)
        else:
            state = ("near", n)
    cache[target_eurio_id] = state
    return state


def select_lost_listings(
    conn,
    *,
    scope: str = "deficit",
    target_eurio_ids: list[str] | None = None,
    listing_ids: list[str] | None = None,
    limit: int | None = None,
    seed: int = 42,
) -> list[LostListing]:
    """Les annonces « perdues » : aucune image avec un `image_assets` présent, ET
    au moins une image en `crop_status='zero_crops'` avec un raw (`storage_path`).

    Les images rejouées sont TOUTES celles de l'annonce qui ont un raw (le step
    detect ignore de lui-même celles qui n'en ont pas). `scope='deficit'` garde
    les annonces dont la classe de banque a moins de `TARGET_EXEMPLARS` fps ;
    `scope='all'` garde tout, y compris les cibles non résolvables.

    `limit` compte des ANNONCES ; avec `limit`, l'ordre est un mélange
    déterministe (`seed`) avant troncature ; sans, l'ordre est `listing` croissant.
    """
    if scope not in ("deficit", "all"):
        raise ValueError(f"scope inconnu {scope!r} (deficit|all)")
    rows = conn.execute(
        """
        SELECT si.id, si.source_ref, si.target_eurio_id, si.listing_country,
               si.crop_status, si.storage_path,
               substr(si.source_ref, 1, instr(si.source_ref, '_img') - 1) AS listing,
               EXISTS (SELECT 1 FROM image_assets a
                        WHERE a.source_image_id = si.id
                          AND a.storage_status = 'present') AS has_asset
          FROM source_images si
         WHERE si.source = ? AND instr(si.source_ref, '_img') > 0
         ORDER BY listing, si.source_ref
        """,
        (SOURCE_ID,),
    ).fetchall()

    fps = _fps_per_class(conn)
    cache: dict[str, tuple[str, int | None]] = {}
    wanted_targets = set(target_eurio_ids) if target_eurio_ids else None
    wanted_listings = set(listing_ids) if listing_ids else None

    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["listing"], []).append(r)

    out: list[LostListing] = []
    for listing, imgs in groups.items():
        if wanted_listings is not None and listing not in wanted_listings:
            continue
        if any(r["has_asset"] for r in imgs):
            continue
        if not any(r["crop_status"] == "zero_crops" and r["storage_path"] for r in imgs):
            continue
        # La cible est portée par l'annonce ; la première non-NULL fait foi.
        target = next((r["target_eurio_id"] for r in imgs if r["target_eurio_id"]), None)
        if wanted_targets is not None and target not in wanted_targets:
            continue
        state, n_fps = _class_state(conn, target, fps, cache)
        if scope == "deficit" and state != "deficit":
            continue
        country = next((r["listing_country"] for r in imgs if r["listing_country"]), None)
        out.append(LostListing(
            listing=listing, target_eurio_id=target, listing_country=country,
            class_state=state, n_fps=n_fps,
            images={r["source_ref"]: r["id"] for r in imgs if r["storage_path"]},
        ))

    if limit is not None:
        random.Random(seed).shuffle(out)
        out = out[:limit]
    return out


def _print_perimeter(lost: list[LostListing], *, scope: str) -> None:
    n_images = sum(ll.n_images for ll in lost)
    print(f"[reprocess] scope={scope} · {len(lost)} annonce(s) perdue(s) · {n_images} image(s) à rejouer")
    by_country = Counter(ll.listing_country or "?" for ll in lost)
    countries = ", ".join(
        f"{c} {n}" for c, n in sorted(by_country.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    print(f"  par listing_country : {countries or '—'}")
    by_state = Counter(ll.class_state for ll in lost)
    labels = {
        "deficit": f"deficit (<{TARGET_EXEMPLARS} fps)",
        "near": f"{TARGET_EXEMPLARS}-{FULL_EXEMPLARS - 1}",
        "full": f"full (>={FULL_EXEMPLARS})",
        "unresolvable": "unresolvable",
    }
    print("  par état de classe  : " + ", ".join(
        f"{labels[s]} {by_state.get(s, 0)}" for s in CLASS_STATES
    ))
    n_classes = len({ll.target_eurio_id for ll in lost if ll.target_eurio_id})
    print(f"  classes visées      : {n_classes}")


def _summary(conn, run_id: str, image_ids: list[str], *, n_listings: int,
             n_crops_added: int) -> dict:
    ph = ",".join("?" * len(image_ids))
    n_with_crop = conn.execute(
        f"SELECT COUNT(DISTINCT source_image_id) AS n FROM image_assets "
        f" WHERE storage_status = 'present' AND source_image_id IN ({ph})",
        image_ids,
    ).fetchone()["n"] if image_ids else 0
    n_score_recover = conn.execute(
        "SELECT COUNT(*) AS n FROM image_assets "
        " WHERE run_id = ? AND detection_method = 'score_recover'",
        (run_id,),
    ).fetchone()["n"]
    n_zero_again = conn.execute(
        f"SELECT COUNT(*) AS n FROM source_images "
        f" WHERE crop_status = 'zero_crops' AND id IN ({ph})",
        image_ids,
    ).fetchone()["n"] if image_ids else 0
    n_errors = conn.execute(
        "SELECT n_errors FROM source_runs WHERE id = ?", (run_id,)
    ).fetchone()["n_errors"]
    return {
        "n_listings": n_listings,
        "n_images": len(image_ids),
        "n_images_with_crop": int(n_with_crop),
        "n_crops_added": int(n_crops_added),
        "n_score_recover": int(n_score_recover),
        "n_zero_again": int(n_zero_again),
        "n_errors": int(n_errors),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--scope", choices=("deficit", "all"), default="deficit",
                   help="deficit (défaut) : annonces dont la classe de banque a "
                        f"moins de {TARGET_EXEMPLARS} exemplaires fps (D1/D3). "
                        "all : toutes les annonces perdues.")
    p.add_argument("--target-eurio-ids", default=None,
                   help="Restreindre aux annonces visant ces eurio_id (a,b,c).")
    p.add_argument("--listing-ids", default=None,
                   help="Restreindre à ces annonces (clé = source_ref sans le suffixe _imgN, "
                        "séparées par des virgules).")
    p.add_argument("--limit", type=int, default=None,
                   help="Au plus N ANNONCES (mélange déterministe par --seed avant troncature).")
    p.add_argument("--seed", type=int, default=42, help="Graine du mélange sous --limit (défaut 42).")
    p.add_argument("--dry-run", action="store_true",
                   help="Affiche le périmètre et sort sans créer de run.")
    p.add_argument("--force", action="store_true",
                   help="Ouvre le run même si un run eBay est déjà 'running'.")
    p.add_argument("--db", default=None,
                   help=f"Fichier SQLite (défaut : {DB_PATH}, résolu par store.resolve_db_path "
                        "— EURIO_DB_PATH quand la variable est posée). IGNORÉ sous --push.")
    p.add_argument("--push", action="store_true",
                   help="Modèle B : travaille sur une réplique scratch inscriptible (pull "
                        "depuis le VPS). Le push du run au canonique est AUTOMATIQUE dès "
                        "qu'EURIO_API_URL est configuré, avec ou sans ce flag.")
    p.add_argument("--no-push", action="store_true",
                   help="Force le Modèle A (aucun push au canonique) même si EURIO_API_URL est posé.")
    p.add_argument("-v", "--verbose", action="store_true", help="Logs DEBUG.")
    return p


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [s.strip() for s in value.split(",") if s.strip()]
    return items or None


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s",
    )
    if args.push and args.no_push:
        print("ERROR: --push et --no-push sont mutuellement exclusifs.", file=sys.stderr)
        return 1
    if args.push and args.dry_run:
        print("ERROR: --push est incompatible avec --dry-run (rien à pousser).", file=sys.stderr)
        return 1
    push_override: bool | None = False if args.no_push else None

    if args.push:
        if args.db is not None:
            logger.warning("--db %s IGNORÉ : --push est actif, le reprocess travaille sur "
                           "une réplique scratch pull-ée du canonique.", args.db)
        from store import staging_store  # noqa: PLC0415

        store = staging_store(prefix="eurio-reprocess-")
        print(f"[model-b] réplique scratch inscriptible → {store.db_path}")
    else:
        db_path = Path(args.db) if args.db else DB_PATH
        # Le dry-run ne fait que lire : on l'autorise sur la réplique read-only.
        store = Store(db_path, read_only=True) if args.dry_run else Store(db_path)
    conn = store._connection()  # noqa: SLF001

    lost = select_lost_listings(
        conn, scope=args.scope,
        target_eurio_ids=_split_csv(args.target_eurio_ids),
        listing_ids=_split_csv(args.listing_ids),
        limit=args.limit, seed=args.seed,
    )
    _print_perimeter(lost, scope=args.scope)
    if args.dry_run:
        return 0
    if not lost:
        print("[reprocess] rien à rejouer.")
        return 0

    source_image_ids: dict[str, str] = {}
    for ll in lost:
        source_image_ids.update(ll.images)

    # Le témoin : la passe de secours est posée ICI et vérifiée par la fonction
    # que le détecteur lit réellement. Un reprocess qui tourne recover OFF
    # reproduit le même zéro en silence (O7 §« Le remède existe »).
    os.environ["EURIO_CENSUS_RECOVER"] = "1"
    if not normalize_snap._census_recover_enabled():  # noqa: SLF001
        logger.error("recover=OFF : `_census_recover_enabled()` est faux malgré "
                     "EURIO_CENSUS_RECOVER=1 — aucun run créé.")
        return 2
    tau = normalize_snap._census_fragment_tau()  # noqa: SLF001
    logger.info("recover=ON tau=%s scope=%s listings=%d images=%d",
                tau, args.scope, len(lost), len(source_image_ids))

    filters = {
        "reprocess": True, "scope": args.scope, "recover": "on", "tau": tau,
        "n_listings": len(lost), "n_images": len(source_image_ids),
    }
    try:
        with start_run(conn, source=SOURCE_ID, kind="run", filters=filters,
                       force=args.force) as run:
            # Containment par-run (Model B) : les source_images parents ont un
            # run_id first-seen ; sans ce lien, export_run ne transporte ni la
            # mutation crop_status ni les images vers le canonique.
            for sid in source_image_ids.values():
                _link_source_image_run(conn, sid, run.run_id)

            run.set_step("detect")
            det = run_detect_crop(
                conn=conn, run=run, source_id=SOURCE_ID,
                source_image_ids=source_image_ids, retry_zero_crops=True,
            )
            run.set_step("resolve")
            run_resolve(
                conn=conn, run=run, source_id=SOURCE_ID, source_image_ids=source_image_ids,
            )
            run.set_step("auto_validate")
            run_auto_validate_dino(
                conn=conn, run=run, source_id=SOURCE_ID, source_image_ids=source_image_ids,
            )
            run.set_step("enqueue")
            run_enqueue(
                conn=conn, run=run, source_id=SOURCE_ID, source_image_ids=source_image_ids,
            )

            summary = _summary(
                conn, run.run_id, list(source_image_ids.values()),
                n_listings=len(lost), n_crops_added=det.n_crops_added,
            )
            logger.info("[reprocess] bilan run=%s %s", run.run_id, json.dumps(summary))
            run.end("success" if summary["n_errors"] == 0 else "partial",
                    error_summary=json.dumps(summary))
            conn.commit()
            run_id = run.run_id
    except Exception:  # noqa: BLE001
        logger.exception("[reprocess] échec — le run est marqué 'failed'")
        conn.commit()
        return 1

    _maybe_push_run(store, run_id, push=push_override)
    print(f"run_id {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
