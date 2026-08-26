"""P4 — le gold du banc d'encodeurs : figé, versionné, sans aucune prédiction.

POURQUOI CE MODULE EXISTE
-------------------------
Le banc multi-encodeurs reconstruisait son jeu d'évaluation par un ``SELECT``
sur ``review_queue`` (``ml/scripts/bench_encoder_dino.py:_load_labeled``), une
table **vivante** : la review tranche des crops tous les jours. Deux runs à deux
semaines d'écart ne mesuraient donc pas la même chose, et rien ne le signalait —
la seule trace de l'écart était un nombre de crops qui bougeait dans un log
stderr. Ce module fige la population une fois pour toutes, lui donne une
version de contenu, et rend tout écart mesurable (``diff_gold``).

CE QUE LE MANIFESTE CONTIENT — ET CE QU'IL NE CONTIENDRA JAMAIS
---------------------------------------------------------------
Uniquement ``(asset_id, vérité, provenance)``. **Aucune prédiction** : ni
``top1``, ni similarité, ni ``spread``, ni jointure sur
``image_asset_dino_predictions``. C'est ce qui rend le gold indépendant de P3
(le backfill des 12 454 prédictions périmées) : il peut être figé aujourd'hui et
rester valable après. Les prédictions vivent dans ``encoder_bench_predictions``,
par run — pas ici.

OÙ VIT LE FICHIER, ET POURQUOI IL EST COMMITTÉ
-----------------------------------------------
``ml/state/validation_gold/encoder_bench_gold.jsonl``, **committé**, comme son
voisin ``verdict_gold.jsonl`` (tracké dans git ; ``git ls-files
ml/state/validation_gold/``). Trois raisons :

1. Un gold non committé n'est pas un gold : deux machines ne compareraient pas
   le même jeu, et c'est précisément le défaut qu'on corrige.
2. La taille est du même ordre que le précédent — 1 958 lignes / 855 ko,
   contre 1 009 lignes / 334 ko pour ``verdict_gold.jsonl`` (``ls -la
   ml/state/validation_gold/``). Le
   ``.gitignore`` sort ``ml/state/*.npz`` et les bases, **pas**
   ``ml/state/validation_gold/*.jsonl`` (vérifié : ``git check-ignore -v`` ne
   matche pas).
3. Le fichier est append-only en pratique : la review ne dé-décide pas un crop.
   Ses diffs git resteront lisibles.

CHIFFRES MESURÉS LE 2026-08-19 SUR ``ml/state/eurio.replica.db``
------------------------------------------------------------------
Requête (celle-là même que ``build_gold`` exécute, cf. ``SELECTION_SQL``) ::

    SELECT COUNT(*)
      FROM review_queue rq
      JOIN image_assets a  ON a.id = rq.image_asset_id
      JOIN source_images s ON s.id = a.source_image_id
     WHERE rq.status = 'done' AND rq.decided_eurio_id IS NOT NULL
       AND a.storage_path IS NOT NULL;
    -- 1958

    ... AND a.training_eligible = 1;                        -- 1911
    SELECT COUNT(DISTINCT rq.decided_eurio_id) ...;         -- 194

Les trois nombres attendus par la spec sont retrouvés à l'unité près. Détail
utile : ``training_eligible`` ne vaut que 0 (47 crops) ou 1 (1 911), jamais
NULL ; et les 194 classes sont les mêmes avec ou sans le filtre — aucune classe
n'est portée exclusivement par des crops non éligibles.

POURQUOI ``training_eligible`` EST UNE COLONNE ET PAS UN FILTRE
-----------------------------------------------------------------
Un crop ``training_eligible=0`` a quand même été **tranché par un humain** : sa
vérité est aussi bonne que celle des autres. Le drapeau dit « ne pas
l'ENTRAÎNER » (flou, cadrage, doublon) — pas « on ne sait pas ce que c'est ».
Or le banc mesure un encodeur GELÉ en zero-shot : il n'entraîne rien. Exclure
ces 47 crops reviendrait à retirer du banc les cas difficiles, exactement ceux
qui séparent deux encodeurs. Et le choix inverse — les inclure d'office —
ne doit pas non plus être imposé à l'appelant. D'où la colonne : le manifeste
enregistre les deux populations, ``bench_encoder_dino`` décidera (et son choix
sera tracé dans ``encoder_bench_runs``), sans jamais avoir à re-requêter la base.

LE PIÈGE ``class_id``
---------------------
La banque ``2eur_all`` n'indexe pas une pièce courante sous son ``eurio_id``
mais sous celui du **représentant** de son groupe de dessin (cf.
``shared/bank_classes.py``). Mesuré ce jour sur ce gold : 194 ``eurio_id``
distincts se replient sur **188** ``class_id`` de banque, et **8 classes / 105
crops** ont un ``class_id`` différent de leur ``eurio_id`` (dont
``at-2008-…-2nd-map`` → ``at-2002-…-1st-map``, 82 crops à lui seul). Un gold
qui aurait mis ``eurio_id`` dans ``class_id`` aurait donc compté 105 crops
faux sur 1 958 (5,4 %) sans rien signaler — un recall plancher de 94,6 %.

LE PIÈGE ``truth_country``
--------------------------
Le pays du gold est celui de la **décision** (``decided_eurio_id[:2]``), jamais
celui de la cible du listing eBay (``source_images.target_eurio_id[:2]``).
Mesuré le 2026-08-19 sur la réplique : les deux divergent sur **33 crops** et la
cible est **nulle sur 209** (10,7 %) — requête complète dans la docstring de
``_truth_country``. Comme ``encoder_bench_runs.country_recall1/5`` est le
critère de départage entre deux encodeurs proches, un label pays faux à 1,7 %
est du même ordre que l'écart cherché. Le champ est **non nullable** : une
décision porte toujours son ISO2.

Conséquence assumée : ce correctif **change le ``gold_version``** — le gold
committé a été régénéré, et un manifeste d'avant correctif (champ
``target_country``) est refusé bruyamment par ``load_gold``.

Contrat d'import : **stdlib + ``shared.bank_classes`` + ``shared.storage.local_cache``**.
Ni numpy, ni torch, ni timm : ce module doit s'importer partout, y compris dans
l'image lean.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_ML_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = _ML_ROOT / "state" / "validation_gold" / "encoder_bench_gold.jsonl"

def _default_db() -> Path:
    """La base à LIRE, ``EURIO_DB_PATH`` d'abord, la RÉPLIQUE en repli.

    Même convention que ``bench_encoder_dino.default_db`` — et jamais
    ``state/eurio.db``, base de travail pré-flip qui peut être périmée de
    milliers de lignes. Résolu à l'appel, pas à l'import, pour qu'un test qui
    pose ``EURIO_DB_PATH`` soit entendu.

    Réimplémenté ici plutôt qu'importé de ``store`` : le contrat d'import de ce
    module est stdlib + ``shared.bank_classes`` + ``shared.storage.local_cache``,
    et ``store/__init__`` tire une dizaine de mixins métier.
    """
    env = os.environ.get("EURIO_DB_PATH")
    return Path(env) if env else _ML_ROOT / "state" / "eurio.replica.db"


#: Bucket MinIO par DÉFAUT des crops de review. ⚠️ Ce n'est plus le seul : un
#: crop réservé à un corpus d'évaluation vit dans ``eval-corpus`` (juge-et-banc,
#: D9). Le bucket se DÉRIVE de la clé (``bucket_for_key``) — ne le hardcode pas.
CROPS_BUCKET = "enrichment-crops"

#: Le texte EXACT de la sélection, recopié dans le sidecar ``.meta.json`` pour
#: qu'un lecteur dans six mois sache ce qui a été retenu sans relire ce fichier.
SELECTION_SQL = """
SELECT rq.image_asset_id            AS asset_id,
       rq.decided_eurio_id          AS truth_eurio_id,
       a.storage_path               AS storage_path,
       COALESCE(rq.decided_face, a.face) AS face,
       rq.decided_at                AS decided_at,
       rq.decided_by                AS decided_by,
       rq.kind                      AS review_kind,
       COALESCE(a.training_eligible, 0) AS training_eligible
  FROM review_queue rq
  JOIN image_assets a  ON a.id = rq.image_asset_id
  JOIN source_images s ON s.id = a.source_image_id  -- restreint la POPULATION, ne fournit plus aucune colonne
 WHERE rq.status = 'done'
   AND rq.decided_eurio_id IS NOT NULL
   AND a.storage_path IS NOT NULL
 ORDER BY rq.image_asset_id
""".strip()


@dataclass(frozen=True)
class GoldCrop:
    """Une ligne du manifeste. Aucun champ n'est une prédiction."""

    asset_id: str
    truth_eurio_id: str
    class_id: str
    storage_path: str
    truth_country: str
    face: str | None
    decided_at: str
    decided_by: str | None
    review_kind: str | None
    training_eligible: int


_COUNTRY_RE = re.compile(r"^([a-z]{2})-")


def _truth_country(asset_id: str, truth_eurio_id: str) -> str:
    """L'ISO2 de la VÉRITÉ TRANCHÉE — jamais celui de la cible du scrape.

    Le gold portait ``source_images.target_eurio_id[:2]``, c'est-à-dire la pièce
    que le listing eBay VISAIT. Mesuré le 2026-08-19 sur
    ``ml/state/eurio.replica.db``, sur les 1 958 crops du gold ::

        SELECT COUNT(*),
               SUM(lower(substr(s.target_eurio_id,1,2))
                   <> lower(substr(rq.decided_eurio_id,1,2))),
               SUM(s.target_eurio_id IS NULL)
          FROM review_queue rq
          JOIN image_assets a  ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
         WHERE rq.status = 'done' AND rq.decided_eurio_id IS NOT NULL
           AND a.storage_path IS NOT NULL;
        -- 1958 | 33 | 209

    **33 pays faux** (be→de ×5, es→de ×2, cy→gr, fr→de…) et **209 nuls**
    (10,7 %). Or ``encoder_bench_runs.country_recall1/5`` est le critère de
    départage entre deux encodeurs proches : 1,7 % de bruit d'étiquetage est du
    même ordre que l'écart cherché, et 10,7 % de bande absente en est un ordre
    au-dessus. La vérité était disponible gratuitement sur la même ligne.

    Le champ est donc **non nullable** : une décision porte toujours son pays.
    Un ``eurio_id`` qui ne commence pas par ``xx-`` est une corruption de
    donnée, pas un cas limite — on lève, on ne rend pas ``None``. Contrôlé le
    2026-08-19 : ``… AND rq.decided_eurio_id NOT GLOB '[a-z][a-z]-*'`` → **0**.
    """
    m = _COUNTRY_RE.match((truth_eurio_id or "").lower())
    if not m:
        raise ValueError(
            f"{asset_id} : decided_eurio_id={truth_eurio_id!r} n'a pas de "
            "préfixe pays ISO2 ; le gold refuse d'inventer une bande pays."
        )
    return m.group(1)


def _bank_class_id(conn: sqlite3.Connection, eurio_id: str) -> str:
    """L'identifiant SOUS LEQUEL LA BANQUE INDEXE cette pièce.

    ``shared.bank_classes.bank_class_ids`` rend ``[eurio_id]`` (commémorative,
    ou courante déjà représentante) ou ``[eurio_id, représentant]``. Le gold a
    besoin d'**un** identifiant, pas d'un filtre ``IN (…)`` : c'est le dernier
    élément, c'est-à-dire le représentant quand il existe.

    ⚠️ Écart assumé avec la spec, qui suggérait ``bank_class_ids_for_many`` :
    cette fonction rend une **union dédupliquée sur une cohorte**, elle perd
    l'association crop → classe dont le gold a besoin. On appelle donc
    ``bank_class_ids`` par ``eurio_id`` distinct, mémoïsé par l'appelant.
    """
    from shared.bank_classes import bank_class_ids  # noqa: PLC0415

    return bank_class_ids(conn, eurio_id)[-1]


def build_gold(conn: sqlite3.Connection) -> list[GoldCrop]:
    """Le manifeste, lu depuis une connexion (read-only suffit).

    Trié par ``asset_id`` : la sortie est déterministe, donc diffable, donc
    hashable sans surprise.
    """
    previous_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(SELECTION_SQL).fetchall()
        cache: dict[str, str] = {}
        out: list[GoldCrop] = []
        for r in rows:
            truth = r["truth_eurio_id"]
            if truth not in cache:
                cache[truth] = _bank_class_id(conn, truth)
            out.append(
                GoldCrop(
                    asset_id=r["asset_id"],
                    truth_eurio_id=truth,
                    class_id=cache[truth],
                    storage_path=r["storage_path"],
                    truth_country=_truth_country(r["asset_id"], truth),
                    face=r["face"],
                    decided_at=r["decided_at"] or "",
                    decided_by=r["decided_by"],
                    review_kind=r["review_kind"],
                    training_eligible=int(r["training_eligible"] or 0),
                )
            )
        return out
    finally:
        conn.row_factory = previous_factory


def gold_version(rows: Sequence["GoldCrop"]) -> str:
    """sha256 de ``asset_id|truth_eurio_id|class_id`` trié, tronqué à 12 hex.

    Même convention de calcul que ``store.scan_corpus.corpus_version``
    (sha256 d'un manifeste trié, 12 hex) — délibérément : deux notions de
    « version d'un jeu figé » qui se calculeraient différemment finiraient par
    être comparées à tort.

    POURQUOI LA VÉRITÉ EST DANS LE HASH
    -----------------------------------
    La version ne hachait que les ``asset_id``. Une **re-décision humaine** —
    le cas que ``diff_gold`` désigne lui-même comme « celui qui doit alerter » —
    laissait la version identique, donc deux runs estampillés
    ``gold_version=X`` pouvaient avoir été notés contre des vérités
    différentes. Reproduit sur le gold committé : remplacer le
    ``truth_eurio_id`` du premier crop rendait ``9b15176b3309`` avant **et**
    après. Idem pour ``class_id``, qui est ce que le banc compare réellement
    (le représentant de groupe de dessin, cf. « LE PIÈGE class_id »).

    ``truth_country`` n'entre PAS dans le hash : depuis la correction du label
    pays, il est une fonction pure de ``truth_eurio_id`` (``[:2]``), donc il ne
    peut pas bouger sans que la vérité bouge. L'ajouter allongerait le
    manifeste sans rien discriminer de plus. ``storage_path``,
    ``training_eligible`` et les champs de provenance en sont exclus pour la
    raison inverse : ils décrivent le crop, pas ce contre quoi on le note.

    Les ``asset_id`` nus sont **refusés** : l'ancienne signature en prenait, et
    les laisser passer rendrait un hash de l'ancienne famille — comparable à
    tort avec une version d'avant correctif.
    """
    lines = []
    for r in rows:
        if not isinstance(r, GoldCrop):
            raise TypeError(
                "gold_version attend des GoldCrop, pas "
                f"{type(r).__name__} ({r!r}) : la version hache la vérité, "
                "plus seulement la population."
            )
        lines.append(f"{r.asset_id}|{r.truth_eurio_id}|{r.class_id}")
    manifest = "\n".join(sorted(lines))
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()[:12]


def _git_commit() -> str | None:
    """Le HEAD du dépôt, ou ``None`` hors dépôt / sans git. Jamais une exception :
    un sidecar sans commit reste plus utile qu'un build qui casse."""
    try:
        out = subprocess.run(
            ["git", "-C", str(_ML_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def meta_path(path: Path = DEFAULT_GOLD) -> Path:
    """Le sidecar de ``path`` : ``<nom>.meta.json`` (suffixe ``.jsonl`` remplacé)."""
    return path.with_suffix(".meta.json")


def build_meta(rows: Sequence[GoldCrop], *, db_path: Path | str | None = None,
               meta_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Le sidecar, sans écrire — utile pour l'afficher avant de committer."""
    db = Path(db_path) if db_path else None
    meta: dict[str, Any] = {
        "gold_version": gold_version(rows),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_crops": len(rows),
        "n_classes": len({r.class_id for r in rows}),
        "n_truth_eurio_ids": len({r.truth_eurio_id for r in rows}),
        "n_training_eligible": sum(1 for r in rows if r.training_eligible),
        "db_path": str(db) if db else None,
        "db_mtime": (
            datetime.fromtimestamp(db.stat().st_mtime, timezone.utc).isoformat(
                timespec="seconds"
            )
            if db and db.exists()
            else None
        ),
        "git_commit": _git_commit(),
        "builder": socket.gethostname(),
        "selection_sql": SELECTION_SQL,
    }
    if meta_extra:
        meta.update(meta_extra)
    return meta


def save_gold(
    rows: Sequence[GoldCrop],
    path: Path = DEFAULT_GOLD,
    *,
    meta_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Écrit le ``.jsonl`` **trié par asset_id** et son sidecar. Rend le sidecar.

    Aucun garde-fou d'écrasement ici : c'est le CLI qui porte ``--force``, pour
    que la bibliothèque reste utilisable dans un test ou un tmpdir sans rituel.
    """
    ordered = sorted(rows, key=lambda r: r.asset_id)
    db_path = (meta_extra or {}).get("db_path")
    meta = build_meta(ordered, db_path=db_path, meta_extra=meta_extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in ordered:
            f.write(json.dumps(asdict(r), ensure_ascii=False, sort_keys=True) + "\n")
    meta_path(path).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return meta


_FIELD_NAMES = frozenset(f.name for f in fields(GoldCrop))


def load_gold(path: Path = DEFAULT_GOLD) -> list[GoldCrop]:
    """Relit le manifeste. Les clés inconnues sont refusées bruyamment : un gold
    d'un autre schéma ne doit pas se charger à moitié."""
    out: list[GoldCrop] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            unknown = set(payload) - _FIELD_NAMES
            if unknown:
                raise ValueError(
                    f"{path}:{lineno} — champs inconnus {sorted(unknown)} ; "
                    "le gold n'a pas le schéma de GoldCrop."
                )
            out.append(GoldCrop(**payload))
    return out


def load_meta(path: Path = DEFAULT_GOLD) -> dict[str, Any]:
    """Le sidecar du gold ``path``."""
    return json.loads(meta_path(path).read_text(encoding="utf-8"))


def current_storage_paths(conn: sqlite3.Connection) -> dict[str, str]:
    """``{asset_id: storage_path}`` — l'emplacement des octets AUJOURD'HUI."""
    return {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT id, storage_path FROM image_assets WHERE storage_path IS NOT NULL"
        )
    }


def resolve_local_paths(
    rows: Sequence[GoldCrop],
    conn: sqlite3.Connection | None = None,
) -> tuple[list[tuple[GoldCrop, Path]], list[str]]:
    """``(présents sur disque, asset_ids manquants)``.

    **NE FILTRE PAS le gold** : le manifeste reste entier. Un crop absent du
    cache local aujourd'hui peut revenir de MinIO demain ; si le gold se
    rétrécissait à chaque cache froid, il ne serait plus figé — exactement le
    défaut qu'on corrige. C'est l'appelant (le banc) qui décide quoi faire du
    trou, et qui doit le REPORTER.

    🔴 **L'emplacement vient de la BASE, pas du manifeste — et ce n'est pas un
    dégel du gold.** Le gold fige *quels* crops sont notés ; il ne fige pas *où*
    leurs octets sont rangés. Confondre les deux a coûté cher le 2026-08-26 :
    le déplacement des crops d'éval vers le bucket ``eval-corpus`` (D9) a rendu
    **208 des 1 958** ``storage_path`` du manifeste périmés d'un coup. Avec
    l'ancienne version — ``local_path("enrichment-crops", r.storage_path)`` en
    dur — ces 208 partaient en ``missing`` : le banc perdait 10,6 % de son gold,
    basculait en ``provisional=1``, et ses chiffres cessaient d'être comparables
    aux bras du 2026-08-20. Rien n'aurait été faux, seulement décalé — la pire
    espèce d'écart.

    Le ``storage_path`` du manifeste reste utile comme **provenance** (ce qu'on
    a figé) et alimente ``diff_gold`` ; il ne sert simplement plus à ouvrir le
    fichier. Un asset absent de la base part en ``missing`` : c'est une vraie
    dérive, et ``diff_gold`` la nomme.

    ``conn`` optionnel : par défaut on ouvre la **réplique** en lecture seule
    (même convention que ``bench_encoder_dino.default_db`` — jamais
    ``state/eurio.db``, base de travail pré-flip qui peut être périmée de
    milliers de lignes).
    """
    from shared.storage import bucket_for_key  # noqa: PLC0415
    from shared.storage.local_cache import local_path  # noqa: PLC0415

    fermer = conn is None
    if conn is None:
        conn = sqlite3.connect(f"file:{_default_db()}?mode=ro", uri=True)
    try:
        actuels = current_storage_paths(conn)
    finally:
        if fermer:
            conn.close()

    present: list[tuple[GoldCrop, Path]] = []
    missing: list[str] = []
    for r in rows:
        cle = actuels.get(r.asset_id)
        if cle is None:
            # L'asset n'existe plus en base — dérive réelle, pas un cache froid.
            missing.append(r.asset_id)
            continue
        try:
            # Bucket DÉRIVÉ de la clé : `eval-corpus` pour un crop d'éval.
            p = local_path(bucket_for_key(cle), cle)
        except FileNotFoundError:
            missing.append(r.asset_id)
            continue
        if p.is_file():
            present.append((r, p))
        else:
            missing.append(r.asset_id)
    return present, missing


def diff_gold(conn: sqlite3.Connection, rows: Sequence[GoldCrop]) -> dict[str, Any]:
    """Ce que la base dirait aujourd'hui, comparé au gold figé.

    ``truth_changed`` est le cas qui doit alerter : un humain a re-tranché un
    crop déjà dans le gold. Ce n'est pas anodin — les runs antérieurs l'ont
    compté avec l'ancienne vérité.
    """
    current = {r.asset_id: r for r in build_gold(conn)}
    frozen = {r.asset_id: r for r in rows}

    added = sorted(set(current) - set(frozen))
    removed = sorted(set(frozen) - set(current))
    common = sorted(set(frozen) & set(current))
    truth_changed = [
        {"asset_id": aid, "was": frozen[aid].truth_eurio_id,
         "now": current[aid].truth_eurio_id}
        for aid in common
        if frozen[aid].truth_eurio_id != current[aid].truth_eurio_id
    ]
    # `class_id` est ce que le banc compare réellement : il peut bouger SANS
    # que `truth_eurio_id` bouge (nouveau représentant de groupe de dessin,
    # `design_group_id` recomposé). Le taire rendrait le diff vert sur un gold
    # qui ne mesure plus la même chose.
    class_changed = [
        {"asset_id": aid, "was": frozen[aid].class_id,
         "now": current[aid].class_id}
        for aid in common
        if frozen[aid].class_id != current[aid].class_id
    ]
    n_bougés = len({c["asset_id"] for c in truth_changed}
                   | {c["asset_id"] for c in class_changed})
    return {
        "added": added,
        "removed": removed,
        "truth_changed": truth_changed,
        "class_changed": class_changed,
        "n_stable": len(common) - n_bougés,
        "gold_version_frozen": gold_version(list(frozen.values())),
        "gold_version_current": gold_version(list(current.values())),
    }
