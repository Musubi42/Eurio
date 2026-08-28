-- 0019 — Le jeu d'or du cadrage vit dans le CANONIQUE, pas dans un fichier.
--
-- Chantier `juge-du-crop`, lot L2 (ADR-017). L'or, c'est ~60 ellipses tracées
-- à la main par le PO en 40 minutes. On ne les retrace pas.
--
-- **Pourquoi une table, et pas un bucket** — mesuré le 2026-08-28 :
--
--   · `MIRROR_BUCKETS` (`infra/backup/eurio-backup.sh:74`) est une liste EN
--     DUR. Un bucket neuf en est absent, donc hors des cinq anneaux, et
--     l'oubli est MUET. Ce n'est pas une crainte : `eval-corpus`, créé le
--     2026-08-26 pour le corpus qui a tranché ArcFace ↔ DINO, y a manqué deux
--     jours — et l'invariant [3] rougissait pendant ce temps ;
--   · `eurio.db` est capturée par CONSTRUCTION (`VACUUM INTO`) ;
--   · l'or doit se JOINDRE à `image_assets` (strate, verdict humain,
--     `detection_method`) — un blob JSON ne se joint pas ;
--   · le front hébergé doit pouvoir l'afficher, donc il faut une route, donc
--     il faut du SQL ;
--   · `crop_edit_observations` (0018) porte déjà la même nature de donnée —
--     un verdict géométrique humain. Deux rangements pour une même nature,
--     c'est la dette que R0 interdit.
--
-- **Et RE-5 alors** (« l'or est un artefact de données, versionné, immuable ;
-- aucune annotation n'est corrigée au passage ») ? Il est tenu par le GEL, pas
-- par le support. Tant que `crop_gold_versions.frozen_at` est NULL, la version
-- s'annote — c'est la séance. Une fois gelée, elle est en lecture seule et son
-- instantané part dans `model-artifacts`, bucket DÉJÀ miroité. Un or modifié =
-- une nouvelle version = tous les bras ré-exécutés.
--
-- Le gel est ce qui rend RE-5 exécutable au lieu d'être une consigne : la
-- garde vit dans le writer, pas dans la bonne volonté de l'annotateur.

CREATE TABLE IF NOT EXISTS crop_gold_versions (
  gold_version    TEXT PRIMARY KEY,        -- 'v1', 'v2'…
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),

  -- La requête d'échantillonnage qui a produit le tirage. Sans elle, le jeu
  -- n'est pas reproductible et RE-5 est une déclaration d'intention.
  requete_sha256  TEXT,

  -- ── Le gel ───────────────────────────────────────────────────────────────
  -- NULL = en cours d'annotation. Non NULL = plus une seule écriture n'entre.
  frozen_at       TEXT,
  -- sha256 de l'instantané JSON figé, et sa clé dans `model-artifacts`.
  -- Le dépôt git ne porte que ce sha — git n'est jamais un transport de données.
  snapshot_sha256 TEXT,
  snapshot_key    TEXT,

  note            TEXT,

  CHECK (frozen_at IS NULL OR snapshot_sha256 IS NOT NULL)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS crop_gold_annotations (
  gold_version    TEXT NOT NULL
                  REFERENCES crop_gold_versions(gold_version) ON DELETE CASCADE,
  asset_id        TEXT NOT NULL
                  REFERENCES image_assets(id) ON DELETE CASCADE,

  -- La 2ᵉ passe n'écrase PAS la 1ʳᵉ : elle mesure la reproductibilité de la
  -- main, qui est le PLAFOND du banc (cf. JUGE.md). Les écraser reviendrait à
  -- détruire la seule borne qui dise ce qu'aucune méthode ne peut dépasser.
  passe           INTEGER NOT NULL DEFAULT 1 CHECK (passe >= 1),

  actor           TEXT NOT NULL,   -- `principal.user_id` : le PO et un ami ne
                                   -- cadrent pas pareil, et on veut le savoir
                                   -- AVANT d'entraîner dessus.
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT NOT NULL DEFAULT (datetime('now')),

  -- ── L'ellipse d'or, en PIXELS NATIFS du raw ──────────────────────────────
  -- Native et pas normalisée : le raw ne change pas, et une fraction obligerait
  -- à retrouver ses dimensions pour relire l'or. `theta_deg` en degrés comme
  -- `cv2.fitEllipse`, pour qu'un copier-coller depuis `measure_tilt` reste vrai.
  cx              REAL,
  cy              REAL,
  a               REAL,            -- demi-GRAND axe
  b               REAL,            -- demi-PETIT axe
  theta_deg       REAL,

  -- Un cas non annotable SORT explicitement (pièce coupée par le bord, floue,
  -- masquée). Il ne s'annote pas au jugé, et il ne se remplace pas tout seul :
  -- la réserve existe pour que le PO en annote une de plus.
  indecidable     INTEGER NOT NULL DEFAULT 0 CHECK (indecidable IN (0,1)),

  -- ── La strate, tirée puis CONFIRMÉE ──────────────────────────────────────
  -- Les strates viennent de proxys textuels (le mot « capsule » n'existe pas
  -- dans le parc) ; c'est la confirmation humaine qui les rend honnêtes.
  strate_tiree     TEXT,
  strate_confirmee TEXT,

  -- ── Le coût du geste, pour savoir quand le pré-remplissage est mauvais ───
  -- Au-delà de ~90 s/image, c'est `measure_tilt` qui propose mal sur la strate
  -- en cours. L'information est utile en elle-même.
  secondes         REAL,
  prefill_modifie  INTEGER,        -- 0 = le pré-remplissage a été accepté tel
                                   -- quel. Une NON-modification est une donnée,
                                   -- pas une absence de donnée (leçon de L1).

  editor_version   TEXT NOT NULL,

  PRIMARY KEY (gold_version, asset_id, passe),

  -- Une annotation dit quelque chose : soit une ellipse complète, soit
  -- « indécidable ». Une ligne à moitié remplie serait une annotation au jugé.
  CHECK (indecidable = 1
         OR (cx IS NOT NULL AND cy IS NOT NULL AND a IS NOT NULL
             AND b IS NOT NULL AND theta_deg IS NOT NULL)),
  -- `a` est le demi-GRAND axe. L'inversion est l'erreur classique de
  -- `cv2.fitEllipse` (qui rend (largeur, hauteur), pas (grand, petit)) ; la
  -- laisser entrer rendrait tout `d = 0,08·a` faux d'un facteur b/a.
  CHECK (a IS NULL OR (a > 0 AND b > 0 AND a >= b))
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_crop_gold_annotations_asset
  ON crop_gold_annotations(asset_id);
CREATE INDEX IF NOT EXISTS idx_crop_gold_annotations_version_passe
  ON crop_gold_annotations(gold_version, passe);
