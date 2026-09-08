-- 0020 — Le TIRAGE du jeu d'or rejoint l'or dans le canonique.
--
-- Chantier `juge-du-crop`, décision D12. 0019 a fait entrer les ANNOTATIONS
-- dans `eurio.db` ; le tirage — les 60 + 24 images à annoter, leur strate, leur
-- rang, le cercle de production et le pré-remplissage — restait dans
-- `ml/state/gold_crop/v1/manifest.json`, sur le disque du Mac. Une séance
-- d'annotation ne pouvait donc se tenir que là, avec un serveur Python jetable.
--
-- **Les quatre raisons de D11 s'appliquent mot pour mot au tirage** :
--
--   1. `eurio.db` est capturée par CONSTRUCTION (`VACUUM INTO`). Un fichier de
--      `ml/state/` ne l'est pas — et `git clean -xdf` l'emporte sans un mot ;
--   2. le tirage doit se JOINDRE à `image_assets` / `source_images` pour rendre
--      un `raw_url` servable. Un manifeste JSON ne se joint pas ;
--   3. le front HÉBERGÉ doit afficher la séance — donc il faut une route, donc
--      il faut du SQL. C'est tout l'objet de D12 : annoter depuis
--      `eurio-admin.musubi.dev`, pas depuis un `localhost` jetable ;
--   4. `crop_gold_annotations` porte déjà la même nature de donnée, à la même
--      maille `(gold_version, asset_id)`. Deux rangements pour une même nature,
--      c'est la dette que R0 interdit.
--
-- **`verdict` n'est délibérément PAS stocké ici.** Le manifeste local le porte
-- (`accept` / `reject`), et c'est précisément ce qu'il ne faut pas donner à
-- l'annotateur : le jeu d'or sert à mesurer si le juge sépare les acceptés des
-- rejetés (RE-4). Un annotateur qui voit le verdict humain avant de tracer
-- l'ellipse le confirme au lieu de l'ignorer, et la mesure ne prouve plus rien.
-- Le verdict reste JOIGNABLE depuis `image_assets` pour le banc, qui lui n'est
-- pas influençable — il n'a simplement pas sa place dans ce que la route sert.
--
-- Le pré-remplissage vient de `measure_tilt` (cv2), calculé sur la machine du
-- ML et POUSSÉ ici : l'API lean du VPS n'importe pas cv2 et ne le calculera
-- jamais. D'où des colonnes, et pas une route qui recalcule.

CREATE TABLE IF NOT EXISTS crop_gold_tirage (
  gold_version    TEXT NOT NULL
                  REFERENCES crop_gold_versions(gold_version) ON DELETE CASCADE,
  asset_id        TEXT NOT NULL
                  REFERENCES image_assets(id) ON DELETE CASCADE,

  -- 'tirage' = les 15 par strate qu'on annote ; 'reserve' = celles qui
  -- remplacent un « indécidable » SANS retirer une image du tirage. Le rôle
  -- doit être en base : le tirer au sort deux fois ne donnerait pas le même
  -- jeu, et RE-5 exige que le jeu soit reproductible.
  role            TEXT NOT NULL CHECK (role IN ('tirage','reserve')),

  -- Rang dans la strate, tel que rendu par la requête d'échantillonnage. Il
  -- fixe l'ORDRE de la séance : deux annotateurs voient la même suite.
  rn              INTEGER,

  -- La strate TIRÉE (proxy textuel). La strate CONFIRMÉE par l'humain vit dans
  -- `crop_gold_annotations` — les deux ne se mélangent pas, c'est l'écart entre
  -- elles qui dit ce que valent les proxys.
  strate_tiree    TEXT NOT NULL,

  -- Dimensions du RAW, en pixels natifs — la même unité que l'ellipse d'or de
  -- 0019. Servies avec le tirage pour que le front pose son SVG sans un second
  -- aller-retour.
  width           INTEGER,
  height          INTEGER,

  -- ── Le cercle de PRODUCTION (`hint`) ────────────────────────────────────
  -- Ce que le pipeline a effectivement cadré. C'est le candidat que le juge
  -- doit départager : sans lui, le jeu d'or ne mesure rien. NOT NULL parce
  -- qu'une image sans cercle de production n'a rien à faire dans le tirage.
  hint_cx         REAL NOT NULL,
  hint_cy         REAL NOT NULL,
  hint_r          REAL NOT NULL,

  -- ── Le PRÉ-REMPLISSAGE (`measure_tilt`, cv2) ────────────────────────────
  -- L'ellipse proposée à l'annotateur, qu'il corrige. Nullable EN GROUPE :
  -- soit `measure_tilt` a rendu une ellipse, soit il a échoué et l'annotateur
  -- part du cercle de production. Une ellipse à moitié remplie serait une
  -- proposition au jugé — le même raisonnement qu'en 0019.
  prefill_cx      REAL,
  prefill_cy      REAL,
  prefill_a       REAL,            -- demi-GRAND axe
  prefill_b       REAL,            -- demi-PETIT axe
  prefill_theta_deg REAL,

  -- Pourquoi la proposition n'est pas fiable (`too_circular:0.983`,
  -- `no_contour`…). Gardée MÊME quand l'ellipse est présente : elle dit à
  -- l'annotateur de se méfier, et elle dit au banc sur quelles strates
  -- `measure_tilt` propose mal.
  prefill_reason  TEXT,

  created_at      TEXT NOT NULL DEFAULT (datetime('now')),

  PRIMARY KEY (gold_version, asset_id),

  -- Tout ou rien : cf. le commentaire du groupe ci-dessus.
  CHECK ((prefill_cx IS NULL AND prefill_cy IS NULL AND prefill_a IS NULL
          AND prefill_b IS NULL AND prefill_theta_deg IS NULL)
         OR (prefill_cx IS NOT NULL AND prefill_cy IS NOT NULL
             AND prefill_a IS NOT NULL AND prefill_b IS NOT NULL
             AND prefill_theta_deg IS NOT NULL)),
  -- `prefill_a` est le demi-GRAND axe. `cv2.fitEllipse` rend (largeur,
  -- hauteur), PAS (grand, petit) : c'est le piège d'inversion de 0019, et le
  -- pré-remplissage vient précisément de là. Le laisser entrer inversé
  -- donnerait à l'annotateur une ellipse tournée de 90°.
  CHECK (prefill_a IS NULL OR (prefill_a > 0 AND prefill_b > 0
                               AND prefill_a >= prefill_b)),
  CHECK (hint_r > 0)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_crop_gold_tirage_asset
  ON crop_gold_tirage(asset_id);
CREATE INDEX IF NOT EXISTS idx_crop_gold_tirage_version_role
  ON crop_gold_tirage(gold_version, role);
