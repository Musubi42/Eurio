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
