"""Le jeu d'or du cadrage — write-half SQL-pure (Direction A).

Une séance d'annotation dure 40 minutes et ne se refait pas. Ce module est ce
qui la rend durable : l'or entre dans le canonique, pas dans un fichier local.
Le pourquoi (table vs bucket, et le gel qui tient RE-5) est dans
`serving/migrations/0019_crop_gold_annotations.sql`.

⚠️ **STDLIB + `store.*` UNIQUEMENT.** Ni `cv2`, ni `torch`, ni `training`, et
surtout pas `review.review_lanes` — il tire `training.foundation` en transitif,
et c'est le défaut qui a tué `backfill_denom --reject` en prod le 2026-08-27 :
échec à l'IMPORT dans l'image lean, avant d'avoir rien tenté.

Contrat transactionnel identique à `store/crops.py` : prend `conn`, ne fait NI
`BEGIN` NI `COMMIT` — le caller possède la transaction.
"""
from __future__ import annotations

import json
import sqlite3

#: Version d'éditeur par défaut. Change quand le GESTE change (poignées,
#: pré-remplissage), pas quand le CSS change : il sert à découper un jeu d'or
#: annoté avec deux outils différents.
EDITOR_VERSION = "gold_v1"


class OrGele(Exception):
    """Écriture refusée : cette version d'or est gelée.

    RE-5 dit « aucune annotation n'est corrigée au passage ». Le dire ne suffit
    pas — la garde doit vivre dans le writer, pas dans la bonne volonté de
    l'annotateur. Un or gelé qu'on peut encore éditer n'est pas un or gelé.
    """


def _champ(obs, nom, defaut=None):
    """Duck-typing pydantic OU dataclass OU dict — comme `store/crops.py`."""
    if isinstance(obs, dict):
        return obs.get(nom, defaut)
    return getattr(obs, nom, defaut)


def assurer_version(conn: sqlite3.Connection, gold_version: str,
                    requete_sha256: str | None = None,
                    note: str | None = None) -> dict:
    """Crée la version si elle manque. Ne dégèle JAMAIS une version gelée."""
    if not gold_version:
        raise ValueError("gold_version vide")
    row = conn.execute(
        "SELECT gold_version, frozen_at, requete_sha256 FROM crop_gold_versions"
        " WHERE gold_version = ?", (gold_version,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO crop_gold_versions (gold_version, requete_sha256, note)"
            " VALUES (?,?,?)", (gold_version, requete_sha256, note))
        return {"gold_version": gold_version, "cree": True, "frozen_at": None}
    frozen = row["frozen_at"] if isinstance(row, sqlite3.Row) else row[1]
    return {"gold_version": gold_version, "cree": False, "frozen_at": frozen}


def _refuser_si_gele(conn: sqlite3.Connection, gold_version: str) -> None:
    row = conn.execute(
        "SELECT frozen_at FROM crop_gold_versions WHERE gold_version = ?",
        (gold_version,)).fetchone()
    if row is not None and row[0]:
        raise OrGele(
            f"l'or {gold_version} est gelé depuis {row[0]} — "
            f"une correction exige une NOUVELLE version (RE-5), "
            f"et la ré-exécution de TOUS les bras")


def enregistrer_annotation(conn: sqlite3.Connection, obs, *, actor: str,
                           gold_version: str) -> dict:
    """Écrit (ou remplace) UNE annotation. `asset_id` inconnu → `missing`.

    Jamais de 404 global : une séance qui perd 59 annotations parce que la
    60ᵉ pointe un asset purgé serait le pire des échecs possibles ici.
    """
    _refuser_si_gele(conn, gold_version)
    asset_id = _champ(obs, "asset_id")
    if not asset_id:
        return {"statut": "invalide", "raison": "asset_id absent"}
    if conn.execute("SELECT 1 FROM image_assets WHERE id = ?",
                    (asset_id,)).fetchone() is None:
        return {"statut": "missing", "asset_id": asset_id}

    indecidable = 1 if _champ(obs, "indecidable", False) else 0
    ell = _champ(obs, "ellipse") or {}
    cx, cy = _champ(ell, "cx"), _champ(ell, "cy")
    a, b = _champ(ell, "a"), _champ(ell, "b")
    theta = _champ(ell, "theta")

    if not indecidable and None in (cx, cy, a, b, theta):
        return {"statut": "invalide", "asset_id": asset_id,
                "raison": "ellipse incomplète et cas non déclaré indécidable"}
    if a is not None and b is not None and b > a:
        # `cv2.fitEllipse` rend (largeur, hauteur), PAS (grand, petit). Laisser
        # entrer l'inversion rendrait tout `d = 0,08·a` faux d'un facteur b/a.
        a, b = b, a
        theta = (theta or 0.0) + 90.0

    passe = int(_champ(obs, "passe", 1) or 1)
    if passe < 1:
        return {"statut": "invalide", "asset_id": asset_id, "raison": "passe < 1"}

    conn.execute(
        "INSERT INTO crop_gold_annotations"
        " (gold_version, asset_id, passe, actor, cx, cy, a, b, theta_deg,"
        "  indecidable, strate_tiree, strate_confirmee, secondes,"
        "  prefill_modifie, editor_version)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(gold_version, asset_id, passe) DO UPDATE SET"
        "   actor = excluded.actor, cx = excluded.cx, cy = excluded.cy,"
        "   a = excluded.a, b = excluded.b, theta_deg = excluded.theta_deg,"
        "   indecidable = excluded.indecidable,"
        "   strate_tiree = excluded.strate_tiree,"
        "   strate_confirmee = excluded.strate_confirmee,"
        "   secondes = excluded.secondes,"
        "   prefill_modifie = excluded.prefill_modifie,"
        "   editor_version = excluded.editor_version,"
        "   updated_at = datetime('now')",
        # Un « indécidable » GARDE son ellipse s'il en a une : elle dit où
        # l'annotateur avait commencé avant de renoncer, et ça se relit.
        (gold_version, asset_id, passe, actor, cx, cy, a, b, theta,
         indecidable, _champ(obs, "strate_tiree"), _champ(obs, "strate_confirmee"),
         _champ(obs, "secondes"),
         None if _champ(obs, "prefill_modifie") is None
         else int(bool(_champ(obs, "prefill_modifie"))),
         _champ(obs, "editor_version") or EDITOR_VERSION))
    return {"statut": "ecrit", "asset_id": asset_id, "passe": passe}


def enregistrer_lot(conn: sqlite3.Connection, annotations, *, actor: str,
                    gold_version: str, requete_sha256: str | None = None) -> dict:
    """Écrit un lot. Rend le compte par statut — jamais un booléen.

    Un « ok » global masquerait la seule chose qu'on veut savoir : lesquelles
    ne sont PAS passées.
    """
    assurer_version(conn, gold_version, requete_sha256)
    # Pas de garde de gel ICI : elle vit dans `enregistrer_annotation`, par où
    # passe TOUTE écriture. La dupliquer donnerait deux gardes qui se couvrent
    # l'une l'autre — donc aucune des deux ne serait tuée par une mutation, donc
    # aucune ne serait vraiment vérifiée.
    resultats = [enregistrer_annotation(conn, o, actor=actor,
                                        gold_version=gold_version)
                 for o in annotations]
    comptes: dict[str, int] = {}
    for r in resultats:
        comptes[r["statut"]] = comptes.get(r["statut"], 0) + 1
    return {"gold_version": gold_version, "comptes": comptes,
            "details": [r for r in resultats if r["statut"] != "ecrit"]}


def lire(conn: sqlite3.Connection, gold_version: str,
         passe: int | None = None) -> list[dict]:
    """Les annotations d'une version, jointes à ce que le banc doit savoir."""
    sql = (
        "SELECT g.*, ia.resolution_status, ia.quality_reason, ia.bbox_json,"
        "       ia.detection_method, si.storage_path AS raw_path,"
        "       si.width, si.height, si.source"
        "  FROM crop_gold_annotations g"
        "  JOIN image_assets ia ON ia.id = g.asset_id"
        "  JOIN source_images si ON si.id = ia.source_image_id"
        " WHERE g.gold_version = ?")
    params: list = [gold_version]
    if passe is not None:
        sql += " AND g.passe = ?"
        params.append(passe)
    sql += " ORDER BY g.passe, g.asset_id"
    return [dict(r) for r in conn.execute(sql, params)]


def geler(conn: sqlite3.Connection, gold_version: str, *,
          snapshot_sha256: str, snapshot_key: str | None = None) -> dict:
    """Gèle une version. Idempotent seulement si le sha est le MÊME.

    Re-geler avec un autre sha voudrait dire que l'or a changé après le gel —
    exactement ce que RE-5 interdit. On refuse au lieu d'écraser.
    """
    row = conn.execute(
        "SELECT frozen_at, snapshot_sha256 FROM crop_gold_versions"
        " WHERE gold_version = ?", (gold_version,)).fetchone()
    if row is None:
        raise ValueError(f"version d'or inconnue : {gold_version}")
    if row[0]:
        if row[1] != snapshot_sha256:
            raise OrGele(
                f"l'or {gold_version} est déjà gelé sur {row[1][:12]}… ; "
                f"un contenu différent ({snapshot_sha256[:12]}…) exige une "
                f"nouvelle version")
        return {"gold_version": gold_version, "frozen_at": row[0], "deja": True}
    conn.execute(
        "UPDATE crop_gold_versions SET frozen_at = datetime('now'),"
        " snapshot_sha256 = ?, snapshot_key = ? WHERE gold_version = ?",
        (snapshot_sha256, snapshot_key, gold_version))
    return {"gold_version": gold_version, "deja": False}


def instantane(conn: sqlite3.Connection, gold_version: str) -> str:
    """Le JSON canonique d'une version — c'est LUI qu'on hache et qu'on gèle.

    Sérialisation déterministe (clés triées, séparateurs fixes) : deux appels
    sur le même contenu doivent rendre le même sha256, sinon le gel ne prouve
    rien.
    """
    lignes = [
        {k: r[k] for k in ("asset_id", "passe", "cx", "cy", "a", "b",
                           "theta_deg", "indecidable", "strate_tiree",
                           "strate_confirmee", "actor", "editor_version")}
        for r in lire(conn, gold_version)
    ]
    return json.dumps({"gold_version": gold_version, "annotations": lignes},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
