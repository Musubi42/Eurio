-- Une seule décision EN ATTENTE par crop.
--
-- review-collaborative-v2, lot 3. `writes._quarantine` vérifiait déjà qu'aucune
-- décision `pending` n'existait avant d'insérer — mais entre la lecture et
-- l'écriture, deux reviewers peuvent passer. La file les sert tous les deux
-- (elle n'exclut que les crops DÉJÀ pending), donc la course est atteignable
-- dès qu'un ami et le PO travaillent la même classe en même temps.
--
-- Ce que ça coûtait sans l'index : les deux décisions atterrissent `pending`,
-- puis `peer_arbitration.approve` clôt `review_queue` pour la première et marque
-- la seconde `superseded`. Le travail de quelqu'un disparaît SANS ERREUR — le
-- pire mode de panne de ce dépôt.
--
-- Avec l'index, la seconde insertion lève une contrainte que la route traduit en
-- 409 : la personne l'apprend tout de suite et passe au crop suivant.
--
-- Index PARTIEL : seul l'état `pending` est contraint. L'historique garde
-- volontairement plusieurs lignes par crop (approved/rejected/superseded) — c'est
-- la trace de qui a proposé quoi, et elle ne doit pas être bridée.
CREATE UNIQUE INDEX IF NOT EXISTS idx_peer_review_une_pendante_par_crop
  ON peer_review_decisions(image_asset_id)
  WHERE arbitration_status = 'pending';
