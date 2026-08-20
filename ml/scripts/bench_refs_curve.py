"""Étape 3 — la courbe « combien de références wild par classe ? ».

⚠️ CHIFFRES DE CE DOCSTRING : ils décrivent la banque du 2026-08-19
(build ``23c637d93b43``, 1533 ancres, 182 classes à exemplaires, 858 crops
fuités, 1100 held-out). La banque SERVIE depuis le 2026-08-20 14:27 est
``365dcab2a253`` : **1495 ancres, 124 classes à exemplaires, 779 fuités,
1179 held-out**. Le protocole décrit ci-dessous n'a pas changé ; seuls les
effectifs ont bougé, et ``check_bank_matches_build`` les revérifie à chaque run.

⛔ CE QU'UN PALIER N SIGNIFIE, ET CE QU'IL NE SIGNIFIE PAS
---------------------------------------------------------
Un palier N est « **TOUTES** les classes plafonnées à N », jamais « ces
classes-ci à N, les autres pleines ». Confondre les deux a coûté un plancher
``min_exemplars=2`` posé le 2026-08-20 et retiré le soir même. Pour poser la
question **par classe**, utiliser ``--bank-classes`` / ``--gold-classes`` ; pour
sonder le rôle de l'ordre du FPS, ``--rank-order last`` (sonde, ne correspond à
aucun build possible).

CE QUE CE SCRIPT MESURE
-----------------------
La précision de reconnaissance en fonction du **nombre d'exemplaires par
classe** dans la banque d'ancres. C'est le chiffre qui dimensionne le budget
de review (cf. ``docs/work-in-progress/scan-sans-retrain/DECISION.md`` §Étape 3).

L'IDÉE QUI REND LA MESURE PEU COÛTEUSE
--------------------------------------
On ne rebâtit **pas** la banque une fois par palier — ce serait N × 4 minutes
d'encodage, et la review se sert de la banque servie pendant ce temps.

Les 1533 ancres sont **déjà décrites** par ``state/foundation_anchors_2eur_all.npz``
(``eurio_ids`` = class_id de banque, ``asset_ids``, ``source_paths``) et
``dino_class_references`` porte le **``rank``** de chaque ligne : l'ordre du
*farthest-point sampling*, rang 1 = le plus diversifiant. Donc :

1. on encode les 1533 sources d'ancres + les crops du gold **une seule fois**
   avec l'encodeur demandé ;
2. pour chaque N, on **sous-échantillonne la matrice en mémoire** (canoniques +
   les lignes ``fps`` de rang ≤ N) et on rescore.

Coût total ≈ un seul run de banc. Aucune écriture : ni base, ni ``.npz``.

L'HYPOTHÈSE EST VÉRIFIÉE À CHAQUE RUN, PAS SUPPOSÉE
---------------------------------------------------
``check_bank_matches_build`` compare l'ensemble des ``asset_id`` du ``.npz`` à
celui du build tracé en base, et refuse de produire un chiffre si les deux
divergent. Mesuré le 2026-08-20 sur ``state/eurio.replica.db``, build
``23c637d93b43`` : 862 asset_id des deux côtés, 0 de différence dans chaque
sens, 671 class_id canoniques identiques, et les 862 ``eurio_ids`` du ``.npz``
égaux au ``class_id`` de la ligne correspondante. Les rangs ``fps`` sont
contigus 1..k pour les 182 classes à exemplaires.

LA FUITE — ET POURQUOI ELLE COMMANDE TOUT LE PROTOCOLE
-------------------------------------------------------
Les exemplaires de la banque **sont** des crops validés en review, donc ils
sont aussi dans le gold. Mesuré : **858 des 1958 crops du gold sont
eux-mêmes des lignes de la banque**. Les noter contre une banque qui les
contient, c'est mesurer une similarité de 1,0 avec soi-même : la « courbe »
monterait mécaniquement avec N sans rien dire de la généralisation.

Ce script note donc sur les crops **held-out** — ceux qui ne sont dans aucune
ligne de banque, à aucun palier : 1100 crops sur 72 classes. Le mode
``--include-leaked`` rejoue la version fuitée, uniquement pour **chiffrer**
l'écart ; il n'est jamais la mesure.

LES DEUX LECTURES, QUI NE RÉPONDENT PAS À LA MÊME QUESTION
-----------------------------------------------------------
Toutes les classes n'ont pas 10 exemplaires (182 en ont ≥1, 55 en ont 10). Une
seule courbe mélangerait deux populations :

* **population variable** — toutes les classes held-out, chacune plafonnée à ce
  qu'elle a. C'est ce que vit l'utilisateur : à N=10 les classes pauvres
  n'apportent toujours que leur canonique.
* **population constante** — les seules classes qui ont 10 exemplaires. C'est
  ce qui isole l'effet du nombre de références, puisque le N demandé est le N
  réellement obtenu pour chaque classe.

Les deux sortent, dans deux tables séparées.

⚠️ LA TÂCHE MESURÉE EST LA REVIEW, PAS LE SCAN
-----------------------------------------------
Le gold est fait de photos de vendeurs eBay (à plat, nettes). La courbe du
scan — frame caméra en main, reflets — sera différente et exige le corpus de
capture, encore vide.

RESTREINDRE — ET NE PAS CONFONDRE LES DEUX RESTRICTIONS
--------------------------------------------------------
Un point agrégé sur 1179 crops ne dit rien d'un effet qui porte sur 68 classes :
il le dilue jusqu'à l'invisible. C'est ce qui a fait poser puis retirer le
plancher ``min_exemplars`` (cf. ``shared/dino_threshold_defaults.py``). Deux
drapeaux, qui ne mesurent PAS la même chose :

* ``--bank-classes`` change la BANQUE : le plafond N ne s'applique qu'à ces
  classes, toutes les autres gardent tous leurs exemplaires. C'est ainsi qu'on
  simule « ces classes-là sont pauvres, le reste est intact ».
* ``--gold-classes`` change la POPULATION ÉVALUÉE : seuls les crops de ces
  classes sont notés.

Les croiser sépare les deux moitiés de l'effet d'un exemplaire :
``--bank-classes S --gold-classes S`` = ce qu'il apporte à SA classe ;
``--bank-classes S --gold-classes <complément>`` = ce qu'il coûte aux AUTRES,
en distracteur. Mesuré le 2026-08-20 sur la banque ``365dcab2`` (S = les 57
classes à 10 exemplaires, vitl14) : +1,5 pt sur les siens (67,6 → 69,1 %,
McNemar p = 0,048) contre −0,6 pt sur les autres (88,5 → 88,0 %, p = 0,031).

Ce S se régénère depuis la banque servie, sans base ni modèle ::

    python -c "
    import numpy as np; from collections import Counter
    d = np.load('state/foundation_anchors_2eur_all.npz', allow_pickle=True)
    per = Counter(e for e, a in zip(d['eurio_ids'], d['asset_ids']) if a)
    print('\\n'.join(sorted(c for c, n in per.items() if n == 10)))" > /tmp/S.txt

``--rank-order last`` garde, à nombre d'ancres identique, les exemplaires les
MOINS diversifiants au lieu des plus diversifiants. Aucun build ne produit ça :
c'est la sonde du mécanisme. Elle a tranché — vitl14 à un exemplaire par
classe : 73,8 % avec le rang 1, **77,8 % avec le dernier rang**, contre 76,2 %
à N=0. Le creux à N=1 est un effet de la SÉLECTION, pas du nombre.

Chaque palier porte aussi sa comparaison appariée au premier palier demandé
(paires discordantes + McNemar exact) : sans elle, un écart de deux points sur
une petite population se lit comme un résultat.

Usage::

    .venv/bin/python -m scripts.bench_refs_curve
    .venv/bin/python -m scripts.bench_refs_curve --model dinov2_vitl14
    .venv/bin/python -m scripts.bench_refs_curve --refs 0 1 3 10 --out courbe.md
    .venv/bin/python -m scripts.bench_refs_curve --refs 0 1 \
        --bank-classes @classes.txt --gold-classes @classes.txt
    .venv/bin/python -m scripts.bench_refs_curve --refs 0 1 --rank-order last
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

import numpy as np  # noqa: E402

from training.foundation import (  # noqa: E402
    AnchorBank,
    encode_paths,
    load_anchors,
    pick_device,
)
from review.bench_gold import (  # noqa: E402
    DEFAULT_GOLD,
    GoldCrop,
    load_gold,
    load_meta,
    resolve_local_paths,
)
from scripts.bench_encoder_dino import (  # noqa: E402
    BENCH_KIND,
    _load_model,
    encoder_version_of,
    score_crops,
    select_sample,
)
from shared.stats.paired import paired_compare  # noqa: E402
from store import resolve_db_path  # noqa: E402

#: Les paliers par défaut. 0 = banque canonique seule (l'état « aucune review »).
DEFAULT_REFS = (0, 1, 2, 3, 5, 8, 10)

_RULE = "=" * 78


def default_db() -> Path:
    """La base à LIRE, ``EURIO_DB_PATH`` d'abord, repli sur la **réplique**.

    Même convention que ``scripts.bench_encoder_dino.default_db`` (D12) : un
    lecteur seul se replie sur le miroir du canonique, jamais sur
    ``state/eurio.db`` qui est une base de travail pré-flip périmée.
    Résolu à l'appel, pour qu'un test qui pose l'env soit entendu.
    """
    return resolve_db_path(ML_DIR / "state" / "eurio.replica.db")


def parse_class_set(spec: str | None) -> set[str] | None:
    """``"a,b"`` ou ``"@fichier"`` → un ensemble de ``class_id``. ``None`` passe.

    Un fichier = un ``class_id`` par ligne, ``#`` en commentaire. On refuse un
    ensemble vide plutôt que de le confondre avec « pas de restriction » : les
    deux ne mesurent pas la même chose, et l'un des deux ne mesure rien.
    """
    if spec is None:
        return None
    if spec.startswith("@"):
        path = Path(spec[1:])
        raw = [
            line.split("#", 1)[0].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
    else:
        raw = spec.split(",")
    out = {s.strip() for s in raw if s.strip()}
    if not out:
        raise ValueError(f"ensemble de classes vide : {spec!r}")
    return out


# ─── Les rangs FPS, lus en base ──────────────────────────────────────────────


def load_reference_ranks(
    conn: sqlite3.Connection, *, anchors_kind: str, encoder_version: str
) -> tuple[str | None, dict[str, int], set[str]]:
    """``(build_id, {asset_id: rank}, {class_id canoniques})`` du dernier build.

    ``rank`` est l'ordre de sélection du *farthest-point sampling* : rang 1 =
    l'exemplaire le plus diversifiant de sa classe. C'est lui qui permet de
    sous-échantillonner la banque sans la rebâtir — prendre « les N premiers »
    reproduit exactement ce qu'aurait donné un build à ``exemplars_per_class=N``,
    **à sélection constante** (cf. la réserve du rapport).

    Rend ``(None, {}, set())`` si aucun build n'est tracé : l'appelant doit
    refuser, pas deviner.
    """
    row = conn.execute(
        "SELECT build_id FROM dino_anchor_builds "
        " WHERE anchors_kind = ? AND encoder_version = ? "
        " ORDER BY built_at DESC LIMIT 1",
        (anchors_kind, encoder_version),
    ).fetchone()
    if not row:
        return None, {}, set()
    build_id = row[0]
    ranks: dict[str, int] = {}
    canonical: set[str] = set()
    for class_id, asset_id, method, rank in conn.execute(
        "SELECT class_id, asset_id, method, rank FROM dino_class_references "
        " WHERE build_id = ?",
        (build_id,),
    ):
        if method == "canonical" or not asset_id:
            canonical.add(class_id)
        elif method == "fps":
            if rank is None:
                raise ValueError(
                    f"{build_id} : ligne fps sans rang (class_id={class_id}, "
                    f"asset_id={asset_id}) — la courbe ne peut pas ordonner "
                    "les références de cette classe."
                )
            ranks[asset_id] = int(rank)
    return build_id, ranks, canonical


def check_bank_matches_build(
    bank: AnchorBank, ranks: dict[str, int], canonical: set[str], build_id: str | None
) -> None:
    """Refuse de mesurer si le ``.npz`` et le build tracé ne décrivent pas la
    même banque. C'est l'hypothèse centrale du protocole ; elle est vérifiée à
    chaque run, jamais supposée."""
    if build_id is None:
        raise RuntimeError(
            "Aucun build tracé dans dino_anchor_builds pour "
            f"({bank.anchors_kind}, {bank.encoder_version}) — sans les rangs "
            "FPS il n'y a pas de courbe possible. Rafraîchir la réplique."
        )
    if not bank.asset_ids:
        raise RuntimeError(
            "Le .npz ne porte pas d'asset_ids — banque d'avant improvement-loop B."
        )
    npz_assets = {a for a in bank.asset_ids if a}
    db_assets = set(ranks)
    if npz_assets != db_assets:
        raise RuntimeError(
            f"Banque servie et build {build_id} divergent : "
            f"{len(npz_assets - db_assets)} asset_id du .npz absents de la base, "
            f"{len(db_assets - npz_assets)} de la base absents du .npz. "
            "La banque a été rebâtie sans que la trace suive (ou l'inverse) — "
            "la courbe serait fausse."
        )
    npz_canonical = {
        eid for eid, aid in zip(bank.eurio_ids, bank.asset_ids) if not aid
    }
    if npz_canonical != canonical:
        raise RuntimeError(
            f"Lignes canoniques divergentes : {len(npz_canonical)} dans le .npz, "
            f"{len(canonical)} dans le build {build_id}."
        )


# ─── Le sous-échantillonnage, fonction pure ──────────────────────────────────


def class_max_rank(
    eurio_ids: Sequence[str],
    asset_ids: Sequence[str | None],
    ranks: dict[str, int],
) -> dict[str, int]:
    """``{class_id: rang FPS le plus élevé}`` — le dernier exemplaire de chaque
    classe. Sert à l'ordre ``last`` de :func:`subsample_indices`."""
    out: dict[str, int] = {}
    for eid, aid in zip(eurio_ids, asset_ids):
        if not aid:
            continue
        r = ranks.get(aid)
        if r is None:
            continue
        out[eid] = max(out.get(eid, 0), int(r))
    return out


def subsample_indices(
    eurio_ids: Sequence[str],
    asset_ids: Sequence[str | None],
    ranks: dict[str, int],
    n_refs: int,
    *,
    cap_classes: set[str] | None = None,
    order: str = "first",
) -> list[int]:
    """Les indices de lignes d'une banque plafonnée à ``n_refs`` exemplaires/classe.

    Garde **toutes** les lignes canoniques (une classe ne disparaît jamais d'un
    palier : à N=0 la banque est la banque canonique seule, 671 classes) et les
    lignes ``fps`` de rang ≤ ``n_refs``.

    ``cap_classes`` — le plafond ne s'applique QU'À ces classes ; toutes les
    autres gardent **tous** leurs exemplaires. C'est ce qui permet de simuler
    « ces classes-là sont pauvres, le reste de la banque est intact », donc de
    poser la question du plancher (``min_exemplars``) sur une sous-population
    au lieu de l'agréger sur la banque entière. ``None`` = plafond global,
    le comportement historique.

    ``order`` — quel exemplaire on garde quand on n'en garde qu'un :

    * ``"first"`` : les rangs 1..N, l'ordre du FPS. Le rang 1 est le crop le
      **plus** diversifiant, donc le plus atypique — c'est celui qu'un vrai
      build à N=1 mettrait en banque.
    * ``"last"`` : les N **derniers** rangs de chaque classe, c'est-à-dire les
      crops les moins diversifiants, donc les plus typiques. Ne correspond à
      aucun build possible : c'est la sonde du **mécanisme** « le rang 1 agit
      en faux attracteur parce qu'il est atypique ». Si le creux à N=1
      disparaît en ``last``, c'est l'atypicité qui coûte, pas le nombre.
    """
    if n_refs < 0:
        raise ValueError(f"n_refs doit être ≥ 0, reçu {n_refs}")
    if order not in ("first", "last"):
        raise ValueError(f"order doit être 'first' ou 'last', reçu {order!r}")
    maxima = (
        class_max_rank(eurio_ids, asset_ids, ranks) if order == "last" else {}
    )
    keep: list[int] = []
    for i, (eid, aid) in enumerate(zip(eurio_ids, asset_ids)):
        if not aid:
            keep.append(i)
            continue
        rank = ranks.get(aid)
        if rank is None:
            raise KeyError(
                f"asset_id={aid} (classe {eid}) n'a pas de rang FPS — "
                "check_bank_matches_build aurait dû l'attraper."
            )
        if cap_classes is not None and eid not in cap_classes:
            keep.append(i)          # classe hors périmètre : intacte
            continue
        if order == "first":
            if rank <= n_refs:
                keep.append(i)
        else:
            if rank > maxima.get(eid, 0) - n_refs:
                keep.append(i)
    return keep


def exemplars_per_class(
    eurio_ids: Sequence[str], asset_ids: Sequence[str | None]
) -> dict[str, int]:
    """Combien d'exemplaires (lignes non canoniques) porte chaque classe."""
    counts: Counter[str] = Counter()
    for eid, aid in zip(eurio_ids, asset_ids):
        if aid:
            counts[eid] += 1
    return dict(counts)


def sub_bank(bank: AnchorBank, matrix: np.ndarray, keep: Sequence[int]) -> AnchorBank:
    """Une banque restreinte aux indices ``keep``, sur la matrice ré-encodée."""
    idx = np.asarray(keep, dtype=int)
    return AnchorBank(
        eurio_ids=[bank.eurio_ids[i] for i in idx],
        matrix=matrix[idx],
        encoder_version=bank.encoder_version,
        anchors_kind=bank.anchors_kind,
        built_at="courbe-refs",
        asset_ids=[bank.asset_ids[i] for i in idx] if bank.asset_ids else [],
    )


# ─── Les populations ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Population:
    """Un sous-ensemble du gold, avec de quoi le décrire dans le rapport."""

    name: str
    label: str
    question: str
    crops: list[tuple[GoldCrop, Path]]

    @property
    def n_crops(self) -> int:
        return len(self.crops)

    @property
    def n_classes(self) -> int:
        return len({c.class_id for c, _p in self.crops})


def split_populations(
    crops: Sequence[tuple[GoldCrop, Path]],
    bank_class_ids: set[str],
    bank_asset_ids: set[str],
    per_class: dict[str, int],
    n_max: int,
    *,
    include_leaked: bool = False,
) -> list[Population]:
    """Les deux lectures de la mission, plus la fuitée si on la demande."""
    in_scope = [t for t in crops if t[0].class_id in bank_class_ids]
    held_out = [t for t in in_scope if t[0].asset_id not in bank_asset_ids]
    full = {c for c, n in per_class.items() if n >= n_max}
    pops = [
        Population(
            name="variable",
            label="Population VARIABLE — held-out, toutes classes "
                  "(plafond = ce que la classe a)",
            question="Ce que vit l'utilisateur : à N demandé, une classe pauvre "
                     "n'apporte toujours que ce qu'elle a.",
            crops=held_out,
        ),
        Population(
            name="constante",
            label=f"Population CONSTANTE — held-out, seules les classes à ≥ {n_max} "
                  f"exemplaires",
            question="Ce qui isole l'effet du nombre de références : ici le N "
                     "demandé est le N réellement obtenu par chaque classe.",
            crops=[t for t in held_out if t[0].class_id in full],
        ),
    ]
    if include_leaked:
        pops.append(
            Population(
                name="fuitee",
                label="Population FUITÉE — tous les crops in-scope, y compris ceux "
                      "qui SONT des lignes de la banque",
                question="Ne répond à aucune question de généralisation : sert "
                         "uniquement à chiffrer combien la fuite gonfle le chiffre.",
                crops=in_scope,
            )
        )
    return pops


# ─── La mesure ───────────────────────────────────────────────────────────────


def _ratio(n: int, d: int) -> float | None:
    return (n / d) if d else None


def _pct(x: float | None) -> str:
    return f"{100.0 * x:.1f}%" if x is not None else "—"


def measure_curve(
    bank: AnchorBank,
    anchor_matrix: np.ndarray,
    ranks: dict[str, int],
    populations: Sequence[Population],
    kept_index: dict[str, int],
    crop_matrix: np.ndarray,
    refs: Sequence[int],
    *,
    cap_classes: set[str] | None = None,
    order: str = "first",
) -> dict[str, list[dict[str, Any]]]:
    """Pour chaque palier N, rescore chaque population contre la sous-banque.

    Chaque palier porte aussi sa comparaison **appariée** au premier palier
    demandé (``paired_vs_base``) : mêmes crops, deux banques, table de
    contingence + McNemar exact. Sans elle, un écart de 2 points sur 80 crops
    se lit comme un résultat alors qu'il tient dans le bruit — et c'est
    exactement l'erreur qu'on répare ici.
    """
    out: dict[str, list[dict[str, Any]]] = {p.name: [] for p in populations}
    base_ok: dict[str, dict[str, bool]] = {}
    for n_refs in refs:
        keep = subsample_indices(
            bank.eurio_ids, bank.asset_ids, ranks, n_refs,
            cap_classes=cap_classes, order=order,
        )
        sb = sub_bank(bank, anchor_matrix, keep)
        n_ex = sum(1 for a in sb.asset_ids if a)
        for pop in populations:
            preds, agg = score_crops(sb, pop.crops, kept_index, crop_matrix)
            ok = {p.asset_id: bool(p.correct) for p in preds}
            if pop.name not in base_ok:
                base_ok[pop.name] = ok
                paired = None
            else:
                paired = paired_compare(base_ok[pop.name], ok).to_dict()
            out[pop.name].append(
                {
                    "n_refs": n_refs,
                    "bank_rows": sb.count,
                    "bank_exemplars": n_ex,
                    "bank_classes": len(set(sb.eurio_ids)),
                    "n_in_scope": agg["n_in_scope"],
                    "n_not_encoded": agg["n_not_encoded"],
                    "recall1": _ratio(agg["g1"], agg["n_in_scope"]),
                    "recall5": _ratio(agg["g5"], agg["n_in_scope"]),
                    "country_n": agg["c_total"],
                    "country_recall1": _ratio(agg["c1"], agg["c_total"]),
                    "country_recall5": _ratio(agg["c5"], agg["c_total"]),
                    "paired_vs_base": paired,
                }
            )
    return out


def diminishing_returns(
    points: Sequence[dict[str, Any]], *, min_gain_pt_per_ref: float = 1.0
) -> dict[str, Any] | None:
    """Le palier à partir duquel une référence de plus ne rapporte plus rien.

    Définition explicite, pour qu'elle soit discutable : le **gain marginal par
    référence** d'un segment vaut ``(r1[k] - r1[k-1]) / (N[k] - N[k-1])``, et le
    coude est le **plus petit N dont TOUS les segments suivants** passent sous
    ``min_gain_pt_per_ref`` point de recall@1 par référence.

    ⚠️ Le « premier segment plat », qui serait le critère naïf, est FAUX ici, et
    la mesure réelle le prouve : sur ``dinov2_vits14`` la première référence FPS
    — la plus diversifiante, donc la plus atypique — fait *baisser* le recall
    (53,1 % → 50,1 %) avant que la courbe ne remonte jusqu'à 75,5 % à N=10. Un
    critère « premier segment sous le seuil » rendrait « coude à N=0 », c'est-à-
    dire « ne validez aucun crop ». Exactement l'inverse de la conclusion.

    ``None`` quand aucun palier ne satisfait la condition : la courbe monte
    encore dans la plage mesurée, et il faut pousser les paliers plus loin — un
    cas qu'il faut lire, pas masquer.
    """
    usable = [p for p in points if p.get("recall1") is not None]
    if len(usable) < 2:
        return None
    gains = [
        (100.0 * (cur["recall1"] - prev["recall1"]) / (cur["n_refs"] - prev["n_refs"]))
        if cur["n_refs"] > prev["n_refs"] else 0.0
        for prev, cur in zip(usable, usable[1:])
    ]
    for k in range(len(usable) - 1):
        if all(g < min_gain_pt_per_ref for g in gains[k:]):
            return {
                "knee_n_refs": usable[k]["n_refs"],
                "recall1_at_knee": usable[k]["recall1"],
                "next_n_refs": usable[k + 1]["n_refs"],
                "marginal_gain_pt_per_ref": gains[k],
                "min_gain_pt_per_ref": min_gain_pt_per_ref,
            }
    return None


# ─── Rapport ─────────────────────────────────────────────────────────────────


def render_report(
    *,
    model: str,
    encoder_version: str,
    device: str,
    params_m: float,
    input_px: int,
    dim: int,
    gold_version: str,
    n_gold: int,
    n_submitted: int,
    n_missing: int,
    n_not_encoded: int,
    build_id: str,
    bank_rows: int,
    bank_classes: int,
    bank_exemplars: int,
    per_class_hist: dict[int, int],
    populations: Sequence[Population],
    curves: dict[str, list[dict[str, Any]]],
    knees: dict[str, dict[str, Any] | None],
    n_leaked: int,
    n_max: int,
    seconds: float,
    cap_classes: set[str] | None = None,
    gold_classes: set[str] | None = None,
    rank_order: str = "first",
) -> str:
    lines = [
        "# Courbe « références par classe » — banque 2eur_all, gold figé de review",
        "",
        "```",
        _RULE,
        "⚠ TÂCHE REVIEW, PAS TÂCHE SCAN — le gold est fait de photos de vendeurs",
        "  eBay (à plat, nettes). La courbe du scan (frame caméra en main,",
        "  reflets) sera différente et exige le corpus de capture, encore vide.",
        _RULE,
        "```",
        "",
        "## Ce qui a été mesuré",
        "",
        f"- encodeur `{model}` (`{encoder_version}`) — {params_m:.1f} M params, "
        f"{input_px} px, dim {dim}, device `{device}`",
        f"- gold `{gold_version}` : {n_gold} crops figés · {n_submitted} soumis · "
        f"{n_missing} absents du cache · {n_not_encoded} non encodés",
        f"- banque servie : build `{build_id}`, {bank_rows} lignes "
        f"({bank_classes} canoniques + {bank_exemplars} exemplaires)",
        f"- **{n_leaked} crops du gold sont eux-mêmes des lignes de la banque** "
        "et sont EXCLUS des deux lectures (se comparer à soi-même rend 1,0).",
        f"- durée totale : {seconds:.0f} s",
        "",
        "Restrictions de ce run — **les deux ne mesurent pas la même chose** :",
        "",
        f"- plafond N appliqué à : "
        + (f"**{len(cap_classes)} classes** (`--bank-classes`) ; toutes les "
           "autres gardent TOUS leurs exemplaires"
           if cap_classes is not None else "toutes les classes (défaut)"),
        f"- crops notés restreints à : "
        + (f"**{len(gold_classes)} classes** (`--gold-classes`)"
           if gold_classes is not None else "tout le gold in-scope (défaut)"),
        f"- exemplaires gardés par le plafond : `{rank_order}` "
        + ("(rangs FPS 1..N — ce qu'un vrai build produirait)"
           if rank_order == "first"
           else "(les N DERNIERS rangs, les moins diversifiants — sonde de "
                "mécanisme, aucun build ne produit ça)"),
        "",
        "Exemplaires par classe dans la banque (les classes sans exemplaire "
        "n'apparaissent pas) :",
        "",
        "| exemplaires | classes |",
        "|---:|---:|",
    ]
    lines += [
        f"| {k} | {per_class_hist[k]} |" for k in sorted(per_class_hist)
    ]
    for pop in populations:
        lines += [
            "",
            f"## {pop.label}",
            "",
            f"> {pop.question}",
            "",
            f"{pop.n_crops} crops · {pop.n_classes} classes.",
            "",
            "| N réf./classe | lignes de banque | in-scope | global@1 | global@5 "
            "| pays@1 | pays@5 | gagnés/perdus vs base | McNemar p |",
            "|---:|---:|---:|---:|---:|---:|---:|:--:|---:|",
        ]
        for pt in curves[pop.name]:
            pr = pt.get("paired_vs_base")
            if pr is None:
                disc, pval = "— (base)", "—"
            elif not pr["comparable"]:
                disc, pval = "aucune paire", "—"
            else:
                disc = f"+{pr['b_only']} / −{pr['a_only']}"
                pval = f"{pr['p_value']:.3g}"
            lines.append(
                f"| {pt['n_refs']} | {pt['bank_rows']} | {pt['n_in_scope']} "
                f"| {_pct(pt['recall1'])} | {_pct(pt['recall5'])} "
                f"| {_pct(pt['country_recall1'])} | {_pct(pt['country_recall5'])} "
                f"| {disc} | {pval} |"
            )
        knee = knees.get(pop.name)
        lines.append("")
        if knee:
            lines.append(
                f"**Rendement décroissant à N = {knee['knee_n_refs']}** "
                f"(global@1 = {_pct(knee['recall1_at_knee'])}) : le segment "
                f"{knee['knee_n_refs']} → {knee['next_n_refs']} ne rapporte plus que "
                f"{knee['marginal_gain_pt_per_ref']:.2f} point de global@1 par "
                "référence ajoutée."
            )
        else:
            lines.append(
                "**Aucun coude dans la plage mesurée** : chaque référence "
                "supplémentaire rapporte encore ≥ 1 point de global@1. La courbe "
                "n'a pas plié — pousser les paliers plus loin avant de conclure."
            )
    lines += [
        "",
        "## Ce que cette mesure ne dit pas",
        "",
        "- **La sélection est celle de `dinov2-vitl14`.** Les rangs FPS viennent "
        f"du build `{build_id}`, calculé avec l'encodeur de production. Rejouer la "
        "courbe avec un autre encodeur fait varier le NOMBRE de références à "
        "sélection constante — c'est voulu (ça isole le nombre), mais un vrai "
        "build à N exemplaires avec cet encodeur choisirait des crops "
        "légèrement différents. ⚠️ estimation : l'écart est probablement petit "
        "(le FPS optimise la diversité, pas l'encodeur), non mesuré.",
        "- **La population held-out est biaisée vers les classes riches.** Un "
        "crop n'est held-out que s'il n'a pas été retenu comme exemplaire ; une "
        "classe qui n'a qu'un crop validé le voit partir dans la banque et "
        "disparaît de l'évaluation. D'où "
        f"{populations[0].n_classes} classes évaluées, pas 671.",
        "- **C'est la tâche review.** Voir la bannière en tête.",
    ]
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="dinov2_vits14",
                        help="spec d'encodeur (torch.hub DINOv2 ou timm:<name>)")
    parser.add_argument("--refs", nargs="+", type=int, default=list(DEFAULT_REFS),
                        help=f"paliers de références/classe (défaut : {list(DEFAULT_REFS)})")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--db", default=None,
                        help=f"base à LIRE (défaut : {default_db()})")
    parser.add_argument("--limit", type=int, default=None,
                        help="échantillon déterministe de N crops du gold")
    parser.add_argument(
        "--bank-classes", default=None,
        help="restreint le PLAFOND N à ces classes (`a,b` ou `@fichier`) : les "
             "autres gardent tous leurs exemplaires. Simule « ces classes-là "
             "sont pauvres, le reste de la banque est intact ».")
    parser.add_argument(
        "--gold-classes", default=None,
        help="restreint les CROPS NOTÉS à ces classes (`a,b` ou `@fichier`). "
             "Ce n'est PAS la même mesure que --bank-classes : celle-ci change "
             "la population évaluée, celle-là change la banque.")
    parser.add_argument(
        "--rank-order", choices=("first", "last"), default="first",
        help="quels exemplaires garde le plafond : `first` = les rangs FPS 1..N "
             "(ce qu'un vrai build produirait) ; `last` = les N derniers rangs, "
             "les moins diversifiants — sonde du mécanisme « le rang 1 est un "
             "faux attracteur parce qu'il est atypique ».")
    parser.add_argument("--include-leaked", action="store_true",
                        help="ajouter la courbe FUITÉE (crops qui sont des ancres) "
                             "pour chiffrer l'écart — jamais la mesure")
    parser.add_argument("--out", default=None, help="rapport Markdown")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="courbes brutes en JSON")
    args = parser.parse_args(argv)

    refs = sorted(set(args.refs))
    if not refs:
        parser.error("--refs ne peut pas être vide")
    try:
        cap_classes = parse_class_set(args.bank_classes)
        gold_classes = parse_class_set(args.gold_classes)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    n_max = max(refs)
    t_start = time.perf_counter()

    base = load_anchors(BENCH_KIND)
    if base is None or not base.source_paths:
        raise RuntimeError(
            f"Banque {BENCH_KIND} introuvable ou sans source_paths — "
            "`go-task ml:dino-anchors:build` d'abord."
        )

    db_path = Path(args.db) if args.db else default_db()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        build_id, ranks, canonical = load_reference_ranks(
            conn, anchors_kind=BENCH_KIND, encoder_version=base.encoder_version
        )
    finally:
        conn.close()
    check_bank_matches_build(base, ranks, canonical, build_id)
    print(
        f"banque servie ↔ build {build_id} : {len(ranks)} exemplaires appariés, "
        f"{len(canonical)} canoniques — hypothèse vérifiée",
        file=sys.stderr,
    )

    gold = load_gold(args.gold)
    meta = load_meta(args.gold)
    present, missing = resolve_local_paths(gold)
    if gold_classes is not None:
        n_avant = len(present)
        present = [t for t in present if t[0].class_id in gold_classes]
        print(
            f"--gold-classes : {len(gold_classes)} classes demandées, "
            f"{len(present)} crops retenus sur {n_avant} (les classes sans crop "
            "en cache ne pèsent rien)",
            file=sys.stderr,
        )
        if not present:
            raise RuntimeError(
                "--gold-classes ne retient aucun crop du gold : il n'y a rien à "
                "mesurer. Vérifier les class_id (maille class_id, pas eurio_id)."
            )
    crops = select_sample(present, args.limit)
    print(
        f"gold {meta['gold_version']} : {len(gold)} figés · {len(present)} en "
        f"cache · {len(crops)} soumis",
        file=sys.stderr,
    )

    device = pick_device()
    encoder, transform, n_params, input_px = _load_model(args.model, device)
    print(f"=== {args.model} on {device} ===", file=sys.stderr)

    anchor_paths = [Path(p) for p in base.source_paths]
    kept_anchor_paths, anchor_matrix = encode_paths(
        anchor_paths, encoder=encoder, device=device, transform=transform
    )
    if len(kept_anchor_paths) != len(anchor_paths):
        # Une ancre perdue décale toute la correspondance ligne ↔ rang : on
        # refuse plutôt que de rendre une courbe décalée d'une ligne.
        raise RuntimeError(
            f"{len(anchor_paths) - len(kept_anchor_paths)} sources d'ancres non "
            "encodées — la correspondance ligne ↔ rang FPS serait rompue."
        )

    crop_paths = [p for _c, p in crops]
    kept_crop_paths, crop_matrix = encode_paths(
        crop_paths, encoder=encoder, device=device, transform=transform
    )
    kept_index = {str(p): i for i, p in enumerate(kept_crop_paths)}
    n_not_encoded = len(crop_paths) - len(kept_crop_paths)
    if n_not_encoded:
        print(
            f"  !! {n_not_encoded} crops présents en cache mais NON encodés",
            file=sys.stderr,
        )

    per_class = exemplars_per_class(base.eurio_ids, base.asset_ids)
    bank_asset_ids = {a for a in base.asset_ids if a}
    bank_class_ids = set(base.eurio_ids)
    populations = split_populations(
        crops, bank_class_ids, bank_asset_ids, per_class, n_max,
        include_leaked=args.include_leaked,
    )
    n_leaked = sum(
        1 for c, _p in crops
        if c.class_id in bank_class_ids and c.asset_id in bank_asset_ids
    )

    curves = measure_curve(
        base, anchor_matrix, ranks, populations, kept_index, crop_matrix, refs,
        cap_classes=cap_classes, order=args.rank_order,
    )
    knees = {p.name: diminishing_returns(curves[p.name]) for p in populations}

    report = render_report(
        model=args.model,
        encoder_version=encoder_version_of(args.model),
        device=str(device),
        params_m=n_params / 1e6,
        input_px=input_px,
        dim=int(anchor_matrix.shape[1]),
        gold_version=meta["gold_version"],
        n_gold=len(gold),
        n_submitted=len(crops),
        n_missing=len(missing),
        n_not_encoded=n_not_encoded,
        build_id=build_id or "?",
        bank_rows=base.count,
        bank_classes=len(canonical),
        bank_exemplars=len(ranks),
        per_class_hist=dict(Counter(per_class.values())),
        populations=populations,
        curves=curves,
        knees=knees,
        n_leaked=n_leaked,
        n_max=n_max,
        seconds=time.perf_counter() - t_start,
        cap_classes=cap_classes,
        gold_classes=gold_classes,
        rank_order=args.rank_order,
    )
    print(report)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"\n→ écrit dans {args.out}", file=sys.stderr)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {
                    "model": args.model,
                    "gold_version": meta["gold_version"],
                    "build_id": build_id,
                    "bank_classes": sorted(cap_classes) if cap_classes else None,
                    "gold_classes": sorted(gold_classes) if gold_classes else None,
                    "rank_order": args.rank_order,
                    "n_leaked": n_leaked,
                    "populations": {
                        p.name: {"n_crops": p.n_crops, "n_classes": p.n_classes}
                        for p in populations
                    },
                    "curves": curves,
                    "knees": knees,
                },
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        print(f"→ JSON écrit dans {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
