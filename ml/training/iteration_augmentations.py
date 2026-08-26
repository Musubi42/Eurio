"""Generate persistent augmentations for a Lab iteration.

Sprint 1 / D-004 — augmentations are baked once on disk under
``ml/datasets/<numista_id>/augmentations/<iteration_id>/sample_NNN.jpg``.
The training pipeline then reads that snapshot directly (no on-the-fly
recipe), so re-running the same iteration_id yields identical inputs.

**Idempotence : sur l'identité des entrées, pas sur le compte de fichiers.**
Le bake ne réutilise un snapshot que si le ``_manifest.json`` posé à côté porte
le même ``inputs_digest`` — recipe + seed + cible + liste ordonnée des sources
(chemin et taille). Sinon il régénère. La version d'avant comparait seulement
``len(existing) >= target`` puis **réécrivait le manifeste** en re-dérivant
``sources[i % len(sources)]`` sur la liste de sources *du moment* : une review
qui ajoutait ou retirait un crop sans changer la cible faisait attribuer les
samples à des sources qui ne les avaient pas produits, sans rien signaler.
Mesuré le 2026-08-16 sur ``4aaac6865ca9`` : samples datés de 02:05 UTC,
manifestes stampés 02:11 UTC par un re-bake qui n'avait régénéré aucune image.
Le digest retient la **taille** et non un sha256 du contenu : une éviction LRU
du cache suivie d'un re-téléchargement rend les mêmes octets, et re-hasher
chaque source à chaque bake annulerait le bénéfice de la réutilisation.

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
    TRAINING_TARGET,
    projection,
)
from store import Store, resolve_db_path

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
    #: L'empreinte des ENTRÉES de CETTE pièce (``_inputs_digest``). Remontée
    #: dans le rapport pour que l'appelant puisse la persister sur l'itération
    #: (migration 0016) sans relire les manifestes sur disque — ils n'existent
    #: que sur la machine qui a baké. ``None`` pour une pièce sautée : elle n'a
    #: pas d'entrées, et son absence DOIT changer le rollup (cf.
    #: :func:`rollup_inputs_digest`).
    inputs_digest: str | None = None


# Schéma du ``_manifest.json`` par pièce. v1 = sans ``inputs_digest`` (on ne peut
# pas prouver que ses samples viennent des sources listées) → toujours régénéré.
MANIFEST_VERSION = 2
MANIFEST_NAME = "_manifest.json"


def _inputs_digest(
    sources: list[Path], *, seed: int, recipe_cfg: dict, target: int
) -> str:
    """Empreinte des entrées d'un bake de pièce.

    Tout ce qui change les images produites y entre : la **configuration** de la
    recette, le seed par-pièce, la cible (elle pilote le nombre ET le cyclage sur
    les sources) et la liste ORDONNÉE des sources — l'ordre compte,
    ``sources[i % len]`` en dépend. Chaque source est identifiée par son chemin
    et sa taille (cf. docstring du module pour le choix taille vs sha256).

    ⚠️ On hache la **config**, pas le ``recipe_id`` : ``PUT /lab/recipes/{id}``
    modifie une recette **en place** (``store.update_recipe``), sans changer son
    id. Hacher l'id laissait donc réutiliser un snapshot produit par l'ANCIENNE
    config pendant que le manifeste et ``experiment_iterations.recipe_id``
    affirment la nouvelle — le mensonge de provenance que ce digest existe pour
    supprimer. Ça couvre aussi le cas ``recipe_id=None`` (``DEFAULT_RECIPE``),
    qui n'entrait pas du tout dans l'empreinte.
    """
    h = hashlib.sha256()
    recipe_fingerprint = json.dumps(recipe_cfg, sort_keys=True, default=str)
    h.update(f"v{MANIFEST_VERSION}|{recipe_fingerprint}|{seed}|{target}\0".encode())
    for p in sources:
        try:
            size = p.stat().st_size
        except OSError:
            size = -1  # source disparue entre la collecte et ici → digest différent
        h.update(f"{p}\0{size}\0".encode())
    return h.hexdigest()


def rollup_inputs_digest(reports: list[CoinAugReport]) -> str:
    """L'empreinte des entrées de TOUTE l'itération, à partir des rapports.

    Migration 0016. La maille de la question — « ces deux modèles ont-ils été
    entraînés sur les mêmes entrées ? » — est l'ITÉRATION ; le détail par pièce
    reste dans les manifestes, où il sert au bake à décider s'il régénère.

    Trois propriétés, et chacune a coûté un raisonnement :

    * **trié par ``eurio_id``**, donc indépendant de l'ordre dans lequel
      ``bake_member_ids`` a rendu les pièces. Sans ça deux bakes identiques
      rendraient deux digests différents et la colonne ne servirait à rien ;
    * **une pièce SAUTÉE compte**, sous la forme ``skip:<motif>``. C'est le
      point qui rend la colonne utile : le pool grossit (5 051 → 6 594 samples
      pour la même cohorte entre le 2026-08-16 et le 2026-08-25), donc une
      classe sans source un jour en a une le lendemain. Si les sautées étaient
      omises, le rollup ne bougerait pas et dirait « mêmes entrées » d'un bake
      qui a gagné une classe ;
    * **la liste des pièces entre dans le hachage**, pas seulement leurs
      digests : ajouter une pièce dont le digest coïncide par hasard avec une
      autre ne doit pas passer inaperçu.
    """
    h = hashlib.sha256()
    h.update(f"rollup-v{MANIFEST_VERSION}\0".encode())
    for r in sorted(reports, key=lambda r: r.eurio_id):
        marque = r.inputs_digest or f"skip:{r.skipped_reason or 'inconnu'}"
        h.update(f"{r.eurio_id}\0{marque}\0".encode())
    return h.hexdigest()


def _reusable_snapshot(
    out_dir: Path, *, digest: str, target: int
) -> bool:
    """Vrai si le snapshot sur disque est PROUVÉ conforme aux entrées courantes.

    Exige un manifeste v2 au bon digest, exactement ``target`` samples, et que
    chaque fichier qu'il liste soit encore là. Au moindre doute on renvoie False
    : régénérer est déterministe (même seed, mêmes sources ⇒ mêmes octets), donc
    le pire coût d'un faux négatif est du temps CPU — alors qu'un faux positif
    laisse une provenance fausse dans le manifeste.
    """
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if manifest.get("version") != MANIFEST_VERSION:
        return False
    if manifest.get("inputs_digest") != digest:
        return False
    samples = manifest.get("samples") or []
    if len(samples) != target:
        return False
    if len(list(out_dir.glob("sample_*.jpg"))) != target:
        return False
    return all((out_dir / s.get("file", "")).is_file() for s in samples)


def bake_member_ids(cohort_eurio_ids: list[str], store: Store):
    """(resolver, eurio_ids RÉELLEMENT bakés) pour une liste de pièces de cohorte.

    Maille design_group : une classe = ``COALESCE(design_group_id, eurio_id)`` et
    elle s'entraîne sur TOUS ses membres — y compris des pièces **hors cohorte**
    (be-1999 nourrit la classe de be-2007 même si seule be-2007 est listée).
    L'ensemble baké est donc l'union des membres des groupes de la cohorte, et il
    est franchement plus grand : mesuré le 2026-08-16, une cohorte de 27 pièces en
    bake 61.

    Fonction partagée **exprès** : le bake, le nettoyage et la galerie doivent
    raisonner sur le MÊME ensemble. Quand `clear_for_iteration` bouclait sur la
    seule cohorte, un « regénérer » laissait intacts les snapshots des membres
    hors cohorte — c'est-à-dire une bonne moitié du dataset.
    """
    from training.eval.class_resolver import build_resolver

    resolver = build_resolver(force_eurio_id=False, db_path=store.db_path)
    descriptors, _ = resolver.classes_for_eurio_ids(cohort_eurio_ids)
    out: list[str] = []
    seen: set[str] = set()
    for d in descriptors:
        for eid in d.eurio_ids:
            if eid not in seen:
                seen.add(eid)
                out.append(eid)
    return resolver, out


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
    # Gate face (P3 improvement-loop) : le REVERS confirmé n'entre jamais au
    # train (côté carte commun à toutes les 2€ → nuisible à une classe d'avers).
    # NULL / 'unknown' passent — présumés avers ; la passe de face du scan
    # (training/training_set_scan.py, P2) les résout en amont. Aligné sur
    # l'export legacy (scripts/build_arcface_dataset.py).
    rows = conn.execute(
        """
        SELECT a.storage_path
          FROM image_assets a
          JOIN source_images si ON si.id = a.source_image_id
         WHERE si.source = 'ebay'
           AND a.eurio_id = ?
           AND a.training_eligible = 1
           AND a.storage_status = 'present'
           AND (a.face IS NULL OR a.face != 'reverse')
           -- Hold-out d'évaluation (juge-et-banc, migration 0014) : un crop
           -- réservé à un corpus d'éval n'entre JAMAIS au train. Le prédicat
           -- est écrit ici ET dans `foundation/anchors.py` — les deux
           -- collectes divergent (intersection 2888, ArcFace seul 79, DINO
           -- seul 1), il n'existe pas de point unique en amont.
           AND a.eval_corpus IS NULL
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


def _target_per_coin(
    n_sources: int, variant_count: int | None, target: int | None = None
) -> int:
    """Cible d'images augmentées d'une classe : facteur dynamique ceil(100/seed).

    Le facteur entier ``ceil(100 / n_sources)`` est appliqué uniformément à
    toutes les sources réelles → projeté = facteur × n_sources, toujours ≥ 100
    (ex. 15 sources → ×7 → 105). ``variant_count`` (réglage de l'itération) agit
    comme plancher optionnel s'il dépasse la cible dynamique. Source de vérité :
    ``foundation/enrichment.py`` (partagée avec l'affichage cockpit).
    """
    _factor, projected = projection(n_sources, target)
    return max(projected, int(variant_count or 0))


def generate_for_iteration(
    *,
    iteration_id: str,
    store: Store | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[CoinAugReport]:
    """(Re)generate augmentations for every coin in the iteration's cohort.

    Un snapshot n'est réutilisé que s'il est **prouvé conforme** aux entrées
    courantes (manifeste v2 au bon ``inputs_digest``, cf. ``_reusable_snapshot``
    et le docstring du module). Toute dérive des sources, de la recette, du seed
    ou de la cible régénère la pièce — y compris quand le nombre de fichiers,
    lui, n'aurait pas bougé. Les snapshots v1 (sans digest) sont toujours
    régénérés une fois. Un rebuild inconditionnel reste possible en vidant le
    dossier d'abord (ce que fait l'endpoint regenerate).

    ``on_progress(done, total)`` (optional) is called before processing each coin
    — used by the detached bake runner (`run_augmentation.py`) to report progress.
    """
    store = store or Store(resolve_db_path(ML_DIR / "state" / "eurio.db"))
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

    # Seuils GELÉS à la création de l'itération (store/thresholds →
    # training_config_json). On bake avec la règle sous laquelle l'itération a
    # été admise, pas avec celle d'aujourd'hui : sinon un rebake silencieux
    # changerait la cible d'un run déjà mesuré.
    _cfg = it.training_config or {}
    frozen_target = int(_cfg.get("training_target", TRAINING_TARGET))
    frozen_min_real = int(_cfg.get("min_real", MIN_REAL))

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
    _resolver, bake_eurio_ids = bake_member_ids(cohort.eurio_ids, store)

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
        target_per_coin = _target_per_coin(
            len(sources), it.variant_count, frozen_target
        )

        out_dir = DATASETS_DIR / str(nid) / "augmentations" / iteration_id
        out_dir.mkdir(parents=True, exist_ok=True)
        seed = _per_coin_seed(it.augmentations_seed, nid)
        digest = _inputs_digest(
            sources, seed=seed, recipe_cfg=recipe_cfg, target=target_per_coin
        )

        if _reusable_snapshot(out_dir, digest=digest, target=target_per_coin):
            # Entrées identiques et provenance déjà prouvée : on ne régénère pas
            # et on NE RÉÉCRIT PAS le manifeste — le réécrire ne pourrait que
            # remplacer une provenance vraie par une provenance re-devinée.
            written = target_per_coin
        else:
            # Le manifeste part EN PREMIER : entre l'effacement des samples et
            # sa réécriture en fin de boucle, un crash du job détaché laisserait
            # sur disque un manifeste décrivant des fichiers qui ne sont plus
            # ceux-là. Mieux vaut pas de preuve qu'une preuve fausse — et
            # l'absence de manifeste force de toute façon la régénération.
            (out_dir / MANIFEST_NAME).unlink(missing_ok=True)
            # Always start clean when we need to (re)generate so we don't end
            # up with a mix of partial old + new samples — ni de reliquats quand
            # la cible BAISSE (le staging symlinke tout ``sample_*.jpg``).
            for f in sorted(out_dir.glob("sample_*.jpg")):
                f.unlink()
            pipeline = AugmentationPipeline(recipe_cfg, seed=seed)
            manifest_samples: list[dict] = []
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

            # Audit trail: explicit per-coin manifest of which source (obverse
            # ou crop eBay reviewé) fed which baked sample. Écrit UNIQUEMENT
            # par le chemin qui produit les images — c'est ce qui rend sa
            # provenance vérifiable (captures device toujours absentes —
            # Doctrine A). ``inputs_digest`` + ``sources`` permettent au bake
            # suivant de décider sans re-deviner.
            manifest = {
                "version": MANIFEST_VERSION,
                "iteration_id": iteration_id,
                "eurio_id": eurio_id,
                "numista_id": nid,
                "recipe_id": it.recipe_id,
                "seed": seed,
                "target": target_per_coin,
                "inputs_digest": digest,
                "sources": [
                    {
                        "path": str(p),
                        "name": p.name,
                        "size": p.stat().st_size if p.exists() else None,
                    }
                    for p in sources
                ],
                "samples": manifest_samples,
                "generated_at": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
            }
            (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))

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
                below_floor_real=real_ebay < frozen_min_real,
                # Remontée QUE le snapshot ait été régénéré ou réutilisé : dans
                # les deux cas c'est bien l'empreinte des entrées courantes
                # (`_reusable_snapshot` a justement prouvé qu'elles n'ont pas
                # bougé). Ne la poser que sur la branche « régénéré » ferait
                # dire au rollup « entrées inconnues » d'un bake parfaitement
                # à jour — le pire des deux mondes.
                inputs_digest=digest,
            )
        )

    return reports


def clear_for_iteration(*, iteration_id: str, store: Store | None = None) -> int:
    """Wipe persistent augmentations + the staging root for an iteration.

    Returns the number of per-coin snapshots removed. Used by the regenerate
    endpoint to force a clean rebuild.

    Balaie l'ensemble RÉELLEMENT baké (``bake_member_ids``), pas la seule
    cohorte : sinon « regénérer » laisse en place les snapshots des membres
    hors cohorte tirés par la maille design_group — plus de la moitié du
    dataset sur une grande cohorte.
    """
    store = store or Store(resolve_db_path(ML_DIR / "state" / "eurio.db"))
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")
    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")

    removed = 0
    _resolver, bake_ids = bake_member_ids(cohort.eurio_ids, store)
    for eurio_id in bake_ids:
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
    """Return per-coin lists of augmentation paths (relative to ``ml/``).

    Sur l'ensemble RÉELLEMENT baké (``bake_member_ids``) : la galerie doit
    montrer ce qui entre dans le dataset, membres hors cohorte compris —
    sinon elle cache les pièces qui en constituent la plus grosse part.
    """
    store = store or Store(resolve_db_path(ML_DIR / "state" / "eurio.db"))
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")
    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")
    out: list[dict] = []
    _resolver, bake_ids = bake_member_ids(cohort.eurio_ids, store)
    for eurio_id in bake_ids:
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


def class_sample_counts(
    *,
    iteration_id: str,
    store: Store | None = None,
) -> dict[str, int]:
    """Total baked samples per CLASS (``COALESCE(design_group_id, eurio_id)``).

    Le bake bake par MEMBRE : un design_group multi-millésimes voit ses crops
    bakés sur le millésime qui les porte (ex. ``be-1999``), pas forcément sur le
    membre listé dans la cohorte (ex. ``be-2007``, sans crops propres). La maille
    de vérité du training étant la CLASSE, on somme les samples de TOUS les
    membres du groupe — miroir exact de l'expansion ``bake_eurio_ids`` du bake.
    Sert au garde-fou de launch-training (cf. ``IterationRunner``).
    """
    store = store or Store(resolve_db_path(ML_DIR / "state" / "eurio.db"))
    it = store.get_iteration(iteration_id)
    if it is None:
        raise ValueError(f"Iteration {iteration_id!r} not found")
    cohort = store.get_cohort(it.cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {it.cohort_id!r} not found")

    from training.eval.class_resolver import build_resolver
    resolver = build_resolver(force_eurio_id=False, db_path=store.db_path)
    descriptors, _ = resolver.classes_for_eurio_ids(cohort.eurio_ids)

    counts: dict[str, int] = {}
    for d in descriptors:
        total = 0
        for member in d.eurio_ids:
            nid = coin_lookup.numista_id_for(member)
            if nid is None:
                continue
            sample_dir = DATASETS_DIR / str(nid) / "augmentations" / iteration_id
            if sample_dir.is_dir():
                total += sum(1 for _ in sample_dir.glob("sample_*.jpg"))
        counts[d.class_id] = total
    return counts


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
