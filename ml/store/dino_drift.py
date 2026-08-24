"""L'écart entre la banque d'ancres SERVIE et la donnée qui a bougé depuis.

Répond à une seule question, celle que l'admin se pose devant son accueil :
**« est-ce que ça vaut le coup de relancer un rebuild maintenant ? »**

SQL pur, stdlib pure : ce module est lu par l'image lean du VPS, qui n'a ni
numpy ni torch. Aucune écriture, aucune décision — il compte, il ne juge pas.

⛔ **Le piège des horodatages, déjà payé une fois.** Trois formats cohabitent
dans la même base :

    image_asset_dino_predictions.computed_at → '2026-08-23 17:51:31'
    review_queue.decided_at                  → '2026-08-24T16:09:58Z'
    dino_anchor_builds.built_at              → '2026-08-22T18:06:22+00:00'

L'espace vaut 0x20, le 'T' vaut 0x54 : comparer les CHAÎNES classe toute
prédiction comme antérieure à tout build du même jour. Mesuré le 2026-08-20 par
`store/encoder_bench.py` : `SUM(computed_at < built_at)` rendait 12 454 là où la
vraie réponse était 0. Toutes les comparaisons de ce module passent donc par
`datetime()` des DEUX côtés. Ne jamais l'enlever « pour simplifier ».
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict

from shared.bank_classes import bank_class_ids


@dataclass(frozen=True)
class DinoDrift:
    """Ce que le prochain rebuild changerait, et ce qui est déjà périmé."""

    anchors_kind: str
    encoder_version: str

    # La banque servie aujourd'hui.
    build_id: str | None
    built_at: str | None
    n_classes: int | None
    n_rows: int | None

    # Ce qui a bougé depuis qu'elle a été bâtie.
    n_crops_validated_since: int
    n_classes_touched_since: int
    n_classes_would_gain_anchor: int

    # Ce qui est déjà incohérent avec elle.
    n_predictions_stale: int
    n_assets_without_prediction: int

    def as_dict(self) -> dict:
        d = asdict(self)
        d["is_stale"] = self.is_stale
        return d

    @property
    def is_stale(self) -> bool:
        """Y a-t-il quelque chose à gagner à relancer maintenant ?

        « Jamais bâtie » compte comme périmé : l'absence de banque n'est pas un
        état neutre, c'est le pire des états — et c'est précisément celui où un
        écart de zéro serait le plus trompeur.
        """
        return (
            self.built_at is None
            or self.n_predictions_stale > 0
            or self.n_assets_without_prediction > 0
            or self.n_classes_would_gain_anchor > 0
        )


_TABLES = ("dino_anchor_builds", "image_asset_dino_predictions",
           "dino_class_references", "image_assets", "review_queue")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


class DriftNotMeasurable(RuntimeError):
    """Une table manque : on ne rend PAS un écart de zéro rassurant."""


def dino_drift(
    conn: sqlite3.Connection, *, anchors_kind: str, encoder_version: str,
) -> DinoDrift:
    """L'écart pour un couple (banque, encodeur). Lecture seule.

    Lève `DriftNotMeasurable` si une table manque — plutôt que de rendre des
    zéros, qui se liraient « tout est à jour ». Un écart non mesurable et un
    écart nul ne doivent jamais avoir la même tête à l'écran.
    """
    manquantes = [t for t in _TABLES if not _table_exists(conn, t)]
    if manquantes:
        raise DriftNotMeasurable(
            f"écart DINO non mesurable — table(s) absente(s) : "
            f"{', '.join(manquantes)}"
        )

    build = conn.execute(
        "SELECT build_id, built_at, n_classes, n_rows FROM dino_anchor_builds "
        " WHERE anchors_kind = ? AND encoder_version = ? "
        " ORDER BY datetime(built_at) DESC LIMIT 1",
        (anchors_kind, encoder_version),
    ).fetchone()
    built_at = build["built_at"] if build else None

    # Prédictions antérieures au build servi : elles répondent sur une banque
    # qui n'existe plus. Sans build tracé, la question n'a pas de sens — on
    # laisse 0 et `is_stale` se déclenche par `built_at is None`.
    n_stale = 0
    if built_at:
        n_stale = conn.execute(
            "SELECT COALESCE(SUM(datetime(computed_at) < datetime(?)), 0) "
            "  FROM image_asset_dino_predictions "
            " WHERE anchors_kind = ? AND encoder_version = ?",
            (built_at, anchors_kind, encoder_version),
        ).fetchone()[0]

    # Crops que le backfill DEVRAIT couvrir et qui n'ont pourtant aucune
    # prédiction : le scrape a produit, le backfill n'a pas suivi.
    #
    # 🔴 Corrigé en revue le 2026-08-24. La version d'avant comptait TOUS les
    # assets présents — or `_select_assets_for_backfill`
    # (`sources/_base/steps/auto_validate.py`) ne traite jamais un crop dont
    # l'annonce vise une pièce qui n'est pas 2 €. Ces crops-là n'auront donc
    # JAMAIS de prédiction, quoi qu'on relance : le compteur ne pouvait pas
    # retomber à zéro, `is_stale` restait vrai à vie, la branche « à jour » de
    # la carte était inatteignable, et l'écran réclamait éternellement un
    # rebuild de vingt minutes qui n'y changeait rien. Un chiffre qu'aucune
    # action ne fait bouger n'est pas un écart, c'est du bruit.
    #
    # Le prédicat ci-dessous est le MIROIR de la branche `2eur_all` du sélecteur
    # (cible 2 € OU pool ambigu). S'il dérive, ce compteur redevient faux en
    # silence — c'est la contrepartie assumée de ne pas importer `sources.` ici
    # (ce module est lu par l'image lean, qui ne l'embarque pas).
    n_sans_pred = conn.execute(
        "SELECT COUNT(*) FROM image_assets a "
        "  JOIN source_images s ON s.id = a.source_image_id "
        "  LEFT JOIN coins c ON c.eurio_id = s.target_eurio_id "
        " WHERE a.storage_status = 'present' AND a.storage_path IS NOT NULL "
        "   AND (c.face_value = 2.0 OR s.target_eurio_id IS NULL) "
        "   AND NOT EXISTS (SELECT 1 FROM image_asset_dino_predictions p "
        "                    WHERE p.asset_id = a.id AND p.anchors_kind = ? "
        "                      AND p.encoder_version = ?)",
        (anchors_kind, encoder_version),
    ).fetchone()[0]

    # Le travail humain accumulé depuis le build. C'est LUI que le bouton
    # convertit en ancres — et c'est le seul chiffre qui parle à l'opérateur :
    # « tu as trié 182 crops depuis le dernier rebuild ».
    n_valides, n_classes_touchees = 0, 0
    if built_at:
        row = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT a.eurio_id) "
            "  FROM review_queue rq JOIN image_assets a ON a.id = rq.image_asset_id "
            " WHERE rq.status = 'done' AND a.training_eligible = 1 "
            "   AND a.storage_status = 'present' AND a.eurio_id IS NOT NULL "
            "   AND rq.decided_at IS NOT NULL "
            "   AND datetime(rq.decided_at) > datetime(?)",
            (built_at,),
        ).fetchone()
        n_valides, n_classes_touchees = row[0], row[1]

    # Classes qui ont de quoi porter un exemplaire mais n'en ont aucun dans la
    # banque servie : le rebuild les ferait passer du rendu Numista seul à une
    # vraie photo. C'est le gain le plus fort par exemplaire (cf. la courbe
    # références/classe, skill `eurio-banque` §3).
    #
    # ⛔ **La maille est `class_id`, jamais `eurio_id`** — et ce module s'y était
    # trompé jusqu'à la revue du 2026-08-24. La banque n'indexe pas une pièce
    # COURANTE sous son propre identifiant mais sous celui du REPRÉSENTANT de
    # son groupe de dessin (`fr-1999-…` est en banque, `fr-2007-…` non). Une
    # comparaison directe classait donc toute courante non-représentante comme
    # « gagnerait une photo », **à jamais** : aucun rebuild ne pouvait faire
    # baisser ce compteur, puisque rien ne l'y ferait entrer sous ce nom-là.
    # La traduction passe par `shared.bank_classes`, comme partout ailleurs.
    exemplaires = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT class_id FROM dino_class_references "
            " WHERE anchors_kind = ? AND encoder_version = ? AND method = 'fps'",
            (anchors_kind, encoder_version),
        )
    }
    n_gagnantes = 0
    for (eurio_id,) in conn.execute(
        "SELECT DISTINCT a.eurio_id FROM image_assets a "
        " WHERE a.training_eligible = 1 AND a.storage_status = 'present' "
        "   AND a.eurio_id IS NOT NULL "
        "   AND (a.face IS NULL OR a.face != 'reverse')"
    ):
        if not (set(bank_class_ids(conn, eurio_id)) & exemplaires):
            n_gagnantes += 1

    return DinoDrift(
        anchors_kind=anchors_kind,
        encoder_version=encoder_version,
        build_id=build["build_id"] if build else None,
        built_at=built_at,
        n_classes=build["n_classes"] if build else None,
        n_rows=build["n_rows"] if build else None,
        n_crops_validated_since=n_valides,
        n_classes_touched_since=n_classes_touchees,
        n_classes_would_gain_anchor=n_gagnantes,
        n_predictions_stale=int(n_stale),
        n_assets_without_prediction=n_sans_pred,
    )
