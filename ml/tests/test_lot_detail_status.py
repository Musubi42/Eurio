"""Le détail d'un lot dit l'ÉTAT de chaque crop — pas seulement son existence.

La panne, mesurée sur la réplique le 2026-08-26 :

    WITH k AS (SELECT CASE WHEN si.source='ebay'
                 AND json_extract(si.raw_payload_json,'$.ebay_item_id') IS NOT NULL
                 THEN 'ebay_'||json_extract(si.raw_payload_json,'$.ebay_item_id')
                 ELSE si.source_ref END AS lk, rq.status, rq.kind
               FROM review_queue rq
               JOIN image_assets a ON a.id=rq.image_asset_id
               JOIN source_images si ON si.id=a.source_image_id),
         agg AS (SELECT lk, SUM(status='open' AND kind='lot') n_open_lot,
                        SUM(status<>'open') n_closed FROM k GROUP BY lk)
    SELECT COUNT(*), SUM(n_closed) FROM agg WHERE n_open_lot>0 AND n_closed>0;
    -- 751|2303

751 lots encore ouvrables re-servaient 2 303 crops DÉJÀ tranchés comme s'ils
étaient à trancher. `list_lots` filtre `rq.kind='lot' AND rq.status='open'` ;
`get_lot_detail` ne filtrait rien, et ne renvoyait pas non plus de quoi filtrer :
le modèle `LotCrop` ne portait ni `status` ni `kind`. Le contrat écrit — « le
back sert tout, le front filtre » — était donc mort-né, et le front se rabattait
sur `review_id` non vide.

Le correctif ne filtre PAS le JOIN : filtrer ferait disparaître `review_id`, donc
la différence entre « jamais mis en queue » et « déjà tranché » — deux états que
l'écran rend différemment. Il rend l'état, et laisse le consommateur trancher.
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from serving.review_queue import repository
from store import Store


@pytest.fixture()
def conn(tmp_path):
    # Base tmp_path via Store : le devShell pose EURIO_DB_READONLY=1, une
    # écriture sur la réplique échouerait (ou pire, réussirait).
    return Store(tmp_path / "t.db")._connection()  # noqa: SLF001


def _seed_mixte(conn):
    """Un listing, trois crops, trois états — le cas réel d'un lot repris."""
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, listing_country, "
        "storage_path) VALUES ('si-1','ebay','mixte','FR','raw.jpg')",
    )
    etats = [
        ("ouvert", "open", "lot"),
        ("tranche", "done", "lot"),
        ("single", "open", "single"),
    ]
    for idx, (asset, status, kind) in enumerate(etats):
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, storage_path, "
            "storage_status, crop_index, eurio_id) "
            "VALUES (?,'si-1','c.jpg','present',?,?)",
            (asset, idx, "fr-2015-2eur-paix" if status == "done" else None),
        )
        conn.execute(
            "INSERT INTO review_queue (id, image_asset_id, status, kind, lane, "
            "priority, enqueued_at) VALUES (?,?,?,?,'manual',5,'2026-01-01')",
            (f"rq-{asset}", asset, status, kind),
        )
    conn.commit()


def test_le_detail_rend_l_etat_de_chaque_crop(conn):
    _seed_mixte(conn)

    detail = repository.get_lot_detail(conn, "mixte")
    crops = {c.asset_id: c for im in detail.images for c in im.crops}

    # Les trois restent SERVIS : les crops tranchés portent le contexte visuel
    # du coffret (overlay, numérotation des tags). On les montre, on ne les
    # rend pas actionnables.
    assert set(crops) == {"ouvert", "tranche", "single"}

    actionnables = [
        c for c in crops.values()
        if c.review_status == "open" and c.review_kind == "lot"
    ]
    assert [c.asset_id for c in actionnables] == ["ouvert"], (
        "un seul de ces trois crops est encore à trancher en file lot ; "
        "avant le correctif l'écran en proposait trois"
    )

    assert (crops["tranche"].review_status, crops["tranche"].review_kind) == (
        "done", "lot",
    )
    assert (crops["single"].review_status, crops["single"].review_kind) == (
        "open", "single",
    )
    # Et `review_id` reste renseigné pour les trois : c'est lui qui distingue
    # « déjà tranché » de « jamais mis en queue ».
    assert all(c.review_id for c in crops.values())


def test_un_crop_jamais_mis_en_queue_n_a_pas_d_etat(conn):
    """L'état que le filtre SQL aurait effacé : ni review_id, ni statut."""
    _seed_mixte(conn)
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, "
        "storage_status, crop_index) "
        "VALUES ('orphelin','si-1','c.jpg','present',9)",
    )
    conn.commit()

    detail = repository.get_lot_detail(conn, "mixte")
    crops = {c.asset_id: c for im in detail.images for c in im.crops}
    orphelin = crops["orphelin"]
    assert orphelin.review_id == ""
    assert orphelin.review_status is None
    assert orphelin.review_kind is None
