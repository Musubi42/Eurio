"""Generate persistent augmentations for a Lab iteration.

Sprint 1 / D-004 — augmentations are baked once on disk under
``ml/datasets/<numista_id>/augmentations/<iteration_id>/sample_NNN.jpg``.
The training pipeline then reads that snapshot directly (no on-the-fly
recipe), so re-running the same iteration_id yields identical inputs.

Design notes:

- One ``AugmentationPipeline`` per coin, seeded deterministically from
  ``(iteration_seed, numista_id)``. The per-coin seed lets us regenerate
  one coin's snapshot without touching the others (useful when a single
  coin's source images change).
- Training sources per coin = ``<nid>/obverse.{jpg,png}`` (Numista canonical)
  **+ les crops eBay reviewés ``training_eligible=1``** (C4d — cf.
  lab-streamline README §5 « Doctrine A »). Les augmentations sont réparties
  en cyclant sur toutes ces sources réelles (``sources[i % len(sources)]``).
  Captures device : JAMAIS une source de training — ce sont la vérité-terrain
  du bench (`evaluate_real_photos.py` les lit) ; les utiliser ici (a) fuiterait
  l'eval set dans le training (gonflant le R@1 studio) et (b) casserait le mur
  train/bench (Doctrine A). Reverse non plus — le modèle ArcFace ne voit que
  l'avers. Sources du bake : obverse Numista + crops eBay reviewés + réfs
  officielles BCE / EUR-Lex JO (``coin_canonical_images``, avers téléchargé) —
  ces dernières servant de filet pour les classes pauvres en crops eBay.
- Cible par classe (cf. ``docs/cohort-pipeline``) : ``>100`` images, via
  facteur dynamique ``ceil(100/seed)`` par source réelle (foundation/enrichment).
- Output filenames are ``sample_<NNN>.jpg`` zero-padded to 3 digits, as
  documented in ``docs/training-pipeline/filesystem.md``.
- For each iteration we also build a unified training root at
  ``ml/datasets/iterations/<iteration_id>/<eurio_id>/`` whose entries are
  relative symlinks back to the per-coin snapshots. This preserves the
  canonical path while letting torchvision's ImageFolder layout work
  unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from PIL import Image

from serving import coin_lookup
from training.augmentations import AugmentationPipeline
from training.augmentations.recipes import DEFAULT_RECIPE
from training.foundation.enrichment import (
    CANONICAL_REF_SOURCES,
    MIN_REAL,
    projection,
)
from store import Store

DATASETS_DIR = ML_DIR / "datasets"
ITERATION_TRAIN_ROOTS = DATASETS_DIR / "iterations"

OBVERSE_NAMES = ("obverse.jpg", "obverse.png")

# Cible d'images de training par classe : source de vérité UNIQUE partagée avec
# l'affichage cockpit (foundation/enrichment.py). Plus de ×10 codé en dur : le
# facteur est dynamique = ceil(100/seed), appliqué uniformément (voir _target_per_coin).
# MIN_REAL = repère qualité (≥10 crops eBay réels) — n'affecte pas la cible, juste
# un flag report. CANONICAL_REF_SOURCES = réfs officielles (avers) ; numista_api
# exclu (pas de local_path — l'avers Numista est lu sur le FS par _source_images).


@dataclass
class CoinAugReport:
    eurio_id: str
    numista_id: int | None
    written: int
    sources_used: int
    skipped_reason: str | None = None
    n_real_ebay: int = 0          # crops eBay reviewés (training_eligible=1) utilisés
    n_ref_images: int = 0         # réfs officielles BCE / EUR-Lex JO utilisées
    below_floor_real: bool = False  # True si < FLOOR_REAL_EBAY crops eBay réels


def _per_coin_seed(iteration_seed: int, numista_id: int) -> int:
    """Stable per-coin seed derived from the iteration seed + numista_id.

    Hashing keeps the coin-level RNG independent of the iteration RNG so
    regenerating one coin's snapshot doesn't shift the others.
    """
    h = hashlib.sha256(f"{iteration_seed}:{numista_id}".encode("utf-8"))
    return int.from_bytes(h.digest()[:4], "big") & 0x7FFFFFFF


def _source_images(numista_id: int) -> list[Path]:
    """Return the canonical obverse source for this coin, if present.

    Strict obverse-only — see module docstring. Captures are off-limits
    here; they belong to the bench.
    """
    coin_dir = DATASETS_DIR / str(numista_id)
    return [
        coin_dir / name
        for name in OBVERSE_NAMES
        if (coin_dir / name).exists()
    ]


def _ebay_training_sources(eurio_id: str, store: Store) -> list[Path]:
    """eBay crops reviewés ``training_eligible=1`` pour ce coin (C4d).

    Source de training légitime à côté de l'obverse Numista (Doctrine A —
    eBay reviewé = training). Seuls les crops marqués éligibles en review
    (manuel / auto-accept / claude) et présents sur disque qualifient ; les
    captures device restent hors-training (bench-only) et ne sont jamais lues
    ici. Chemins résolus vers le cache local des crops (``enrichment-crops``).
    """
    from shared.storage.local_cache import local_path

    conn = store._connection()  # noqa: SLF001
    # Filtre sur ``a.eurio_id`` (le label TRANCHÉ en review), pas
    # ``si.target_eurio_id`` (la cible de découverte) : si l'admin a réattribué
    # le crop à un autre coin, c'est ce nouveau label qui fait foi pour le train.
    rows = conn.execute(
        """
        SELECT a.storage_path
          FROM image_assets a
          JOIN source_images si ON si.id = a.source_image_id
         WHERE si.source = 'ebay'
           AND a.eurio_id = ?
           AND a.training_eligible = 1
           AND a.storage_status = 'present'
         ORDER BY a.id
        """,
        (eurio_id,),
    ).fetchall()
    paths: list[Path] = []
    for r in rows:
        sp = r[0]
        if not sp:
            continue
        p = local_path("enrichment-crops", sp)
        if p.exists():
            paths.append(p)
    return paths


def _canonical_ref_images(eurio_id: str, store: Store) -> list[Path]:
    """Réfs canoniques officielles (avers) utilisables comme sources de training.

    Filet de sécurité pour les classes pauvres en crops eBay (cf.
    ``docs/cohort-pipeline``) : l'avers officiel BCE / EUR-Lex JO, déjà
    téléchargé localement (``coin_canonical_images.local_path``). Garantit
    qu'une classe jamais scrapée sur eBay ou affamée atteint quand même la
    cible par augmentation. ``numista_api`` est exclu (pas de ``local_path`` —
    l'avers Numista est lu depuis le FS par ``_source_images``). Les chemins
    absents du disque sont ignorés (pas d'erreur bloquante).
    """
    conn = store._connection()  # noqa: SLF001
    placeholders = ",".join("?" * len(CANONICAL_REF_SOURCES))
    rows = conn.execute(
        f"""
        SELECT local_path
          FROM coin_canonical_images
         WHERE eurio_id = ?
           AND role = 'obverse'
           AND source IN ({placeholders})
           AND local_path IS NOT NULL
           AND local_path != ''
         ORDER BY source, local_path
        """,
        (eurio_id, *CANONICAL_REF_SOURCES),
    ).fetchall()
    paths: list[Path] = []
    for r in rows:
        # ``local_path`` est relatif à la racine du repo (ex: 'ml/canonical_images/…').
        p = ML_DIR.parent / r[0]
        if p.exists():
            paths.append(p)
    return paths


@dataclass
class CoinSources:
    """Sources réelles de training d'un coin, ventilées par provenance.

    ``paths`` est l'ordre de bake exact (obverse Numista, puis crops eBay
    reviewés, puis réfs officielles) ; ``total`` = ``len(paths)`` = le *seed*
    au sens ``foundation/enrichment`` (nombre de vues réelles distinctes).
    Définition UNIQUE partagée entre le bake (``generate_for_iteration``) et le
    preflight (``foundation/preflight``) — ne jamais recompter ailleurs.
    """

    n_numista: int
    n_ebay: int
    n_ref: int
    paths: list[Path]

    @property
    def total(self) -> int:
        return len(self.paths)


def real_training_sources(
    eurio_id: str, numista_id: int | None, store: Store
) -> CoinSources:
    """Sources réelles de training d'un coin (avers Numista + eBay reviewés + réfs).

    Source de vérité du *seed* : même collecte que le bake. ``numista_id`` None
    (coin sans mapping) → l'avers Numista FS est simplement absent du pool.
    """
    numista_sources = _source_images(numista_id) if numista_id is not None else []
    real_ebay = _ebay_training_sources(eurio_id, store)
    ref_sources = _canonical_ref_images(eurio_id, store)
    return CoinSources(
        n_numista=len(numista_sources),
        n_ebay=len(real_ebay),
        n_ref=len(ref_sources),
        paths=numista_sources + real_ebay + ref_sources,
    )


def _target_per_coin(n_sources: int, variant_count: int | None) -> int:
    """Cible d'images augmentées d'une classe : facteur dynamique ceil(100/seed).

    Le facteur entier ``ceil(100 / n_sources)`` est appliqué uniformément à
    toutes les sources réelles → projeté = facteur × n_sources, toujours ≥ 100
    (ex. 15 sources → ×7 → 105). ``variant_count`` (réglage de l'itération) agit
    comme plancher optionnel s'il dépasse la cible dynamique. Source de vérité :
    ``foundation/enrichment.py`` (partagée avec l'affichage cockpit).
    """
    _factor, projected = projection(n_sources)
    return max(projected, int(variant_count or 0))


def generate_for_iteration(
    *,
    iteration_id: str,
    store: Store | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[CoinAugReport]:
    """(Re)generate augmentations for every coin in the iteration's cohort.

    Existing snapshots are reused: if ``<nid>/augmentations/<iid>/`` already
    contains the expected number of files, the coin is left untouched.
    Callers that want a forced rebuild should clear the directory first
    (the regenerate endpoint does that).

    ``on_progress(done, total)`` (optional) is called before processing each coin
    — used by the detached bake runner (`run_augmentation.py`) to report progress.
    """
    store = store or Store(ML_DIR / "state" / "eurio.db")
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")

    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")

    if it.augmentations_seed is None:
        raise ValueError(
            f"Iteration {iteration_id!r} has no augmentations_seed — was it created "
            "before the sprint-1 migration?"
        )

    recipe_cfg: dict
    if it.recipe_id:
        recipe = store.get_recipe(it.recipe_id)
        if recipe is None:
            raise ValueError(f"Recipe {it.recipe_id!r} not found")
        recipe_cfg = recipe.config
    else:
        recipe_cfg = DEFAULT_RECIPE

    train_root = ITERATION_TRAIN_ROOTS / iteration_id
    # Staging ImageFolder reconstruit à neuf à chaque appel (cheap — ce ne sont
    # que des symlinks vers les samples persistants). Pooled à la maille
    # design_group : plusieurs eurio_id d'un même groupe partagent UN dossier de
    # classe, donc on vide train_root en amont plutôt que par-coin (sinon le 2e
    # membre du groupe écraserait le 1er). Cf. iteration_runner._launch_training
    # (class_kind="design_group").
    if train_root.exists():
        shutil.rmtree(train_root)
    train_root.mkdir(parents=True, exist_ok=True)
    from training.eval.class_resolver import build_resolver
    _resolver = build_resolver(force_eurio_id=False, db_path=store.db_path)

    # Maille design_group : une classe = COALESCE(design_group_id, eurio_id),
    # et elle s'entraîne sur TOUS ses eurio_id membres — y compris des pièces
    # hors-cohorte (ex. be-1999 nourrit la classe de be-2007 même si seule
    # be-2007 est listée dans la cohorte). On étend donc l'ensemble à baker à
    # l'union des membres des groupes de la cohorte. Le préflight agrège déjà
    # sur ce même ensemble → cohérence préflight ↔ donnée réelle (pas de
    # faux-vert : be-2007 hérite vraiment des crops de be-1999).
    _cohort_descriptors, _ = _resolver.classes_for_eurio_ids(cohort.eurio_ids)
    bake_eurio_ids: list[str] = []
    _seen: set[str] = set()
    for _d in _cohort_descriptors:
        for _eid in _d.eurio_ids:
            if _eid not in _seen:
                _seen.add(_eid)
                bake_eurio_ids.append(_eid)

    reports: list[CoinAugReport] = []
    total = len(bake_eurio_ids)
    for _idx, eurio_id in enumerate(bake_eurio_ids):
        if on_progress is not None:
            on_progress(_idx, total)
        nid = coin_lookup.numista_id_for(eurio_id)
        if nid is None:
            reports.append(
                CoinAugReport(
                    eurio_id=eurio_id,
                    numista_id=None,
                    written=0,
                    sources_used=0,
                    skipped_reason="no numista_id mapping",
                )
            )
            continue

        # Sources réelles de training, par priorité (cf. docs/cohort-pipeline) :
        # avers Numista (FS) + crops eBay reviewés (DB) + réfs officielles
        # BCE / EUR-Lex JO (filet pour les classes pauvres en crops eBay).
        # Collecte UNIQUE partagée avec le preflight (cf. real_training_sources).
        coin_src = real_training_sources(eurio_id, nid, store)
        real_ebay = coin_src.n_ebay
        ref_sources = coin_src.n_ref
        sources = coin_src.paths
        if not sources:
            reports.append(
                CoinAugReport(
                    eurio_id=eurio_id,
                    numista_id=nid,
                    written=0,
                    sources_used=0,
                    skipped_reason="no training source (obverse Numista, crop eBay ni réf BCE/EUR-Lex)",
                    below_floor_real=True,
                )
            )
            continue

        # Cible > 100/classe : ×10 par source réelle, plancher 100 (cf. spec).
        target_per_coin = _target_per_coin(len(sources), it.variant_count)

        out_dir = DATASETS_DIR / str(nid) / "augmentations" / iteration_id
        out_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(out_dir.glob("sample_*.jpg"))
        manifest_samples: list[dict] = []
        if len(existing) >= target_per_coin:
            written = len(existing)
            for i, f in enumerate(existing[:target_per_coin]):
                src_path = sources[i % len(sources)]
                manifest_samples.append({"file": f.name, "source": src_path.name})
        else:
            # Always start clean when we need to (re)generate so we don't end
            # up with a mix of partial old + new samples.
            for f in existing:
                f.unlink()
            seed = _per_coin_seed(it.augmentations_seed, nid)
            pipeline = AugmentationPipeline(recipe_cfg, seed=seed)
            written = 0
            for i in range(target_per_coin):
                src_path = sources[i % len(sources)]
                with Image.open(src_path) as raw:
                    base = raw.convert("RGB")
                    img = pipeline.generate(base, count=1)[0]
                out_path = out_dir / f"sample_{i + 1:03d}.jpg"
                img.save(out_path, "JPEG", quality=92)
                manifest_samples.append({
                    "file": out_path.name,
                    "source": src_path.name,
                })
                written += 1

        # Audit trail: explicit per-coin manifest of which source (obverse ou
        # crop eBay reviewé) fed which baked sample. Cheap (≤target rows, plain
        # dicts), and the only way to verify le mix de sources réelles sans
        # re-lire le code (captures device toujours absentes — Doctrine A).
        manifest = {
            "iteration_id": iteration_id,
            "eurio_id": eurio_id,
            "numista_id": nid,
            "recipe_id": it.recipe_id,
            "seed": _per_coin_seed(it.augmentations_seed, nid),
            "samples": manifest_samples,
            "generated_at": datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
        }
        (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2))

        # Stage symlinks sous la racine d'entraînement → layout ImageFolder
        # standard, UN sous-dossier par CLASSE (maille design_group canonique).
        # Plusieurs eurio_id d'un même groupe écrivent dans le même class_dir →
        # on préfixe le nom du lien par eurio_id pour éviter la collision
        # (sample_001.jpg de be-1999 vs be-2007). Pas de wipe par-coin : le
        # class_dir est partagé, train_root a été vidé en amont.
        _desc = _resolver.for_eurio(eurio_id)
        class_id = _desc.class_id if _desc is not None else eurio_id
        class_dir = train_root / class_id
        class_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(out_dir.glob("sample_*.jpg")):
            link = class_dir / f"{eurio_id}__{f.name}"
            if link.is_symlink() or link.exists():
                link.unlink()
            os.symlink(os.path.relpath(f, class_dir), link)

        reports.append(
            CoinAugReport(
                eurio_id=eurio_id,
                numista_id=nid,
                written=written,
                sources_used=len(sources),
                n_real_ebay=real_ebay,
                n_ref_images=ref_sources,
                below_floor_real=real_ebay < MIN_REAL,
            )
        )

    return reports


def clear_for_iteration(*, iteration_id: str, store: Store | None = None) -> int:
    """Wipe persistent augmentations + the staging root for an iteration.

    Returns the number of per-coin snapshots removed. Used by the regenerate
    endpoint to force a clean rebuild.
    """
    store = store or Store(ML_DIR / "state" / "eurio.db")
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")
    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")

    removed = 0
    for eurio_id in cohort.eurio_ids:
        nid = coin_lookup.numista_id_for(eurio_id)
        if nid is None:
            continue
        out_dir = DATASETS_DIR / str(nid) / "augmentations" / iteration_id
        if out_dir.exists():
            shutil.rmtree(out_dir)
            removed += 1
    train_root = ITERATION_TRAIN_ROOTS / iteration_id
    if train_root.exists():
        shutil.rmtree(train_root)
    return removed


def list_for_iteration(
    *,
    iteration_id: str,
    store: Store | None = None,
) -> list[dict]:
    """Return per-coin lists of augmentation paths (relative to ``ml/``)."""
    store = store or Store(ML_DIR / "state" / "eurio.db")
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")
    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")
    out: list[dict] = []
    for eurio_id in cohort.eurio_ids:
        nid = coin_lookup.numista_id_for(eurio_id)
        samples: list[str] = []
        if nid is not None:
            d = DATASETS_DIR / str(nid) / "augmentations" / iteration_id
            if d.is_dir():
                samples = [
                    str(f.relative_to(ML_DIR)) for f in sorted(d.glob("sample_*.jpg"))
                ]
        out.append(
            {
                "eurio_id": eurio_id,
                "numista_id": nid,
                "samples": samples,
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Bake persistent augmentations for a Lab iteration")
    parser.add_argument("--iteration-id", required=True)
    parser.add_argument(
        "--clear-first",
        action="store_true",
        help="Wipe existing snapshots before regenerating (force rebuild).",
    )
    args = parser.parse_args()

    if args.clear_first:
        clear_for_iteration(iteration_id=args.iteration_id)
    reports = generate_for_iteration(iteration_id=args.iteration_id)
    total_written = sum(r.written for r in reports)
    print(f"Iteration {args.iteration_id}: wrote {total_written} samples across {len(reports)} coin(s)")
    for r in reports:
        if r.skipped_reason:
            print(f"  {r.eurio_id} → SKIP: {r.skipped_reason}")
        else:
            floor = "  ⚠ <10 crops eBay réels" if r.below_floor_real else ""
            print(
                f"  {r.eurio_id} (n{r.numista_id}): {r.written} samples "
                f"({r.sources_used} sources — {r.n_real_ebay} eBay, {r.n_ref_images} réf){floor}"
            )


if __name__ == "__main__":
    main()
