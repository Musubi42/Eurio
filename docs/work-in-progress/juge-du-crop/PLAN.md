Plan — chantier juge-du-crop, lots L1 → L3

Contexte

Sept chantiers « crop » entre mai et août 2026 ont chacun atteint leur cible sur
leur propre oracle et produit des crops que la review humaine jette. Le cas
qui l'explique : crop-recovery avait des critères pré-enregistrés, datés et
validés PO — son seuil IoU médian ≥ 0,80 tolérait 10,6 % d'amputation du
rayon (1 − √0,80). Le chantier n'a pas été bâclé : il a mesuré rigoureusement
la mauvaise chose.

La décision est écrite (ADR-017 (../../Documents/Musubi42/bizz/EurioProject/Eurio/docs/adr/017-le-crop-d-enrichissement-est-decouple-du-scan.md))
et le chantier ouvert (docs/work-in-progress/juge-du-crop/). Il reste à
l'implémenter.

Ce plan couvre L1 → L3 et s'arrête à RE-4, la falsification du juge : on
publie sa corrélation aux verdicts humains sur 60 crops, et s'il ne sépare pas
les acceptés des rejetés, le chantier s'arrête là. C'est la seule chose qui
distingue cette tentative des sept précédentes.

Décidé avec le PO : route d'abandon incluse · ellipse après · les 2 181
recadrages reconstitués servent à la calibration seulement · feu vert global
pour migrer et déployer.

Ce que ce plan ne fait pas

- Il ne choisit aucune méthode de crop (L5, après L3).
- Il ne touche pas au scan Android — ADR-017 les découple.
- Il ne bascule pas sur le disque intérieur bimétallique (D7 : mesuré,
  autorisé, non décidé).
- Il ne réentraîne rien et ne reconstruit aucune banque d'ancres.

---

L1 — le recadrage manuel devient une mesure

Pourquoi en premier : ne bloque personne, et chaque review du PO produit une
observation dès qu'il est posé. C'est la seule brique qui devient plus précieuse
chaque jour qu'elle tourne.

L1.1 — Migration 0018_crop_edit_observations

Table crop_edit_observations (schéma complet dans
docs/work-in-progress/juge-du-crop/ — spec produite le 27/08). Colonnes :
asset_id, review_id, actor, created_at · before_{cx,cy,r} +
before_method · after_{cx,cy,r} · start_{cx,cy,r} + start_origin
(hint|suggestion|default) · suggestion_{cx,cy,r} + suggestion_reason ·
deltas dérivés d_r_ratio, d_cx_norm, d_cy_norm, d_center_norm ·
outcome (inchange|agrandi|retreci|recentre|remplace|abandonne) · touched ·
editor_version.

⚠️ Le triple mécanisme du dépôt — les trois endroits sont obligatoires :

1. ml/serving/migrations/0018_crop_edit_observations.sql — appliqué au boot
   de l'API VPS par run_migrations (ml/serving/db_migrate.py:27, appelé
   depuis ml/serving/server_serve.py:81). Pas de down-migration.
2. Miroir DDL dans ml/state/schema.sql — c'est le seul que voient les bases
   locales (rejoué à chaque ouverture d'un Store inscriptible).
3. Déclarer la migration dans ml/tests/test_schema_mirror.py — la liste
   MIROIR_ATTENDU (:44). C'est une table neuve, donc rejouable sur base
   vide : elle va dans MIROIR_ATTENDU, pas dans exclues. Sans ça,
   test_toute_migration_neuve_est_declaree_ou_exclue_sciemment (:170)
   échoue — et c'est voulu.

Pas de _ensure_column nécessaire : aucune colonne ajoutée à une table
existante, aucun index partiel de schema.sql ne la référence.

L1.2 — Le write-half

ml/store/crop_observations.py → apply_crop_observation(conn, obs) -> dict.

Calqué sur ml/store/crops.py (apply_ingest_crops) : duck-typé pydantic OU
dataclass, ni BEGIN ni COMMIT (le caller possède la transaction),
asset_id inconnu → missing, jamais de 404 global.

Stdlib + store.* uniquement. Interdits : cv2, torch, training, et
review.review_lanes — ce dernier tire training.foundation en transitif,
c'est le défaut qui a tué --reject en prod le 27/08.

Les deltas et outcome sont calculés à l'écriture, pas en vue : une vue les
recalculerait rétroactivement sur un jeu d'or déjà utilisé. Référence du delta =
start_* (ce qui était à l'écran), pas before_* — sinon on attribue à
l'humain un déplacement fait par la suggestion Hough.

L1.3 — Le payload et la route

Découverte qui simplifie : apply_manual_crop (ml/serving/crop_edit.py:311)
relit déjà a.detection_method et la géométrie avant d'écrire. Le client n'a
donc à transmettre que ce que le serveur ne peut pas savoir.

- ManualCropPayload (ml/serving/crop_edit_api.py:69) s'étend en champs
  optionnels : start_{cx,cy,r}, start_origin, suggestion_{cx,cy,r},
  suggestion_reason, touched. Optionnels ⇒ aucun appelant existant ne change
  de comportement.
- Route neuve : POST /review-queue/{review_id}/crop-edit-abandon dans
  ml/serving/review_queue/crop_routes.py, scope review:write, corps
  {start_*, start_origin, touched, last_{cx,cy,r}}. C'est elle qui produit les
  étiquettes positives (outcome='inchange').
- Direction A : l'écriture suit la garde if not resolve_db_readonly()
  existante (crop_edit.py:403) et voyage par un forward jumeau de push_crops.
  Écrire en local sous le flip donnerait readonly database — le piège n°1.

L1.4 — Le front

admin/packages/studio-local/src/features/review/components/CircleCropEditor.vue

⚠️ Il n'existe aucun chemin de fermeture unique. Quatre sites appellent
emit('close') (header :524, bouton Annuler :684, Escape :446-450,
save() :431/:437), plus un cinquième qui ne l'émet pas du tout :
SingleReviewView.resetForCurrent() (:450) fait tomber le v-if.

→ Introduire requestClose(), appelée par les quatre sites, qui émet
l'observation d'abandon avant emit('close'). Filet pour le cinquième chemin :
onBeforeUnmount (:275-280, déjà présent), gardé par un flag savedOk pour
ne pas compter deux fois après une sauvegarde.

L'appel est best-effort avec keepalive: true — perdre une observation ne
doit jamais retenir la fermeture d'une modale. fetchEurioWrite
(useReviewApi.ts:193) accepte déjà keepalive via CommitOpts.

circleTouched (:310) part tel quel dans les deux payloads. Il est déjà
correct : tous les gestes humains passent par clampCircle(), et
loadSuggestion s'y soustrait délibérément.

L1.5 — Le backfill de calibration

ml/scripts/backfill_crop_observations.py — reconstitue 2 181 des 2 913
recadrages via source_images.detections_json (que apply_manual_crop ne touche
jamais), alignés par crop_index.

Marqués editor_version='reconstitue_v0', actor='inconnu',
start_origin='hint'. Calibration seulement : fixer les seuils d'outcome
et trancher la question ouverte « le pipeline sur-crope-t-il ou sous-crope-t-il ? »
(le signal apparié dit Δrayon médian 0,976, rétréci 555 contre agrandi 253 —
en tension avec le récit « sous-crop systémique », et contaminé par une passe
batch intercalée). Exclus du jeu d'or et de tout entraînement.

Deux phases, imports lourds paresseux, --no-push — le patron de
backfill_denom.py corrigé le 27/08.

L1.6 — Tests

┌──────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────┐
│                         test                         │                    ce qu'il verrouille                     │
├──────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│                                                      │ l'applier est SQL pur (ast : aucun import lourd au niveau  │
│ ml/tests/test_crop_observations.py                   │ module) · deltas et outcome corrects aux seuils · asset_id │
│                                                      │  inconnu → missing · outcome='inchange' avec touched=1 ≠   │
│                                                      │ avec touched=0                                             │
├──────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│                                                      │ calqué sur test_face_source_provenance.py : base neuve     │
│ ml/tests/test_migration_0018.py                      │ porte la table · le .sql contient bien le CREATE TABLE et  │
│                                                      │ ses index · déclarée dans MIROIR_ATTENDU                   │
├──────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│                                                      │ patron test_ingest_dino.py : app montée à la main,         │
│ route dans test_crop_observations.py                 │ dependency_overrides[require_principal], relecture SQL     │
│                                                      │ directe, scope refusé sans review:write                    │
├──────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│                                                      │ premier test qui monte réellement CircleCropEditor (il est │
│ .../review/__tests__/crop-editor-observation.spec.ts │  stubé partout aujourd'hui) : fermeture sans geste →       │
│                                                      │ observation touched=false · geste puis fermeture →         │
│                                                      │ abandonne · sauvegarde → pas de double observation         │
└──────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────┘

Discipline non négociable : chaque garde est jouée par mutation et vue
rouge avant d'être crue. Trois de mes gardes ont survécu à leur première
mutation le 27/08.

L1.7 — Déploiement

Backend d'abord. git push github matrice-dino:repo-cleanup, puis sur le VPS
git fetch/merge --ff-only + docker compose up -d --build. La migration
s'applique au boot — vérification : docker logs eurio-api 2>&1 | grep db_migrate doit dire applying 0018_…. Puis l'OpenAPI doit porter
/review-queue/{review_id}/crop-edit-abandon. Front ensuite.

---

L2 — le jeu d'or

L2.1 — script d'export du manifeste : la requête de JEU-D-OR.md (déjà
exécutée, rend exactement 60 lignes, 15 par strate, 8 acceptés / 7 rejetés) →
manifest.json + copie des 60 raws depuis le cache local (200/200 vérifiés
présents, zéro réseau).

L2.2 — outil d'annotation jetable, ml/bench/gold_crop/annotate/ : page HTML
- SVG, 4 poignées (centre, demi-grand axe, demi-petit axe, rotation).
  measure_tilt pré-remplit l'ellipse — le PO corrige une proposition. Deux
  cases : confirmation de strate, et « indécidable » (8 images de réserve par
  strate pour remplacer sans retirer le tirage).

L2.3 — séance PO, ~40 min + 10 min de double passe sur 10 images
(reproductibilité intra-annotateur = le plafond du banc).

L2.4 — gold.json v1 sur MinIO (eurio-datasets/gold-crop/v1/). Le dépôt ne
porte que le sha256 et la requête. Git n'est jamais un transport de données.

---

L3 — le juge, et sa falsification

L3.1 — ml/bench/gold_crop/judge.py : C1 (marge ≥ 2 %·a sur 360 directions),
C2 (couverture du listel ≥ 11/12, anneau défini par E_gold et jamais par un
fitEllipse refait sur le candidat), Boundary IoU d = 0,08·a, IoU de masque et
Hausdorff en log seulement.

L3.2 — harness ml/bench/gold_crop/. Réutilisable tel quel depuis
ml/bench/crop_recovery/ : le patron de registre de iface.py, la forme du JSON
de run, hybrid.py, et iou_circles/circle_from_bbox de common.py. À
réécrire : datasets.py, harness.metrics (entièrement ad-hoc), et common.py
(tout y est câblé sur la probe gelée).

L3.3 — ⛔ RE-4, le point d'arrêt. Exécuter le juge sur baseline_prod et
publier la corrélation entre amputation_rate et le verdict humain sur les 60.
S'il ne sépare pas les 32 acceptés des 28 rejetés, le juge est faux et le
chantier s'arrête. Test de référence : quality_score y échoue à 0,0008
près (0,9200 accepté / 0,9208 rejeté-crop).

Avant L3.3, figer les seuils avec le PO (RE-1) : m = 0,02,
arc_min = 11/12, d = 0,08·a. ⚠️ d = 0,08·a suppose que le listel occupe
~8 % du rayon — non vérifié, à mesurer sur les canoniques avant de figer.

---

Vérification

┌────────────────┬─────────────────────────────────────────────────────┬───────────────────────────────────────────┐
│     étape      │                      commande                       │                  attendu                  │
├────────────────┼─────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ tests Python   │ cd ml && .venv/bin/python -m pytest tests/ -q       │ 2 542 → ~2 560, zéro échec                │
├────────────────┼─────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ miroir de      │ pytest tests/test_schema_mirror.py -q               │ vert (échoue si 0018 non déclarée)        │
│ schéma         │                                                     │                                           │
├────────────────┼─────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ mutations      │ rejouer chaque garde, une par une                   │ toutes rouges, aucun débris # MUT dans    │
│                │                                                     │ l'arbre après                             │
├────────────────┼─────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ typecheck      │ go-task front:typecheck                             │ propre                                    │
│ front          │                                                     │                                           │
├────────────────┼─────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ tests front    │ go-task front:test                                  │ 14 → ~17 passed                           │
├────────────────┼─────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ build front    │ go-task front:build                                 │ vue-tsc --noEmit && vite build            │
├────────────────┼─────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ migration en   │ ssh … 'docker logs eurio-api 2>&1 | grep            │ applying 0018_crop_edit_observations      │
│ prod           │ db_migrate'                                         │                                           │
├────────────────┼─────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ route en prod  │ curl -s $EURIO_API_URL/openapi.json | grep          │ présente (l'OpenAPI fait autorité, pas le │
│                │ crop-edit-abandon                                   │  code HTTP)                               │
├────────────────┼─────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ bout en bout   │ recadrer un crop depuis le front, puis lire la      │ une ligne, deltas cohérents, outcome      │
│                │ table sur le canonique                              │ juste                                     │
├────────────────┼─────────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ étiquette      │ ouvrir l'éditeur, refermer sans rien toucher        │ une ligne outcome='inchange', touched=0   │
│ positive       │                                                     │                                           │
└────────────────┴─────────────────────────────────────────────────────┴───────────────────────────────────────────┘

Contrôle transverse : l'API lean n'a ni cv2, ni torch, ni training. Un
import lourd au niveau module fait skipper le routeur entier, en silence.
Vérifier docker logs eurio-api 2>&1 | grep "routers skippés" — aucun skip
nouveau.

Journal

Mettre à jour docs/work-in-progress/juge-du-crop/SUIVI.md à chaque lot franchi,
et DECISIONS.md à chaque seuil figé ou desserré. Un suivi qui ment est pire
que pas de suivi.
