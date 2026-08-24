"""Câblage live du consensus à l'enqueue (C3).

Vérifie que ``run_enqueue`` route la lane via la règle de CONSENSUS (et non plus
l'ancien ``compute_lane``/contradict→divergent) ET persiste le verdict dans
``consensus_verdicts``. DB en mémoire bootstrappée depuis le schéma réel.
"""

from __future__ import annotations

import uuid

import pytest

from review.validation.consensus import RULE_VERSION
from shared.verdict_scope import VERDICT_ANCHORS_KIND, VERDICT_ENCODER_VERSION
from sources._base.run_logger import start_run
from sources._base.steps.enqueue import run_enqueue
from store import StoreBase, emit_state_event


@pytest.fixture
def conn(tmp_path):
    # StoreBase bootstrappe le schéma COMPLET (schema.sql + migrations Python) —
    # plus fiable qu'un executescript de schema.sql seul (qui n'a pas les colonnes
    # ajoutées par ALTER : review_queue.kind, source_images.is_lot_suspected, …).
    store = StoreBase(tmp_path / "test.db")
    return store._connection()  # noqa: SLF001


def _seed_asset(
    conn, *, eurio_id, is_commemorative, text_verdict, top1, sim, spread,
    in_bank=True,
):
    """Crée source_image + crop needs_review + dino prediction + text signal +
    coin, et renvoie (source_ref, source_image_id, asset_id).

    ``in_bank`` pose une ligne dans ``dino_class_references`` : depuis la
    bascule sur ``2eur_all``, c'est CETTE table qui dit si l'expert DINO est
    dans son périmètre, plus le drapeau ``is_commemorative``. Une fixture sans
    référence modélise une base où la banque n'a jamais été poussée — un cas
    réel (cf. le WARNING de `target_in_dino_scope`), mais pas le cas nominal.
    """
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative) "
        "VALUES (?, 'FR', 2014, 2.0, ?)",
        (eurio_id, is_commemorative),
    )
    if in_bank:
        conn.execute(
            "INSERT INTO dino_class_references "
            "(anchors_kind, class_id, eurio_id, method, encoder_version) "
            "VALUES (?, ?, ?, 'canonical', ?)",
            (VERDICT_ANCHORS_KIND, eurio_id, eurio_id, VERDICT_ENCODER_VERSION),
        )
    sid = uuid.uuid4().hex
    ref = f"ebay_{sid}"
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
        "listing_title) VALUES (?, 'ebay', ?, ?, 'titre')",
        (sid, ref, eurio_id),
    )
    aid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, "
        "resolution_status, phash, storage_path) "
        "VALUES (?, ?, 0, 'needs_review', 1, '/tmp/x.png')",
        (aid, sid),
    )
    conn.execute(
        "INSERT INTO image_asset_dino_predictions "
        "(asset_id, encoder_version, anchors_kind, anchors_count, top_k_json, "
        " top1_eurio_id, top1_sim, spread, top1_country_eurio_id, top1_country_sim, "
        " country_spread) "
        "VALUES (?, ?, ?, 10, '[]', ?, ?, ?, ?, ?, ?)",
        (aid, VERDICT_ENCODER_VERSION, VERDICT_ANCHORS_KIND,
         top1, sim, spread, top1, sim, spread),
    )
    conn.execute(
        "INSERT INTO listing_text_signals (source_image_id, extractor_version, "
        "coverage, vs_target_verdict) VALUES (?, 'v2', 'rich', ?)",
        (sid, text_verdict),
    )
    # État initial du crop (comme après detect) → transitions legales en aval
    # (detected→queued / detected→rejected).
    emit_state_event(conn, asset_id=aid, to_state="detected", actor="pipeline",
                     reason="seed")
    conn.commit()
    return ref, sid, aid


def _enqueue(conn, ref, sid):
    with start_run(conn, source="ebay", kind="run") as run:
        run.set_step("enqueue")
        run_enqueue(
            conn=conn, run=run, source_id="ebay", source_image_ids={ref: sid},
        )
        run.end("success")


def test_strong_match_routes_auto_accept_and_persists(conn):
    # dino fort + texte convergent + commemo in-scope → accept / auto_accept.
    eid = "fr-2014-2eur-commemo"
    ref, sid, aid = _seed_asset(
        conn, eurio_id=eid, is_commemorative=1, text_verdict="convergent",
        top1=eid, sim=0.9, spread=0.2,
    )
    _enqueue(conn, ref, sid)

    rq = conn.execute(
        "SELECT lane FROM review_queue WHERE image_asset_id = ?", (aid,)
    ).fetchone()
    assert rq["lane"] == "auto_accept"

    cv = conn.execute(
        "SELECT outcome, lane, rule FROM consensus_verdicts WHERE image_asset_id = ?",
        (aid,),
    ).fetchone()
    assert cv is not None
    assert (cv["outcome"], cv["lane"], cv["rule"]) == (
        "accept", "auto_accept", "strong_accept"
    )


def test_contradict_alone_is_rescued_to_manual_not_killed(conn):
    # LE changement clé : texte contradict + dino match (pas mismatch) →
    # needs_review/manual (rescue), PAS reject, PAS de discarded. (ccproxy
    # retiré : le rescue tombe en review humaine.)
    eid = "fr-2014-2eur-commemo"
    ref, sid, aid = _seed_asset(
        conn, eurio_id=eid, is_commemorative=1, text_verdict="contradict",
        top1=eid, sim=0.9, spread=0.2,
    )
    _enqueue(conn, ref, sid)

    rq = conn.execute(
        "SELECT lane FROM review_queue WHERE image_asset_id = ?", (aid,)
    ).fetchone()
    assert rq["lane"] == "manual"
    cv = conn.execute(
        "SELECT outcome, rule FROM consensus_verdicts WHERE image_asset_id = ?",
        (aid,),
    ).fetchone()
    assert (cv["outcome"], cv["rule"]) == ("needs_review", "text_contradict_rescue")
    # le listing est en review, pas jeté.
    n_disc = conn.execute("SELECT COUNT(*) AS n FROM discarded_listings").fetchone()["n"]
    assert n_disc == 0


def test_dual_contradict_auto_rejected_and_reopenable(conn):
    # C5 — texte contradict + dino mismatch in-scope → reject : auto-rejeté
    # (resolution_status='rejected', review_queue 'done', estampillé consensus),
    # PAS jeté ni laissé en queue à trier — et ré-ouvrable.
    eid = "fr-2014-2eur-commemo"
    ref, sid, aid = _seed_asset(
        conn, eurio_id=eid, is_commemorative=1, text_verdict="contradict",
        top1="de-2014-2eur-other", sim=0.9, spread=0.2,
    )
    _enqueue(conn, ref, sid)

    ia = conn.execute(
        "SELECT resolution_status, training_eligible, quality_reason "
        "FROM image_assets WHERE id = ?", (aid,)
    ).fetchone()
    assert ia["resolution_status"] == "rejected"
    assert ia["training_eligible"] == 0
    assert ia["quality_reason"] == "consensus_reject"

    rq = conn.execute(
        "SELECT status, decided_by, decision_notes, decision_engine_version "
        "FROM review_queue WHERE image_asset_id = ?", (aid,)
    ).fetchone()
    assert rq["status"] == "done"
    assert rq["decided_by"] == "consensus"
    assert rq["decision_notes"] == "rejected"
    # Dérivé de RULE_VERSION, pas écrit en dur : le bump de la version de règle
    # DOIT changer cette trace (c'est sa raison d'être), et un littéral ferait
    # rougir le test pour la bonne raison mais au mauvais endroit.
    assert rq["decision_engine_version"] == f"consensus@v{RULE_VERSION}"

    cv = conn.execute(
        "SELECT outcome, rule FROM consensus_verdicts WHERE image_asset_id = ?", (aid,)
    ).fetchone()
    assert (cv["outcome"], cv["rule"]) == ("reject", "dual_contradict")

    # Ré-ouvrable : la même requête JOIN que /rejected (review_queue ⋈
    # image_assets WHERE resolution_status='rejected') retrouve l'item → il
    # s'affiche dans la grille de récupération et /restore peut le ré-ouvrir.
    found = conn.execute(
        "SELECT rq.id FROM review_queue rq JOIN image_assets a "
        "ON a.id = rq.image_asset_id "
        "WHERE a.resolution_status = 'rejected' AND a.id = ?", (aid,)
    ).fetchone()
    assert found is not None


def test_reject_not_counted_as_enqueued(conn):
    # Un auto-reject n'est pas un item de queue : n_enqueued ne le compte pas.
    eid = "fr-2014-2eur-commemo"
    ref, sid, aid = _seed_asset(
        conn, eurio_id=eid, is_commemorative=1, text_verdict="contradict",
        top1="de-2014-2eur-other", sim=0.9, spread=0.2,
    )
    with start_run(conn, source="ebay", kind="run") as run:
        run.set_step("enqueue")
        res = run_enqueue(
            conn=conn, run=run, source_id="ebay", source_image_ids={ref: sid},
        )
        run.end("success")
    assert res.n_enqueued == 0 and res.n_auto_rejected == 1


def test_standard_out_of_scope_not_falsely_rejected(conn):
    # Une pièce ABSENTE de la banque d'ancres, avec texte contradict et
    # top1 ≠ cible : dino abstient (rien à quoi la comparer) → rescue
    # needs_review, PAS reject.
    #
    # Le critère a changé avec la bascule du 2026-08-24 : c'est l'appartenance
    # à la BANQUE qui décide, plus le drapeau `is_commemorative`. `2eur_all`
    # contient 41 classes courantes — un standard n'est plus hors scope par
    # nature, il l'est quand la banque ne le connaît pas.
    eid = "fr-2014-2eur-standard"
    ref, sid, aid = _seed_asset(
        conn, eurio_id=eid, is_commemorative=0, text_verdict="contradict",
        top1="de-2014-2eur-other", sim=0.9, spread=0.2, in_bank=False,
    )
    _enqueue(conn, ref, sid)

    cv = conn.execute(
        "SELECT outcome, rule FROM consensus_verdicts WHERE image_asset_id = ?",
        (aid,),
    ).fetchone()
    assert (cv["outcome"], cv["rule"]) == ("needs_review", "text_contradict_rescue")
