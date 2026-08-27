-- 0018 — `crop_edit_observations` : le recadrage manuel devient une MESURE.
--
-- Chantier `juge-du-crop` (ADR-017). Sept chantiers « crop » entre mai et août
-- 2026 ont chacun atteint leur cible sur leur PROPRE oracle et produit des
-- crops que la review humaine jette. Le mode d'échec est constant : l'oracle,
-- jamais l'algorithme. `crop-recovery` avait des critères pré-enregistrés,
-- datés et validés PO — son seuil `IoU médian >= 0,80` tolérait 10,6 %
-- d'amputation du rayon (1 - racine(0,80)). Il a mesuré rigoureusement la
-- mauvaise chose.
--
-- Le dépôt n'a AUCUNE vérité terrain sur le cadrage. Mesuré le 2026-08-27 :
--
--   · `review_queue.decision_notes` ne prend que deux valeurs — `rejected`
--     (1 157) et `other` (304). Aucune taxonomie « mal cadré / sur-crop / autre
--     pièce » ;
--   · `serving/crop_edit.py:405` fait `UPDATE image_assets SET bbox_json=?,
--     detection_method='manual'` EN PLACE : la géométrie proposée à l'humain
--     est écrasée au moment même où elle devient une étiquette ;
--   · le payload (`crop_edit_api.py`, `ManualCropPayload`) ne porte que
--     `{cx, cy, r}`. L'éditeur CONNAÎT pourtant l'avant (`ctx.hint`), la
--     suggestion Hough, et le fait que l'humain ait bougé ou non
--     (`CircleCropEditor.vue`, `circleTouched`). Les trois meurent à la
--     fermeture de la modale ;
--   · 2 913 assets portent `detection_method='manual'` (14,3 % des 20 375), et
--     AUCUN ne dit de quoi il corrigeait quoi.
--
-- Cette table n'invente PAS un oracle de plus. Elle enregistre celui qui existe
-- déjà, gratuitement, dans la main du PO : **le delta entre le crop proposé et
-- le crop final EST l'étiquette**. On ne lui demande de qualifier rien — une
-- taxonomie manuelle serait mal remplie au bout de trois jours et
-- enregistrerait son interprétation, là où la géométrie enregistre le fait.
--
-- POURQUOI UNE TABLE ET PAS DES COLONNES SUR `image_assets`
--   1. plusieurs recadrages par asset (mesuré : 5 assets ont déjà 2 events
--      `manual_recrop`) — une colonne n'en garde qu'un ;
--   2. le NON-geste est une observation. « Ouvert, regardé, rien changé » est
--      l'étiquette « ce cadrage est bon », et c'est la MOITIÉ du signal. Elle
--      ne correspond à AUCUNE mutation d'`image_assets` ;
--   3. `image_state_events.detail_json` est un blob libre : on n'y fait pas de
--      GROUP BY. Un jeu de vérité terrain qu'on ne peut pas agréger n'existe
--      pas.
--
-- ⚠️ Miroir DDL obligatoire dans `ml/state/schema.sql` (les bases locales ne
-- rejouent pas les migrations, elles bootstrappent depuis schema.sql). Pas de
-- `_ensure_column` : aucune colonne n'est ajoutée à une table existante.

CREATE TABLE IF NOT EXISTS crop_edit_observations (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,

  -- ── QUI, QUAND, SUR QUOI ────────────────────────────────────────────────
  asset_id        TEXT NOT NULL
                  REFERENCES image_assets(id) ON DELETE CASCADE,
  review_id       TEXT,          -- NULL si l'éditeur a été ouvert hors queue
                                 -- (voie `coin_assets`). Pas de FK : la review
                                 -- peut être purgée, l'observation reste vraie.
  actor           TEXT NOT NULL, -- `principal.user_id`. `crop_routes.py` le
                                 -- LOGGE déjà et le jette. Un jeu d'or annoté
                                 -- par plusieurs mains doit pouvoir se découper
                                 -- par annotateur : le PO et un ami ne cadrent
                                 -- pas pareil, et on veut le savoir AVANT
                                 -- d'entraîner dessus.
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),

  -- ── AVANT (relu par le serveur, jamais cru sur parole du client) ─────────
  -- Cercle et non bbox : c'est la forme que l'éditeur manipule et que
  -- `_crop_mask_resize_float` consomme. La bbox stockée en est dérivée ;
  -- repasser par elle ajouterait un aller-retour lossy.
  before_cx       REAL,          -- NULL si l'asset n'avait pas de bbox
  before_cy       REAL,
  before_r        REAL,
  before_method   TEXT,          -- `image_assets.detection_method` d'avant.
                                 -- LA colonne qui manque le plus aujourd'hui :
                                 -- sans elle on ne peut pas dire QUEL détecteur
                                 -- l'humain corrige. C'est la question que les
                                 -- sept chantiers posaient sans pouvoir y
                                 -- répondre.

  -- ── APRÈS ───────────────────────────────────────────────────────────────
  -- NULL quand l'humain a ouvert et n'a rien changé (cf. `outcome`). On ne
  -- recopie pas l'avant : un NULL dit « pas de geste », une copie dirait
  -- « geste identique », et ce n'est pas la même chose.
  after_cx        REAL,
  after_cy        REAL,
  after_r         REAL,

  -- ── LE POINT DE DÉPART, ET D'OÙ IL VENAIT ───────────────────────────────
  -- L'éditeur démarre TOUJOURS sur `hint` (SQL, immédiat), puis la suggestion
  -- Hough le remplace en différé SI l'humain n'a pas encore touché. Sans cette
  -- colonne, un delta mesuré depuis `before_*` serait faux dans tous les cas
  -- où la suggestion s'est appliquée : on attribuerait à l'humain un
  -- déplacement fait par le Hough.
  start_origin    TEXT NOT NULL
                  CHECK (start_origin IN ('hint', 'suggestion', 'default')),
  start_cx        REAL,          -- le cercle EFFECTIVEMENT présenté à l'écran
  start_cy        REAL,          -- au moment où l'humain a posé la main.
  start_r         REAL,          -- == before_* si start_origin='hint'.

  -- La suggestion telle que le serveur l'a rendue, MÊME non appliquée. C'est ce
  -- qui permet d'évaluer le Hough `_dominant_circle` et son filtre
  -- `_plausible_suggestion` contre la main humaine, sans relancer un calcul.
  suggestion_cx   REAL,
  suggestion_cy   REAL,
  suggestion_r    REAL,
  suggestion_reason TEXT         -- déjà produit par `_suggestion_for`,
                                 -- aujourd'hui affiché puis jeté. Savoir
                                 -- POURQUOI la suggestion ne sort pas est la
                                 -- moitié du diagnostic.
                  CHECK (suggestion_reason IS NULL OR suggestion_reason IN
                         ('lot','aucun_cercle','cercle_aberrant','erreur')),

  -- ── DELTAS DÉRIVÉS ──────────────────────────────────────────────────────
  -- Calculés À L'ÉCRITURE, pas en vue. (a) Ils doivent survivre à un changement
  -- de formule : une vue les recalculerait rétroactivement sur un jeu d'or déjà
  -- utilisé — exactement le genre de dérive muette que ce dépôt fabrique en
  -- série. (b) Un GROUP BY sur quelques milliers de lignes doit rester du SQL
  -- nu.
  --
  -- Référence = start_*, PAS before_*. Le delta est ce que L'HUMAIN a fait, pas
  -- ce qui sépare le stockage de l'écran.
  d_r_ratio       REAL,          -- after_r / start_r. Ratio et pas différence :
                                 -- un raw fait 400 ou 2 000 px selon le
                                 -- listing, une différence en px n'est pas
                                 -- comparable d'un asset à l'autre.
  d_cx_norm       REAL,          -- (after_cx - start_cx) / start_r. SIGNÉ et
  d_cy_norm       REAL,          -- séparé en x/y : un biais systématique
                                 -- (« le détecteur cadre toujours trop haut »)
                                 -- s'annulerait dans une distance euclidienne.
  d_center_norm   REAL,          -- hypot(dx,dy)/start_r — l'amplitude, pour
                                 -- trier et seuiller sans recalculer.

  -- ── L'ÉTIQUETTE ─────────────────────────────────────────────────────────
  -- Seuils calibrés sur les 2 181 paires reconstituables (cf.
  -- `scripts/backfill_crop_observations.py`) : d_r_ratio médiane 0,976,
  -- p10 0,808, p90 1,123 ; d_center_norm médiane 0,067, p90 0,277.
  --   · 10 % de rayon : au-dessus du bruit de la main et sous les p10/p90,
  --     donc l'étiquette sépare deux populations au lieu de couper au milieu
  --     d'une ;
  --   · 0,15·r de centre : au-delà du p50, en deçà du p90 ;
  --   · 'remplace' : centre > 0,7·r — le MÊME seuil que
  --     `_plausible_suggestion` utilise pour dire « ce n'est plus la même
  --     pièce ». Deux seuils pour la même notion seraient deux vérités.
  -- Ordre d'évaluation : 'remplace' > 'agrandi'/'retreci' > 'recentre' >
  -- 'inchange'.
  outcome         TEXT NOT NULL
                  CHECK (outcome IN (
                    'inchange',   -- ouvert, refermé sans toucher, OU deltas
                                  -- sous tous les seuils. C'EST UNE ÉTIQUETTE
                                  -- POSITIVE : « ce cadrage était bon ». Sans
                                  -- elle le jeu n'a que des négatifs, et un
                                  -- modèle entraîné dessus apprend que tout
                                  -- cadrage est mauvais.
                    'agrandi',    -- d_r_ratio > 1.10
                    'retreci',    -- d_r_ratio < 0.90
                    'recentre',   -- rayon stable, d_center_norm > 0.15
                    'remplace',   -- d_center_norm > 0.70 : un autre objet
                    'abandonne'   -- ouvert, bougé, fermé SANS sauvegarder. Ni
                                  -- un accord ni un désaccord : à exclure du
                                  -- jeu d'or, et à surveiller (un taux qui
                                  -- monte = un éditeur qui frustre).
                  )),
  touched         INTEGER NOT NULL DEFAULT 0
                  CHECK (touched IN (0, 1)),
                                 -- `circleTouched` brut. Distinct d'`outcome` :
                                 -- « bougé puis remis en place » (touched=1,
                                 -- 'inchange') n'est PAS « pas touché »
                                 -- (touched=0, 'inchange'). Le premier est un
                                 -- accord APRÈS examen — c'est celui que le jeu
                                 -- d'or veut ; le second peut être un clic par
                                 -- erreur.

  -- ── PROVENANCE DU LOGICIEL ──────────────────────────────────────────────
  editor_version  TEXT NOT NULL DEFAULT 'v1'
                                 -- Le jour où l'éditeur passe à l'ellipse, les
                                 -- deltas cercle et ellipse ne sont plus
                                 -- comparables : c'est une RUPTURE
                                 -- D'INSTRUMENT, pas une amélioration. Sans
                                 -- cette colonne on mélange deux instruments
                                 -- dans un même jeu d'or, et personne ne le
                                 -- voit. `reconstitue_v0` marque le backfill.
);

CREATE INDEX IF NOT EXISTS idx_crop_edit_obs_asset
  ON crop_edit_observations(asset_id, created_at);
CREATE INDEX IF NOT EXISTS idx_crop_edit_obs_outcome
  ON crop_edit_observations(outcome, before_method);
CREATE INDEX IF NOT EXISTS idx_crop_edit_obs_actor
  ON crop_edit_observations(actor, created_at);
