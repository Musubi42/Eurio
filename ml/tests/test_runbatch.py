"""Tests pour le run-batch export/ingest (Modèle B, chunk C1).

Couvre :
- **Parité** : un run exporté d'une DB → ingéré dans une DB VIERGE → contenu
  identique sur les 9 tables (le serveur canonique reconstruit le run à l'identique).
- **Idempotence** : ré-ingérer le même batch = no-op total (``already_applied``),
  comptages stables, aucun doublon (y compris ``image_state_events`` sans clé
  naturelle).
- **Scoping** : un autre run n'est pas aspiré ; les events de review postérieurs
  (run_id NULL) ne sont pas écrasés par un ré-ingest.

Cf. docs/work-in-progress/model-b/DESIGN.md §C1.
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from client.runbatch import export_run, ingest_run
from store import Store

RUN = "run_test_1"
_HEAVY_TABLES = [
    "source_runs", "source_images", "source_image_runs", "image_assets",
    "listing_text_signals", "image_asset_dino_predictions", "review_queue",
    "consensus_verdicts", "coin_market_quotes", "image_state_events",
]


def _seed_run(conn, run_id=RUN, *, item_offset=0) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO source_registry (id, display_name, kind) "
        "VALUES ('ebay','eBay','marketplace')"
    )
    conn.execute(
        "INSERT INTO source_runs (id, source, kind) VALUES (?, 'ebay', 'run')",
        (run_id,),
    )
    for i in (item_offset, item_offset + 1):
        si = f"si_{run_id}_{i}"
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref, run_id, listing_title) "
            "VALUES (?, 'ebay', ?, ?, ?)",
            (si, f"ebay_item_{i}", run_id, f"Lot {i}"),
        )
        # Lien M:N run↔image (containment par-run) — un run réel l'écrit via
        # upsert_source_image ; ici on le reproduit pour le seed SQL direct.
        conn.execute(
            "INSERT OR IGNORE INTO source_image_runs (source_image_id, run_id) "
            "VALUES (?, ?)",
            (si, run_id),
        )
        conn.execute(
            "INSERT INTO listing_text_signals (source_image_id, coverage) VALUES (?, 'rich')",
            (si,),
        )
        for c in (0, 1):
            aid = f"a_{run_id}_{i}_{c}"
            conn.execute(
                "INSERT INTO image_assets (id, source_image_id, run_id, crop_index, "
                "storage_path) VALUES (?, ?, ?, ?, ?)",
                (aid, si, run_id, c, f"ebay/{aid}.png"),
            )
            conn.execute(
                "INSERT INTO image_asset_dino_predictions "
                "(asset_id, encoder_version, anchors_kind, anchors_count, top_k_json) "
                "VALUES (?, 'dinov2-vits14', '2eur_commemo', 10, '[]')",
                (aid,),
            )
            conn.execute(
                "INSERT INTO review_queue (id, image_asset_id, status) VALUES (?, ?, 'open')",
                (f"rq_{aid}", aid),
            )
            conn.execute(
                "INSERT INTO consensus_verdicts "
                "(image_asset_id, rule_version, outcome, lane, rule) "
                "VALUES (?, 1, 'needs_review', 'manual', 'r1')",
                (aid,),
            )
            conn.execute(
                "INSERT INTO image_state_events (asset_id, to_state, actor, run_id) "
                "VALUES (?, 'queued', 'pipeline', ?)",
                (aid, run_id),
            )
    conn.execute(
        "INSERT INTO coin_market_quotes "
        "(id, eurio_id, source, run_id, period_start, period_end, condition_raw) "
        "VALUES (?, ?, 'ebay', ?, '2026-06-01', '2026-06-07', 'UNC')",
        (f"q_{run_id}", f"be-2007-{run_id}", run_id),
    )


def _dump(conn, run_id=RUN) -> dict[str, list[dict]]:
    """Snapshot comparable des 9 tables pour ce run (events sans l'id autoinc)."""
    b = export_run(conn, run_id)
    return b["tables"]


def test_export_collects_full_run(tmp_path):
    store = Store(tmp_path / "a.db")
    conn = store._connection()  # noqa: SLF001
    _seed_run(conn)
    tables = export_run(conn, RUN)["tables"]
    assert len(tables["source_images"]) == 2
    assert len(tables["image_assets"]) == 4
    assert len(tables["listing_text_signals"]) == 2
    assert len(tables["image_asset_dino_predictions"]) == 4
    assert len(tables["review_queue"]) == 4
    assert len(tables["consensus_verdicts"]) == 4
    assert len(tables["coin_market_quotes"]) == 1
    assert len(tables["image_state_events"]) == 4
    # l'id AUTOINCREMENT des events n'est pas transporté
    assert all("id" not in e for e in tables["image_state_events"])


# ── coin_source_status (D1 : verdict de disponibilité canonique via run-batch) ──
# Contrairement à coin_market_quotes/source_images (pas de FK dimension), la table
# a de vraies FK (eurio_id→coins, source→source_registry) : elle ne s'ingère QUE
# là où ces dimensions existent (le canonique VPS les a). D'où le seed explicite
# des dimensions ci-dessous, côté src ET dst (modèle réel).


def _seed_source_status_dims(conn, run_id=RUN) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO source_registry (id, display_name, kind) "
        "VALUES ('ebay','eBay','reference')"
    )
    conn.execute("INSERT OR IGNORE INTO source_runs (id, source, kind) "
                 "VALUES (?, 'ebay', 'run')", (run_id,))
    conn.execute(
        "INSERT OR IGNORE INTO coins (eurio_id, country, year, face_value) "
        "VALUES (?, 'be', 2007, 2.0)",
        (f"be-2007-{run_id}",),
    )


def test_export_source_status_scoped_by_last_run_id(tmp_path):
    """Seules les rows coin_source_status posées par CE run (last_run_id=run_id)
    voyagent ; le backfill dérivé local (last_run_id NULL) reste sur place."""
    store = Store(tmp_path / "a.db")
    conn = store._connection()  # noqa: SLF001
    _seed_source_status_dims(conn)
    conn.execute(
        "INSERT INTO coin_source_status (eurio_id, source, state, last_run_id) "
        "VALUES (?, 'ebay', 'ok', ?)",
        (f"be-2007-{RUN}", RUN),
    )
    # Backfill dérivé local : verdict sans run_id → ne doit PAS être aspiré.
    conn.execute(
        "INSERT OR IGNORE INTO coins (eurio_id, country, year, face_value) "
        "VALUES ('be-2007-derived', 'be', 2007, 2.0)"
    )
    conn.execute(
        "INSERT INTO coin_source_status (eurio_id, source, state, last_run_id) "
        "VALUES ('be-2007-derived', 'ebay', 'never', NULL)"
    )
    rows = export_run(conn, RUN)["tables"]["coin_source_status"]
    assert len(rows) == 1
    assert rows[0]["eurio_id"] == f"be-2007-{RUN}"
    assert rows[0]["last_run_id"] == RUN


def test_source_status_roundtrip_into_canonical(tmp_path):
    """Round-trip export→ingest : la row voyage et se reconstruit à l'identique
    sur un canonique qui possède déjà les dimensions (coins, source_registry)."""
    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    _seed_source_status_dims(sconn)
    sconn.execute(
        "INSERT INTO coin_source_status (eurio_id, source, state, last_run_id) "
        "VALUES (?, 'ebay', 'ok', ?)",
        (f"be-2007-{RUN}", RUN),
    )
    batch = export_run(sconn, RUN)
    assert len(batch["tables"]["coin_source_status"]) == 1

    dst = Store(tmp_path / "dst.db")
    dconn = dst._connection()  # noqa: SLF001
    _seed_source_status_dims(dconn)  # le canonique a déjà les dimensions
    ingest_run(dconn, batch)

    got = dconn.execute(
        "SELECT eurio_id, source, state, last_run_id FROM coin_source_status"
    ).fetchall()
    assert [tuple(r) for r in got] == [(f"be-2007-{RUN}", "ebay", "ok", RUN)]


def test_parity_export_then_ingest_into_fresh_db(tmp_path):
    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    _seed_run(sconn)
    batch = export_run(sconn, RUN)

    dst = Store(tmp_path / "dst.db")
    dconn = dst._connection()  # noqa: SLF001
    res = ingest_run(dconn, batch)
    assert res["already_applied"] is False

    # Contenu identique sur les 9 tables (le canonique reconstruit le run).
    assert _dump(dconn) == _dump(sconn)
    for t in _HEAVY_TABLES:
        n_src = sconn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        n_dst = dconn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        assert n_dst == n_src, t
    # run journalisé
    assert dconn.execute(
        "SELECT COUNT(*) FROM ingested_runs WHERE run_id=?", (RUN,)
    ).fetchone()[0] == 1


def test_ingest_is_idempotent(tmp_path):
    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    _seed_run(sconn)
    batch = export_run(sconn, RUN)

    dst = Store(tmp_path / "dst.db")
    dconn = dst._connection()  # noqa: SLF001
    ingest_run(dconn, batch)
    before = _dump(dconn)

    res2 = ingest_run(dconn, batch)
    assert res2["already_applied"] is True
    after = _dump(dconn)
    assert after == before  # aucun doublon, y compris image_state_events
    for t in _HEAVY_TABLES:
        assert dconn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == len(before[t])


def test_ingest_scopes_to_run_and_preserves_later_events(tmp_path):
    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    _seed_run(sconn)
    batch = export_run(sconn, RUN)

    dst = Store(tmp_path / "dst.db")
    dconn = dst._connection()  # noqa: SLF001
    ingest_run(dconn, batch)

    # Un autre run présent dans le canonique ne doit pas être touché par le ré-ingest.
    _seed_run(dconn, run_id="other_run", item_offset=100)
    # Un event de REVIEW postérieur (run_id NULL) sur un asset du run ingéré.
    dconn.execute(
        "INSERT INTO image_state_events (asset_id, to_state, actor, run_id) "
        "VALUES (?, 'resolved', 'human', NULL)",
        (f"a_{RUN}_0_0",),
    )
    later_events = dconn.execute(
        "SELECT COUNT(*) FROM image_state_events WHERE run_id IS NULL"
    ).fetchone()[0]

    # Ré-ingest du run (sha inchangé → no-op) : l'event review survit.
    ingest_run(dconn, batch)
    assert dconn.execute(
        "SELECT COUNT(*) FROM image_state_events WHERE run_id IS NULL"
    ).fetchone()[0] == later_events
    # l'autre run intact
    assert dconn.execute(
        "SELECT COUNT(*) FROM source_images WHERE run_id='other_run'"
    ).fetchone()[0] == 2


def test_rescrape_overlap_preserves_first_seen_run_id(tmp_path):
    """Parité A↔B (write-path) : une image re-scrapée par un run ultérieur garde
    son ``run_id`` first-seen (provenance) — le run ultérieur ne VOLE plus
    l'attribution. La containment par-run vit dans ``source_image_runs``, donc
    ``export_run`` de CHAQUE run contient l'image partagée. Repro du cas réel
    f981e819 (16 juin) ↔ a2ff9ffa (CY/2012) qui se partageaient 3 images.
    """
    from sources._base.dedup import SourceImageRow, upsert_source_image

    store = Store(tmp_path / "x.db")
    conn = store._connection()  # noqa: SLF001
    conn.execute(
        "INSERT OR IGNORE INTO source_registry (id, display_name, kind) "
        "VALUES ('ebay','eBay','marketplace')"
    )
    for r in ("run_A", "run_B"):
        conn.execute(
            "INSERT INTO source_runs (id, source, kind) VALUES (?, 'ebay', 'run')", (r,)
        )

    # Run A découvre l'image (prix 10).
    sid_a = upsert_source_image(
        conn,
        SourceImageRow(source="ebay", source_ref="shared_item",
                       run_id="run_A", listing_price=10.0),
    )
    # Run B re-scrape la MÊME image (même source_ref) — prix rafraîchi à 12.
    sid_b = upsert_source_image(
        conn,
        SourceImageRow(source="ebay", source_ref="shared_item",
                       run_id="run_B", listing_price=12.0),
    )
    assert sid_a == sid_b  # dédup par (source, source_ref)

    row = conn.execute(
        "SELECT run_id, listing_price FROM source_images WHERE id=?", (sid_a,)
    ).fetchone()
    assert row["run_id"] == "run_A"      # first-seen immuable (PAS volé par run_B)
    assert row["listing_price"] == 12.0  # contenu mutable bien rafraîchi par le re-scrape

    links = {
        r["run_id"] for r in conn.execute(
            "SELECT run_id FROM source_image_runs WHERE source_image_id=?", (sid_a,)
        )
    }
    assert links == {"run_A", "run_B"}   # les DEUX runs ont touché l'image

    # Containment par junction : chaque run ré-exporte l'image partagée.
    assert [r["id"] for r in export_run(conn, "run_A")["tables"]["source_images"]] == [sid_a]
    assert [r["id"] for r in export_run(conn, "run_B")["tables"]["source_images"]] == [sid_a]


def test_ingest_does_not_steal_run_id_server_side(tmp_path):
    """L'UPSERT canonique ne ré-écrit JAMAIS ``source_images.run_id`` (first-seen
    immuable), même si la réplique MinIO était en retard et croyait l'image neuve
    (donc l'a exportée avec un run_id ultérieur). Le lien (image, run_ultérieur)
    est néanmoins enregistré dans ``source_image_runs``.
    """
    dst = Store(tmp_path / "dst.db")
    dconn = dst._connection()  # noqa: SLF001
    dconn.execute(
        "INSERT OR IGNORE INTO source_registry (id, display_name, kind) "
        "VALUES ('ebay','eBay','marketplace')"
    )
    for r in ("run_A", "run_B"):
        dconn.execute(
            "INSERT INTO source_runs (id, source, kind) VALUES (?, 'ebay', 'run')", (r,)
        )
    # Canonique : image X appartient déjà à run_A.
    dconn.execute(
        "INSERT INTO source_images (id, source, source_ref, run_id) "
        "VALUES ('X','ebay','shared','run_A')"
    )
    dconn.execute(
        "INSERT INTO source_image_runs (source_image_id, run_id) VALUES ('X','run_A')"
    )

    # Réplique "en retard" : run_B porte la MÊME image X avec run_id=run_B.
    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    sconn.execute("INSERT INTO source_runs (id, source, kind) VALUES ('run_B','ebay','run')")
    sconn.execute(
        "INSERT OR IGNORE INTO source_registry (id, display_name, kind) "
        "VALUES ('ebay','eBay','marketplace')"
    )
    sconn.execute(
        "INSERT INTO source_images (id, source, source_ref, run_id) "
        "VALUES ('X','ebay','shared','run_B')"
    )
    sconn.execute(
        "INSERT INTO source_image_runs (source_image_id, run_id) VALUES ('X','run_B')"
    )
    batch = export_run(sconn, "run_B")

    ingest_run(dconn, batch)

    # run_id NON volé côté serveur (reste run_A).
    assert dconn.execute(
        "SELECT run_id FROM source_images WHERE id='X'"
    ).fetchone()[0] == "run_A"
    # mais le lien (X, run_B) est bien enregistré.
    links = {
        r[0] for r in dconn.execute(
            "SELECT run_id FROM source_image_runs WHERE source_image_id='X'"
        )
    }
    assert links == {"run_A", "run_B"}


def test_recrop_run_transports_touched_parent_source_image(tmp_path):
    """C6b : un run recrop (stub source_runs) qui ré-crope un source_image d'un
    AUTRE run doit transporter (a) le nouveau crop (run_id=recrop) ET (b) la
    mutation du source_image parent (crop_status), via le lien source_image_runs.
    Sans le lien, export_run(recrop) ne verrait pas le parent (run_id=ancien run).
    """
    from sources._base.dedup import _link_source_image_run

    store = Store(tmp_path / "x.db")
    conn = store._connection()  # noqa: SLF001
    conn.execute(
        "INSERT OR IGNORE INTO source_registry (id, display_name, kind) "
        "VALUES ('ebay','eBay','marketplace')"
    )
    # Ancien run scrape : 1 source_image zero_crops.
    conn.execute("INSERT INTO source_runs (id, source, kind) VALUES ('scrape','ebay','run')")
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, run_id, crop_status) "
        "VALUES ('X','ebay','ref1','scrape','zero_crops')"
    )
    conn.execute("INSERT INTO source_image_runs (source_image_id, run_id) VALUES ('X','scrape')")

    # Recrop : stub source_runs + mute crop_status + lie le parent + nouveau crop.
    conn.execute(
        "INSERT OR IGNORE INTO source_runs (id, source, kind, status, current_step) "
        "VALUES ('recrop-zero-X','recrop_zero','reset','success','detect')"
    )
    conn.execute("UPDATE source_images SET crop_status='success' WHERE id='X'")
    _link_source_image_run(conn, "X", "recrop-zero-X")
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, run_id, crop_index, "
        "storage_path, storage_status) VALUES ('a1','X','recrop-zero-X',0,'p.png','present')"
    )

    rb = export_run(conn, "recrop-zero-X")["tables"]
    assert [r["id"] for r in rb["source_images"]] == ["X"]
    assert rb["source_images"][0]["crop_status"] == "success"   # mutation transportée
    assert [r["id"] for r in rb["image_assets"]] == ["a1"]       # nouveau crop transporté
    # L'ancien run garde sa containment sur X (provenance préservée).
    assert [r["id"] for r in export_run(conn, "scrape")["tables"]["source_images"]] == ["X"]


def test_dino_backfill_predictions_transported_by_run_id(tmp_path):
    """C6b dino : un backfill DINO produit des prédictions sur des assets
    PRÉEXISTANTS (anciens runs). La prédiction est taguée run_id=backfill →
    export_run la collecte par run_id (l'asset n'appartient pas au backfill run,
    donc le scope par asset_id seul ne la verrait pas). Ingest idempotent.
    """
    def _seed_scrape(conn):
        conn.execute(
            "INSERT OR IGNORE INTO source_registry (id, display_name, kind) "
            "VALUES ('ebay','eBay','marketplace')"
        )
        conn.execute("INSERT INTO source_runs (id, source, kind) VALUES ('scrape','ebay','run')")
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref, run_id) "
            "VALUES ('X','ebay','r','scrape')"
        )
        conn.execute("INSERT INTO source_image_runs (source_image_id, run_id) VALUES ('X','scrape')")
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, run_id, crop_index, "
            "storage_path, storage_status) VALUES ('a1','X','scrape',0,'p.png','present')"
        )

    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    _seed_scrape(sconn)
    # Backfill DINO : stub run + prédiction sur l'asset préexistant 'a1', taguée run_id.
    sconn.execute(
        "INSERT INTO source_runs (id, source, kind, status) "
        "VALUES ('dino-bf','dino_backfill','reset','success')"
    )
    sconn.execute(
        "INSERT INTO image_asset_dino_predictions "
        "(asset_id, encoder_version, anchors_kind, anchors_count, top_k_json, run_id) "
        "VALUES ('a1','dinov2-vits14','2eur_commemo',10,'[]','dino-bf')"
    )

    batch = export_run(sconn, "dino-bf")
    preds = batch["tables"]["image_asset_dino_predictions"]
    assert [d["asset_id"] for d in preds] == ["a1"]      # collectée via run_id
    assert preds[0]["run_id"] == "dino-bf"
    assert batch["tables"]["source_images"] == []        # le backfill ne possède aucune image
    assert batch["tables"]["image_assets"] == []

    # Ingest dans un canonique qui a déjà l'asset (poussé par le run scrape).
    dst = Store(tmp_path / "dst.db")
    dconn = dst._connection()  # noqa: SLF001
    _seed_scrape(dconn)
    res = ingest_run(dconn, batch)
    assert res["already_applied"] is False
    assert dconn.execute(
        "SELECT run_id FROM image_asset_dino_predictions WHERE asset_id='a1'"
    ).fetchone()[0] == "dino-bf"
    # Idempotent : re-POST = no-op.
    assert ingest_run(dconn, batch)["already_applied"] is True


def test_training_run_export_with_recipe_closure(tmp_path):
    """C6c : un training run transporte ses tables run-scopées (runs/steps/epochs/
    classes) + la FK closure des augmentation_recipes (aug_recipe_id + based_on).
    Le run_id = training_runs.id (aucun lien source_runs). Ingest idempotent.
    """
    def _seed_training(conn):
        # Chaîne de recipes : r_base ← r_child (based_on).
        conn.execute(
            "INSERT INTO augmentation_recipes (id, name, config_json) "
            "VALUES ('r_base','base','{}')"
        )
        conn.execute(
            "INSERT INTO augmentation_recipes (id, name, config_json, based_on_recipe_id) "
            "VALUES ('r_child','child','{}','r_base')"
        )
        conn.execute(
            "INSERT INTO training_runs (id, version, status, config_json, "
            "classes_before_json, classes_after_json, classes_added_json, "
            "classes_removed_json, aug_recipe_id) "
            "VALUES ('tr1', 1, 'completed', '{}', '[]', '[]', '[]', '[]', 'r_child')"
        )
        conn.execute(
            "INSERT INTO training_run_steps (run_id, step_index, name, status) "
            "VALUES ('tr1', 0, 'train', 'done')"
        )
        conn.execute(
            "INSERT INTO training_run_epochs (run_id, epoch, train_loss) "
            "VALUES ('tr1', 0, 0.5)"
        )
        conn.execute(
            "INSERT INTO training_run_classes (run_id, class_id, class_kind) "
            "VALUES ('tr1', 'be-2007', 'eurio_id')"
        )

    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    _seed_training(sconn)

    batch = export_run(sconn, "tr1")["tables"]
    assert [r["id"] for r in batch["training_runs"]] == ["tr1"]
    assert len(batch["training_run_steps"]) == 1
    assert len(batch["training_run_epochs"]) == 1
    assert len(batch["training_run_classes"]) == 1
    # FK closure : la recipe directe (r_child) ET son parent (r_base).
    assert [r["id"] for r in batch["augmentation_recipes"]] == ["r_base", "r_child"]
    # Pas de lien source_runs : un training run n'a pas de row source_runs.
    assert batch["source_runs"] == []

    dst = Store(tmp_path / "dst.db")
    dconn = dst._connection()  # noqa: SLF001
    res = ingest_run(dconn, export_run(sconn, "tr1"))
    assert res["already_applied"] is False
    assert dconn.execute(
        "SELECT status FROM training_runs WHERE id='tr1'"
    ).fetchone()[0] == "completed"
    assert dconn.execute(
        "SELECT aug_recipe_id FROM training_runs WHERE id='tr1'"
    ).fetchone()[0] == "r_child"
    # Idempotent.
    assert ingest_run(dconn, export_run(sconn, "tr1"))["already_applied"] is True


def test_reingest_repoints_image_state_current_under_fk_on(tmp_path):
    """Régression : re-ingest d'un run dont les events sont référencés par
    ``image_state_current.last_event_id`` ne doit PAS casser la FK (FK ON serveur).

    L'ingest remplace les events (delete + ré-insert avec de nouveaux id autoinc) ;
    sans recalage de ``image_state_current``, le DELETE viole la FK. On vérifie
    que le chemin réussit et que ``image_state_current`` repointe sur un event valide
    reflétant le dernier état.
    """
    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    _seed_run(sconn)
    batch1 = export_run(sconn, RUN)

    dst = Store(tmp_path / "dst.db")  # FK ON (cf. store.connection)
    dconn = dst._connection()  # noqa: SLF001
    ingest_run(dconn, batch1)

    asset = f"a_{RUN}_0_0"
    # image_state_current pointe désormais sur un event de ce run (via le recalage).
    cur = dconn.execute(
        "SELECT last_event_id, current_state FROM image_state_current WHERE asset_id=?",
        (asset,),
    ).fetchone()
    assert cur is not None and cur["last_event_id"] is not None

    # batch2 : même run, un event SUPPLÉMENTAIRE plus récent → sha différent →
    # force le delete+reinsert (le cas qui cassait la FK).
    batch2 = export_run(sconn, RUN)
    batch2["tables"]["image_state_events"].append({
        "asset_id": asset, "from_state": "queued", "to_state": "resolved",
        "actor": "human", "reason": "test", "eurio_id": None,
        "target_eurio_id": None, "run_id": RUN, "detail_json": None,
        "created_at": "2099-01-01 00:00:00",
    })

    res = ingest_run(dconn, batch2)  # ne doit PAS lever (FK ON)
    assert res["already_applied"] is False

    # image_state_current repointé sur un event valide = le plus récent (resolved).
    row = dconn.execute(
        "SELECT sc.current_state, sc.last_event_id, e.to_state "
        "FROM image_state_current sc JOIN image_state_events e ON e.id=sc.last_event_id "
        "WHERE sc.asset_id=?",
        (asset,),
    ).fetchone()
    assert row is not None, "last_event_id pendant (FK cassée)"
    assert row["current_state"] == "resolved"
    assert row["to_state"] == "resolved"
