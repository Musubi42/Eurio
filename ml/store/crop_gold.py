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


def ordonner_demi_axes(a, b, theta):
    """`(a, b, theta)` avec `a` = demi-GRAND axe, quoi qu'on ait reçu.

    `cv2.fitEllipse` rend (largeur, hauteur), PAS (grand, petit). Laisser entrer
    l'inversion rendrait tout `d = 0,08·a` faux d'un facteur b/a — et côté
    tirage, elle donnerait à l'annotateur une ellipse tournée de 90°. Un seul
    endroit pour la remettre d'aplomb : deux normalisations divergeraient.
    """
    if a is not None and b is not None and b > a:
        return b, a, (theta or 0.0) + 90.0
    return a, b, theta


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
    a, b, theta = ordonner_demi_axes(a, b, theta)

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
        "       ia.detection_method, si.id AS source_image_id,"
        "       si.storage_path AS raw_path,"
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


# ─── Le TIRAGE : ce qu'il y a À annoter (D12, migration 0020) ───────────────

def enregistrer_tirage(conn: sqlite3.Connection, images, *, gold_version: str,
                       requete_sha256: str | None = None) -> dict:
    """Publie (ou republie) le tirage d'une version. Idempotent par asset.

    Trois refus, et un non-refus :

    * la version est GELÉE → `OrGele`. Le tirage fait partie de l'or : le
      changer après le gel changerait la population mesurée, ce que RE-5
      interdit exactement comme il interdit de corriger une annotation ;
    * la version existe déjà avec une AUTRE `requete_sha256` → `ValueError`.
      Un tirage et sa version viennent de la même requête d'échantillonnage ;
      les découpler rendrait le jeu irreproductible en le laissant croire
      reproductible, ce qui est pire (RE-5) ;
    * un `asset_id` absent d'`image_assets` → compté dans `ignorees`, JAMAIS un
      404 global. Perdre 83 images parce que la 84ᵉ pointe un asset purgé
      serait ici le pire échec possible — même doctrine que
      `enregistrer_annotation`.
    """
    _refuser_si_gele(conn, gold_version)

    row = conn.execute(
        "SELECT requete_sha256 FROM crop_gold_versions WHERE gold_version = ?",
        (gold_version,)).fetchone()
    if row is None:
        assurer_version(conn, gold_version, requete_sha256)
    else:
        connue = row[0]
        if connue and requete_sha256 and connue != requete_sha256:
            raise ValueError(
                f"la version {gold_version} a été créée sur la requête "
                f"{connue[:12]}… ; ce tirage vient de {requete_sha256[:12]}… — "
                f"un tirage et sa version sortent de la MÊME requête, sinon le "
                f"jeu n'est pas reproductible (RE-5). Publie-le sous une "
                f"nouvelle version.")

    n = 0
    ignorees: list[str] = []
    for img in images:
        asset_id = _champ(img, "asset_id")
        if not asset_id or conn.execute(
                "SELECT 1 FROM image_assets WHERE id = ?",
                (asset_id,)).fetchone() is None:
            ignorees.append(asset_id or "(asset_id absent)")
            continue

        hint = _champ(img, "hint") or {}
        pre = _champ(img, "prefill") or {}
        pcx, pcy = _champ(pre, "cx"), _champ(pre, "cy")
        pa, pb = _champ(pre, "a"), _champ(pre, "b")
        ptheta = _champ(pre, "theta_deg")
        if None in (pcx, pcy, pa, pb, ptheta):
            # Tout ou rien : un pré-remplissage à moitié rempli serait une
            # proposition au jugé, et la contrainte de 0020 le refuserait de
            # toute façon — autant que ce soit lisible ici.
            pcx = pcy = pa = pb = ptheta = None
        else:
            pa, pb, ptheta = ordonner_demi_axes(pa, pb, ptheta)

        conn.execute(
            "INSERT INTO crop_gold_tirage"
            " (gold_version, asset_id, role, rn, strate_tiree, width, height,"
            "  hint_cx, hint_cy, hint_r, prefill_cx, prefill_cy, prefill_a,"
            "  prefill_b, prefill_theta_deg, prefill_reason)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(gold_version, asset_id) DO UPDATE SET"
            "   role = excluded.role, rn = excluded.rn,"
            "   strate_tiree = excluded.strate_tiree,"
            "   width = excluded.width, height = excluded.height,"
            "   hint_cx = excluded.hint_cx, hint_cy = excluded.hint_cy,"
            "   hint_r = excluded.hint_r,"
            "   prefill_cx = excluded.prefill_cx,"
            "   prefill_cy = excluded.prefill_cy,"
            "   prefill_a = excluded.prefill_a, prefill_b = excluded.prefill_b,"
            "   prefill_theta_deg = excluded.prefill_theta_deg,"
            "   prefill_reason = excluded.prefill_reason",
            (gold_version, asset_id, _champ(img, "role", "tirage"),
             _champ(img, "rn"), _champ(img, "strate_tiree"),
             _champ(img, "width"), _champ(img, "height"),
             _champ(hint, "cx"), _champ(hint, "cy"), _champ(hint, "r"),
             pcx, pcy, pa, pb, ptheta, _champ(img, "prefill_reason")))
        n += 1
    return {"gold_version": gold_version, "n": n, "ignorees": ignorees}


def lire_tirage(conn: sqlite3.Connection, gold_version: str,
                role: str | None = None) -> list[dict]:
    """Le tirage d'une version, joint à ce qu'il faut pour l'AFFICHER.

    Même jointure que `lire()` : le front hébergé n'a pas accès au disque du
    Mac, il lui faut `source` / `source_image_id` / `raw_path` pour qu'une URL
    servable soit fabriquée. Sans eux la galerie est aveugle hors de la machine
    du ML.

    Ordre : 'tirage' avant 'reserve', puis strate, puis rang — c'est l'ordre de
    la séance, et il doit être le même pour deux annotateurs.
    """
    sql = (
        "SELECT t.*, si.id AS source_image_id, si.source,"
        "       si.storage_path AS raw_path"
        "  FROM crop_gold_tirage t"
        "  JOIN image_assets ia ON ia.id = t.asset_id"
        "  JOIN source_images si ON si.id = ia.source_image_id"
        " WHERE t.gold_version = ?")
    params: list = [gold_version]
    if role is not None:
        sql += " AND t.role = ?"
        params.append(role)
    sql += (" ORDER BY CASE t.role WHEN 'tirage' THEN 0 ELSE 1 END,"
            " t.strate_tiree, t.rn, t.asset_id")
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
