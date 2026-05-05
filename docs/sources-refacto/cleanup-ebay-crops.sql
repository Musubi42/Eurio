-- Cleanup eBay crops + review_queue avant remise en route avec
-- la nouvelle pipeline multi-Hough.
--
-- ⚠️ AVANT EXEC : faire une copie de la DB
--    cp ml/state/training.db ml/state/training.db.bak-$(date +%Y%m%d)
--
-- Ce script PRÉSERVE :
--   - les `source_images` (raws téléchargés sur disque)
--   - les `image_assets` avec resolution_status='manual' (décisions humaines déjà prises)
--   - les `review_queue` avec status='done' (idem, traçabilité)
--
-- Ce script SUPPRIME :
--   - les `image_assets` non-manual (auto_phash, pending_match, rejected, etc.)
--   - les `review_queue` open/skipped (orphelins après suppression des assets)
--   - reset le `discovery_log.pipeline_state` des source_images concernés à 'downloaded'
--     pour que le re-detect script les reprenne
--
-- Notes schéma :
--   - `review_queue` n'a pas de colonne `source` : on filtre via
--     image_assets → source_images.source.
--   - `pipeline_state` vit sur `discovery_log` (clé (source, source_ref)),
--     pas sur `source_images`.
--
-- Côté FILESYSTEM : les .png crops orphelins seront supprimés par
--   le script Python recrop_ebay_orphans.py (étape suivante).

BEGIN TRANSACTION;

-- 1. Compteurs avant pour validation post-exec
SELECT
  'BEFORE' AS phase,
  (SELECT COUNT(*) FROM image_assets ia
     JOIN source_images si ON si.id = ia.source_image_id
    WHERE si.source = 'ebay') AS image_assets_ebay_total,
  (SELECT COUNT(*) FROM image_assets ia
     JOIN source_images si ON si.id = ia.source_image_id
    WHERE si.source = 'ebay' AND ia.resolution_status = 'manual') AS image_assets_ebay_manual,
  (SELECT COUNT(*) FROM review_queue rq
     JOIN image_assets ia ON ia.id = rq.image_asset_id
     JOIN source_images si ON si.id = ia.source_image_id
    WHERE si.source = 'ebay' AND rq.status IN ('open', 'skipped')) AS review_queue_ebay_open,
  (SELECT COUNT(*) FROM review_queue rq
     JOIN image_assets ia ON ia.id = rq.image_asset_id
     JOIN source_images si ON si.id = ia.source_image_id
    WHERE si.source = 'ebay' AND rq.status = 'done') AS review_queue_ebay_done,
  (SELECT COUNT(*) FROM source_images WHERE source = 'ebay') AS source_images_ebay,
  (SELECT COUNT(*) FROM discovery_log
    WHERE source = 'ebay' AND pipeline_state = 'cropped') AS discovery_ebay_cropped;

-- 2. Suppression review_queue open/skipped côté eBay (les "done" sont préservés
--    pour traçabilité — ils référencent un asset_id qu'on va aussi préserver).
DELETE FROM review_queue
 WHERE status IN ('open', 'skipped')
   AND image_asset_id IN (
     SELECT ia.id FROM image_assets ia
       JOIN source_images si ON si.id = ia.source_image_id
      WHERE si.source = 'ebay'
   );

-- 3. Suppression image_assets non-manual côté eBay.
--    Note : ON DELETE CASCADE des FK doit nettoyer les références (à vérifier).
DELETE FROM image_assets
 WHERE source_image_id IN (SELECT id FROM source_images WHERE source = 'ebay')
   AND (resolution_status IS NULL OR resolution_status != 'manual');

-- 4. Reset n_crops_detected sur source_images dont tous les assets ont été purgés.
UPDATE source_images
   SET n_crops_detected = 0
 WHERE source = 'ebay'
   AND id NOT IN (
     SELECT DISTINCT source_image_id FROM image_assets
      WHERE source_image_id IS NOT NULL
   );

-- 5. Reset discovery_log.pipeline_state pour que detect_crop reprenne ces source_images.
--    Garder ceux qui ont encore des image_assets manual (ne pas re-detect).
UPDATE discovery_log
   SET pipeline_state = 'downloaded'
 WHERE source = 'ebay'
   AND pipeline_state IN ('cropped', 'resolved')
   AND source_ref IN (
     SELECT si.source_ref FROM source_images si
      WHERE si.source = 'ebay'
        AND si.id NOT IN (
          SELECT DISTINCT source_image_id FROM image_assets
           WHERE source_image_id IS NOT NULL
        )
   );

-- 6. Compteurs après
SELECT
  'AFTER' AS phase,
  (SELECT COUNT(*) FROM image_assets ia
     JOIN source_images si ON si.id = ia.source_image_id
    WHERE si.source = 'ebay') AS image_assets_ebay_total,
  (SELECT COUNT(*) FROM image_assets ia
     JOIN source_images si ON si.id = ia.source_image_id
    WHERE si.source = 'ebay' AND ia.resolution_status = 'manual') AS image_assets_ebay_manual,
  (SELECT COUNT(*) FROM review_queue rq
     JOIN image_assets ia ON ia.id = rq.image_asset_id
     JOIN source_images si ON si.id = ia.source_image_id
    WHERE si.source = 'ebay' AND rq.status IN ('open', 'skipped')) AS review_queue_ebay_open,
  (SELECT COUNT(*) FROM review_queue rq
     JOIN image_assets ia ON ia.id = rq.image_asset_id
     JOIN source_images si ON si.id = ia.source_image_id
    WHERE si.source = 'ebay' AND rq.status = 'done') AS review_queue_ebay_done,
  (SELECT COUNT(*) FROM source_images WHERE source = 'ebay') AS source_images_ebay,
  (SELECT COUNT(*) FROM discovery_log
    WHERE source = 'ebay' AND pipeline_state = 'downloaded') AS discovery_ebay_downloaded;

-- ⚠️ COMMIT seulement si les compteurs AFTER te conviennent.
-- Pour annuler : ROLLBACK;
COMMIT;
