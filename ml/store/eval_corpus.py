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

3. **Le RANGEMENT suit le rôle** (D9, 2026-08-26). ``storage_path`` optionnel
   dans une ligne : c'est la nouvelle clé S3 du crop une fois déplacé dans le
   bucket ``eval-corpus`` sous le préfixe ``eval/<corpus>/``. On l'accepte ici
   — et pas dans une route à part — pour que le rôle et le rangement atterrissent
   dans la MÊME transaction : une base qui dirait « corpus X » en pointant
   encore l'ancienne clé, ou l'inverse, serait un état que rien ne rattrape.
   Le déplacement des octets, lui, est fait par
   ``scripts/move_eval_corpus_objects.py`` AVANT l'appel — on ne réécrit
   jamais une clé vers un objet qui n'est pas encore là.

SQL pur (aucun import de ``cv2``/``numpy``/``training`` : l'image lean du VPS ne
les a pas, et un routeur qui les importe est skippé au boot, en silence).
Commit-free : le caller possède la transaction. ``asset_id`` inconnu →
``missing`` (tolérant, jamais écrit).
"""
from __future__ import annotations

from store.events import emit_field_event


def apply_ingest_eval_corpus(conn, rows) -> dict:
    """Marque (ou démarque) des crops comme appartenant à un corpus d'éval.

    ``rows`` = itérable de dicts ``{asset_id, eval_corpus, storage_path?}``.
    ``eval_corpus`` ``None`` = retrait, et il exige alors ``expect`` (le corpus
    courant) — sans quoi la ligne part en ``conflict``. ``storage_path``
    optionnel = le RANGEMENT qui suit le rôle (D9) : la clé du crop une fois
    déplacé dans ``eval-corpus``.

    Une ligne dont le corpus est déjà posé mais dont la clé change n'est PAS
    ``skipped`` : c'est le deuxième temps normal de la migration (marquer,
    puis déplacer les octets, puis dire où ils sont). La compter ``skipped``
    ferait passer un déplacement pour un no-op.

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
        cible_sp = r.get("storage_path")

        row = conn.execute(
            "SELECT eval_corpus, storage_path FROM image_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()
        if row is None:
            missing.append(asset_id)
            continue
        if hasattr(row, "keys"):
            actuel, actuel_sp = row["eval_corpus"], row["storage_path"]
        else:
            actuel, actuel_sp = row[0], row[1]

        # Le rangement n'a de sens qu'avec un rôle. Réécrire une clé en
        # `eval/…` sur une ligne qu'on retire du corpus laisserait un crop
        # d'entraînement pointant un bucket qu'aucune collecte de train ne
        # regarde — invisible, et impossible à distinguer d'une perte.
        if cible_sp is not None and cible is None:
            conflict.append(asset_id)
            continue

        deplacement = cible_sp is not None and cible_sp != actuel_sp

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
                if not deplacement:
                    skipped += 1
                    continue
                # Même corpus, clé nouvelle : c'est le déplacement. On tombe
                # dans l'UPDATE ci-dessous, qui est idempotent.
            else:
                # Un crop qui change de corpus invaliderait une mesure publiée.
                conflict.append(asset_id)
                continue

        champs = {"image_assets.eval_corpus": cible}
        if deplacement:
            conn.execute(
                "UPDATE image_assets SET eval_corpus = ?, storage_path = ? "
                "WHERE id = ?",
                (cible, cible_sp, asset_id),
            )
            champs["image_assets.storage_path"] = cible_sp
        else:
            conn.execute(
                "UPDATE image_assets SET eval_corpus = ? WHERE id = ?",
                (cible, asset_id),
            )
        emit_field_event(
            conn, asset_id=asset_id, reason="eval_corpus_ingest", actor="pipeline",
            fields=champs,
        )
        updated += 1
    return {
        "updated": updated,
        "skipped": skipped,
        "conflict": conflict,
        "missing": missing,
    }
