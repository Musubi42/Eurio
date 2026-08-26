-- 0017 — `image_assets.face_source` : qui a écrit la face.
--
-- Chantier `debit-enrichissement`. Le défaut, mesuré le 2026-08-27 après le
-- banc à l'aveugle (le PO : « y'a eu pas mal de revers dans le lot ») :
--
--   · l'étiquette de face est écrite UNE SEULE FOIS
--     (`sources/_base/steps/auto_validate.py`, `WHERE id=? AND face IS NULL` ;
--     `store/faces.py`, `AND (face IS NULL OR face='unknown')`) ;
--   · et le seuil qui la décide DÉRIVE tout seul : la marge est
--     `max cos sur les ancres de REVERS − max cos sur la banque des AVERS`,
--     soit 34 vecteurs contre 2 062. Un max sur plus de vecteurs est plus haut
--     par construction, donc chaque rebuild de la banque des avers rabote la
--     marge. Rejoué le 2026-08-27 avec `scripts/bench_face_recall.py`, τ et
--     gold inchangés depuis le 2026-06-13 : rappel des revers durs
--     **73,3 % → 40,0 %**, des revers faciles **100 % → 80,0 %**.
--
-- Les deux ensemble donnent une étiquette FAUSSE ET DÉFINITIVE. En base au
-- 2026-08-27 : 237 assets `obverse` que la marge dit revers, 343 `reverse`
-- qu'elle dit avers, 289 sans étiquette qu'elle dit revers. Dans la file
-- ouverte, 290 crops ont une marge ≥ τ — dont 198 sans aucune étiquette.
--
-- Le garde d'écriture unique n'est PAS l'erreur : il protège les labels
-- humains (`review_queue.decided_face → image_assets.face`), et ça doit
-- rester vrai. L'erreur est que **la colonne ne sait pas qui l'a écrite**,
-- donc protéger l'humain oblige à geler aussi la machine.
--
-- D'où cette colonne, et non un assouplissement du garde. Le précédent du
-- dépôt est `listing_text_signals.extractor_version='manual'` : la provenance
-- vit dans une colonne, pas dans une convention.
--
--   NULL      = provenance inconnue (aucune ligne ne devrait rester ainsi
--               après le backfill ci-dessous, sauf `face IS NULL`) ;
--   'pipeline'= posée par la passe de face → RECALCULABLE ;
--   'human'   = verdict humain → JAMAIS écrasée, par personne.
--
-- Le backfill est EXACT et complet, pas une heuristique : `review_queue`
-- garde `decided_face`, qui est la trace durable du geste humain. Vérifié le
-- 2026-08-27 : 3 284 assets portent un `decided_face`, tous ont une face en
-- `image_assets`, et les deux sont cohérents. On ne retient que les verdicts
-- qui tranchent VRAIMENT une face — `decided_face='unknown'` (162 lignes)
-- n'est pas un jugement sur la face, donc n'immunise pas la ligne.
--
-- ⚠️ Miroir DDL obligatoire dans `ml/state/schema.sql` (les bases locales ne
-- rejouent pas les migrations, elles bootstrappent depuis schema.sql), plus
-- `_ensure_column` PRE-bootstrap dans `store/connection.py`.

ALTER TABLE image_assets
  ADD COLUMN face_source TEXT
  CHECK (face_source IS NULL OR face_source IN ('pipeline', 'human'));

-- 1. Les verdicts humains d'abord — ils ne doivent JAMAIS être écrasés.
UPDATE image_assets
   SET face_source = 'human'
 WHERE id IN (
   SELECT rq.image_asset_id FROM review_queue rq
    WHERE rq.decided_face IN ('obverse', 'reverse')
 );

-- 2. Tout le reste qui porte une face vient de la passe automatique.
UPDATE image_assets
   SET face_source = 'pipeline'
 WHERE face IS NOT NULL
   AND face_source IS NULL;

CREATE INDEX IF NOT EXISTS idx_image_assets_face_source
  ON image_assets(face_source)
  WHERE face_source = 'pipeline';
