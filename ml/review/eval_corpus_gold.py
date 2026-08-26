"""Le manifeste figé d'un CORPUS D'ÉVALUATION — chantier ``juge-et-banc``.

Le pendant de ``review.bench_gold`` pour un jeu défini par un **rôle**
(``image_assets.eval_corpus``) plutôt que par une décision de review. Même
format de ligne (``GoldCrop``), même sidecar, même ``gold_version`` : tout ce
qui lit un gold lit celui-ci sans une ligne de code en plus.

POURQUOI UN MODULE À PART, ET PAS UNE FONCTION DE ``bench_gold``
----------------------------------------------------------------
Parce que la POPULATION n'est pas définie de la même manière, et que confondre
les deux définitions est précisément le défaut que ``bench_gold`` a corrigé
(deux ``SELECT`` concurrents pour « le jeu d'évaluation »). Ici :

* ``bench_gold`` sélectionne **tout ce que la review a tranché** — une
  population qui grossit à chaque décision, figée par un manifeste ;
* ce module sélectionne **les crops portant un rôle d'éval**, prélevés par
  ``scripts/select_eval_holdout.py`` selon la règle D5/D7 et exclus de
  l'entraînement par les deux collectes.

Le second est un sous-ensemble du parc, pas du premier : mesuré le 2026-08-26,
**208 des 300** crops d'éval seulement figurent dans le gold de review, et
ils n'y couvrent que **52 des 60** classes. Les deux jeux ne se comparent donc
pas, et il ne faut pas attendre un delta lisible avec les bras du 2026-08-20.

D'OÙ VIENT LA VÉRITÉ — et pourquoi PAS ``review_queue.decided_eurio_id``
------------------------------------------------------------------------
``image_assets.eurio_id``, le **label tranché**. Mesuré sur les 300 :

.. code-block:: sql

    -- 298 ont une décision de review ; 1 a une ligne 'skipped' (kind='lot'),
    -- 1 n'a aucune ligne review_queue.
    SELECT count(*) FROM image_assets a
      JOIN review_queue rq ON rq.image_asset_id = a.id
     WHERE a.eval_corpus IS NOT NULL AND rq.status='done'
       AND rq.decided_eurio_id IS NOT NULL;                     -- 298
    -- et sur ces 298, DIVERGENCE avec image_assets.eurio_id :
    ... AND rq.decided_eurio_id != a.eurio_id;                  -- 0

Deux raisons de prendre ``a.eurio_id`` :

1. **il est d'accord partout où les deux existent** (0/298), et il couvre les
   2 crops que ``review_queue`` ne couvre pas. Prendre ``decided_eurio_id``
   ferait tomber deux classes de 5 à 4 crops et casserait l'invariant du
   prélèvement, pour zéro gain de justesse mesurable ;
2. **c'est le champ que la collecte d'entraînement utilise comme label**
   (``training.iteration_augmentations._ebay_training_sources`` filtre
   ``a.eurio_id = ?``). Noter contre une autre colonne que celle qui a servi à
   étiqueter le train mesurerait l'écart entre deux colonnes, pas entre deux
   modèles.

⚠️ **Ce que ça coûte, et qui doit être dit avec le chiffre** : ces 2 crops
(0,7 % du jeu) portent un label dont aucune décision humaine n'est traçable.
Leurs champs de provenance (``decided_at``, ``decided_by``, ``review_kind``)
restent donc **vides dans le manifeste** — la ligne dit elle-même qu'il n'y a
personne derrière —, et le sidecar les compte (``n_sans_decision_review``).
Sur un McNemar dont les paires discordantes peuvent se compter en dizaines,
2 frames mal étiquetées ne sont pas nulles : à relire si un écart est serré.

LA MAILLE — le choix qui décide si la comparaison veut dire quelque chose
--------------------------------------------------------------------------
Il existe **deux** notions de « classe » dans le dépôt, et elles ne coïncident
pas :

* ``design_group`` — ``COALESCE(design_group_id, eurio_id)``. C'est la maille
  du PRODUIT et celle à laquelle ArcFace est entraîné (la cohorte
  ``matrice-60c`` en compte 60) ;
* ``bank`` — ``review.bench_gold._bank_class_id``. C'est sous quel identifiant
  la banque d'ancres indexe la pièce : le représentant du groupe pour une
  **courante**, mais son propre ``eurio_id`` pour une **commémorative**, même
  quand elle appartient à un groupe de dessin.

Mesuré le 2026-08-26 sur les 300 crops : **60 classes en maille
``design_group``, 64 en maille ``bank``**. L'écart vient des **émissions
communes européennes**, que le produit traite comme un seul dessin et que la
banque éclate par pays :

===================== =========================
maille d'éval          classes dans la banque
===================== =========================
``eu-eu-flag-2015``    21
``eu-erasmus-2022``    19
``eu-euro-cash-2012``  18
``eu-emu-2009``        16
``eu-rome-2007``       13
===================== =========================

🔴 **Noter à la maille ``bank`` fabriquerait un handicap.** DINO devrait
désigner le bon PAYS parmi 21 dessins quasi identiques, pendant qu'ArcFace,
entraîné à la maille 60, a raison quoi qu'il dise. On mesurerait l'écart des
MAILLES, pas celui des encodeurs — exactement ce que D5 a été écrit pour
éviter. Le défaut est le même que « le plus loin de la canonique selon DINO » :
un instrument qui décide du résultat.

Le défaut est donc ``mesh="design_group"``. La sous-banque de D3 doit être
repliée sur la **même** maille, sinon le garde d'espace de labels refusera —
et il aura raison.

``mesh="bank"`` reste disponible pour un jeu destiné au banc tel qu'il note
aujourd'hui le gold de review, où ``_bank_class_id`` est la bonne réponse.
Sur ce gold-là, s'être trompé de maille aurait compté **105 crops faux sur
1 958** (5,4 %) sans rien signaler.

Contrat d'import : stdlib + ``review.bench_gold``. Ni numpy, ni torch.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Sequence

# `_bank_class_id` et `_truth_country` sont privés à `bench_gold`, et importés
# ici DÉLIBÉRÉMENT : ce sont les deux pièges documentés du format (classe de
# banque, pays de la vérité). Les réimplémenter donnerait deux versions de la
# même subtilité, ce qui est exactement le genre d'écart que ce format existe
# pour éliminer. On les importe ; on ne les recopie pas.
from review.bench_gold import (  # noqa: PLC2701
    GoldCrop,
    _bank_class_id,
    _truth_country,
)

#: La sélection, en toutes lettres — recopiée dans le sidecar pour qu'un
#: lecteur dans six mois sache ce qui a été retenu sans relire ce fichier.
#: ``LEFT JOIN`` sur ``review_queue`` : sa décision est de la PROVENANCE, pas
#: la vérité (cf. §D'où vient la vérité). Un ``JOIN`` sec perdrait 2 crops en
#: silence et casserait l'invariant « 5 par classe ».
SELECTION_SQL = """
SELECT a.id                          AS asset_id,
       a.eurio_id                    AS truth_eurio_id,
       a.storage_path                AS storage_path,
       COALESCE(rq.decided_face, a.face) AS face,
       rq.decided_at                 AS decided_at,
       rq.decided_by                 AS decided_by,
       rq.kind                       AS review_kind,
       COALESCE(a.training_eligible, 0) AS training_eligible
  FROM image_assets a
  LEFT JOIN review_queue rq
         ON rq.image_asset_id = a.id
        AND rq.status = 'done'
        AND rq.decided_eurio_id IS NOT NULL
 WHERE a.eval_corpus = :corpus
   AND a.eurio_id IS NOT NULL
   AND a.storage_path IS NOT NULL
 ORDER BY a.id
""".strip()


#: Les deux mailles possibles. ``design_group`` est la maille du produit et
#: celle d'ArcFace ; ``bank`` est celle sous laquelle la banque d'ancres indexe.
MESHES = ("design_group", "bank")


def _design_group_class_id(conn: sqlite3.Connection, eurio_id: str) -> str:
    """``COALESCE(design_group_id, eurio_id)`` — la maille du produit.

    Une pièce inconnue rend son propre ``eurio_id`` : le jeu ne ramènera rien
    contre la banque, ce qui est le comportement correct, et l'appelant n'a pas
    à distinguer (même contrat que ``bank_class_ids``).
    """
    row = conn.execute(
        "SELECT COALESCE(design_group_id, eurio_id) FROM coins WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchone()
    return row[0] if row is not None else eurio_id


def build_eval_gold(
    conn: sqlite3.Connection, corpus: str, *, mesh: str = "design_group"
) -> list[GoldCrop]:
    """Le manifeste du corpus ``corpus``, lu depuis une connexion read-only.

    ``mesh`` décide de ce que porte ``class_id``, donc de ce que le banc
    comparera — cf. §LA MAILLE. Le défaut ``design_group`` est la maille du
    produit et celle d'ArcFace ; ``bank`` reproduit celle du gold de review.

    Trié par ``asset_id`` : déterministe, donc diffable, donc hashable sans
    surprise. Aucune écriture, aucun accès stockage.
    """
    if mesh not in MESHES:
        raise ValueError(f"maille inconnue : {mesh!r} (attendu {MESHES})")
    classifier = (
        _design_group_class_id if mesh == "design_group" else _bank_class_id
    )
    precedent = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(SELECTION_SQL, {"corpus": corpus}).fetchall()
        cache: dict[str, str] = {}
        out: list[GoldCrop] = []
        for r in rows:
            verite = r["truth_eurio_id"]
            if verite not in cache:
                cache[verite] = classifier(conn, verite)
            out.append(
                GoldCrop(
                    asset_id=r["asset_id"],
                    truth_eurio_id=verite,
                    class_id=cache[verite],
                    storage_path=r["storage_path"],
                    truth_country=_truth_country(r["asset_id"], verite),
                    face=r["face"],
                    # Vides quand aucune décision de review n'existe : la ligne
                    # doit dire elle-même qu'il n'y a personne derrière.
                    decided_at=r["decided_at"] or "",
                    decided_by=r["decided_by"],
                    review_kind=r["review_kind"],
                    training_eligible=int(r["training_eligible"] or 0),
                )
            )
        return out
    finally:
        conn.row_factory = precedent


def eval_gold_extra(
    rows: Sequence[GoldCrop], corpus: str, *, mesh: str = "design_group",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Le supplément de sidecar propre à un corpus d'éval.

    Trois chiffres que le sidecar générique ne porte pas, et dont chacun
    change la lecture des résultats :

    * ``n_sans_decision_review`` — les crops dont le label n'a aucune décision
      humaine traçable. **Jamais tu.** À zéro c'est une ligne de plus ; non nul
      c'est un plancher de bruit à annoncer avec le chiffre ;
    * ``n_crops_par_classe`` — l'invariant du prélèvement (5, cf. D1). Une
      classe en dessous signale qu'un crop a été perdu quelque part entre le
      marquage et ici ;
    * ``n_non_training_eligible`` — devrait être 0 : le pool de prélèvement
      exigeait ``training_eligible = 1``. Non nul = la review a dégradé un crop
      APRÈS son entrée dans le corpus, et le jeu n'est plus celui qu'on croit.
    """
    par_classe: dict[str, int] = {}
    for r in rows:
        par_classe[r.class_id] = par_classe.get(r.class_id, 0) + 1
    tailles = sorted(set(par_classe.values()))
    return {
        "eval_corpus": corpus,
        # La maille est dans le sidecar, jamais implicite : deux manifestes du
        # MÊME corpus à deux mailles ne notent pas la même tâche, et rien
        # d'autre dans le fichier ne le dirait.
        "mesh": mesh,
        "db_path": db_path,
        "selection_sql": SELECTION_SQL,
        "n_sans_decision_review": sum(1 for r in rows if not r.decided_at),
        "n_non_training_eligible": sum(1 for r in rows if not r.training_eligible),
        "n_crops_par_classe": tailles,
        "classes_hors_quota": sorted(
            c for c, n in par_classe.items() if n != (tailles[-1] if tailles else 0)
        ),
    }
