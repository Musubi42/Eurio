"""Ingest du marquage « jeu d'évaluation » — write-half SQL-pure (Direction A).

Pourquoi ce helper existe : la SÉLECTION des crops d'éval a besoin de lire les
mesures géométriques du parc et de tirer un rang déterministe par classe ; elle
tourne donc sur le Mac, qui lit une **réplique read-only**. Le VPS est le seul
writer canonique. Même constat, mot pour mot, que ``store/quality.py`` : le
calcul reste où il peut se faire, les **lignes** voyagent.

Deux gardes, et elles sont le contrat :

1. **Jamais d'écrasement silencieux d'un autre corpus.** Si un crop porte déjà
   ``eval_corpus`` et qu'on lui en demande un AUTRE, la ligne est refusée
   (``conflict``) et non réécrite : un crop qui change de corpus invaliderait
   rétroactivement une mesure déjà publiée. Le même corpus est idempotent
   (``skipped``).
2. **``training_eligible`` n'est pas touché.** Il porte le verdict de la REVIEW
   (« ce crop est-il bon ? ») ; ``eval_corpus`` porte un RÔLE (« à quoi
   sert-il ? »). Les confondre ferait disparaître les crops d'éval des
   compteurs de review et rendrait le retour au train impossible à distinguer
   d'une réhabilitation.

Le retrait est explicite : ``eval_corpus = None`` **avec** le corpus courant
attendu dans ``expect``, sinon la ligne est refusée. Rien ne s'efface par
omission.

SQL pur (aucun import de ``cv2``/``numpy``/``training`` : l'image lean du VPS ne
les a pas, et un routeur qui les importe est skippé au boot, en silence).
Commit-free : le caller possède la transaction. ``asset_id`` inconnu →
``missing`` (tolérant, jamais écrit).
"""
from __future__ import annotations

from store.events import emit_field_event


def apply_ingest_eval_corpus(conn, rows) -> dict:
    """Marque (ou démarque) des crops comme appartenant à un corpus d'éval.

    ``rows`` = itérable de dicts ``{asset_id, eval_corpus}``. ``eval_corpus``
    ``None`` = retrait, et il exige alors ``expect`` (le corpus courant) — sans
    quoi la ligne part en ``conflict``.

    Retourne ``{"updated": n, "skipped": m, "conflict": [asset_id…],
    "missing": [asset_id…]}``.
    """
    updated = 0
    skipped = 0
    conflict: list = []
    missing: list = []
    for r in rows:
        asset_id = r["asset_id"]
        cible = r.get("eval_corpus")

        row = conn.execute(
            "SELECT eval_corpus FROM image_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            missing.append(asset_id)
            continue
        actuel = row[0] if not hasattr(row, "keys") else row["eval_corpus"]

        if cible is None:
            # Retrait : jamais par omission. Le caller DOIT nommer le corpus
            # qu'il croit retirer, sinon on refuse.
            if actuel is None:
                skipped += 1
                continue
            if r.get("expect") != actuel:
                conflict.append(asset_id)
                continue
        elif actuel is not None:
            if actuel == cible:
                skipped += 1
                continue
            # Un crop qui change de corpus invaliderait une mesure publiée.
            conflict.append(asset_id)
            continue

        conn.execute(
            "UPDATE image_assets SET eval_corpus = ? WHERE id = ?", (cible, asset_id)
        )
        emit_field_event(
            conn, asset_id=asset_id, reason="eval_corpus_ingest", actor="pipeline",
            fields={"image_assets.eval_corpus": cible},
        )
        updated += 1
    return {
        "updated": updated,
        "skipped": skipped,
        "conflict": conflict,
        "missing": missing,
    }
