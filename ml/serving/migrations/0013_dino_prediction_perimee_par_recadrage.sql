-- 0013 — une prédiction DINO peut être PÉRIMÉE sans être absente.
--
-- Contexte (review-collaborative-v2, lot 6b + retour du PO). Le recadrage à
-- distance marquait le crop « DINO à réencoder » en SUPPRIMANT ses prédictions :
-- l'absence servait de marqueur, et `backfill_dino_predictions` reprenait
-- exactement les assets sans ligne. Zéro schéma, mais un défaut d'usage majeur,
-- constaté dès la première vraie session :
--
--   « moi je commence toujours par faire le recadrage et après je pick la bonne
--     pièce. Souvent, la suggestion de Dino de base est bonne. »
--
-- Le geste réel est un ajustement AU MICRO du cadrage, suivi du choix de la
-- pièce. Supprimer la prédiction retire l'aide juste avant le moment où elle
-- sert, pour un recadrage qui, neuf fois sur dix, ne la change pas.
--
-- D'où cette colonne : la prédiction RESTE servie, avec la date à laquelle un
-- recadrage l'a rendue suspecte. L'écran peut le dire, l'humain arbitre — et le
-- rattrapage en lot reste programmé, `_existing_keys` traitant une ligne périmée
-- comme absente (donc réencodée SANS `--force`). Un ré-encodage remet la colonne
-- à NULL : la prédiction redevient fraîche parce qu'elle a été recalculée, pas
-- parce qu'on a oublié qu'elle ne l'était pas.
--
-- Rétrocompatible : NULL = « jamais périmée », c'est-à-dire l'état de toutes les
-- lignes existantes.

ALTER TABLE image_asset_dino_predictions ADD COLUMN stale_since TEXT;

-- Index partiel : la question posée est « lesquelles sont à réencoder ? », donc
-- une poignée de lignes sur des dizaines de milliers. Un index plein coûterait
-- pour une réponse qui tient dans un mouchoir.
CREATE INDEX IF NOT EXISTS idx_dino_predictions_stale
  ON image_asset_dino_predictions(stale_since)
  WHERE stale_since IS NOT NULL;
