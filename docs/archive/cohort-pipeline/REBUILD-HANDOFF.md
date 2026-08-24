# Cockpit cohorte — HANDOFF de reconstruction

> Document de passation pour une **nouvelle session Claude Code**. Le cockpit
> `/lab/cohorts/<id>` (cohorte pilote **mix-zone-17** `b0299ca0252b`) **ne donne
> pas satisfaction au PO** : malgré beaucoup de travail (5 chantiers livrés cette
> session), le flow reste **illisible** et plusieurs comportements sont **buggés
> ou trompeurs**. Le PO veut une **reconstruction** : modèle d'état SQLite
> explicite (fini les heuristiques temps-réel), UX repensée (prendre de la place,
> expliquer le flow), et un backend qui « fait de vraies choses » et **note tout
> en base**.
>
> ⚠️ **Posture exigée par le PO** : ne pas présumer « je sais mieux ». Si le PO
> dit que ça ne marche pas, ça ne marche pas. Vérifier en base, pas au jugé.

---

## 0. PROMPT à coller pour démarrer la prochaine session

```
On reprend le cockpit cohorte d'Eurio (/lab/cohorts/b0299ca0252b), qui ne marche
toujours pas malgré la session précédente. Lis d'abord, dans l'ordre :
  - docs/cohort-pipeline/REBUILD-HANDOFF.md  (CE doc : flow, bugs, direction)
  - docs/cohort-pipeline/README.md           (carte 9 étages, journal)
  - docs/cohort-pipeline/census-detector-design.md
  - la mémoire : project_cohort_training_pipeline, project_lab_streamline,
    project_coin_census_detector, project_crop_quality_overhaul, feedback_*

NE PATCHE RIEN tant qu'on n'a pas re-cadré ensemble. Lance des workflows
d'analyse (ultracode) pour, EN PARALLÈLE :
  1. AUDIT état réel : tracer en base (ml/state/eurio.db) le cycle de vie d'une
     image d'une cohorte, lister tous les états/transitions réels, les
     incohérences entre ce qui est en base et ce qui est affiché, et reproduire
     les bugs listés au §4 (surtout be-2007 "scraper" → 0 attribué, recrop = 0).
  2. RECHERCHE comment les plateformes de data-labeling / curation de datasets
     (Label Studio, CVAT, Roboflow, Scale, etc.) modélisent un pipeline
     ingestion→annotation→QA→export et le présentent en UI (états, files,
     compteurs honnêtes, pas d'heuristique d'affichage).
  3. DESIGN d'un modèle d'état SQLite explicite par cohorte (nouvelles tables,
     PK/FK, chaque transition d'image notée avec timestamp+raison+acteur ;
     AUCUNE éval temps-réel). Ne pas casser les tables qui marchent.
  4. REDESIGN UX du cockpit avec le skill frontend-design : un flow LISIBLE,
     qui prend de la place, avec une légende/ligne-exemple expliquant chaque
     chiffre et chaque action, et le flow écrit en tête de la cohorte.

Restitue les findings + un plan, demande-moi mes arbitrages, PUIS implémente par
chunks avec audit visuel. Tous les commits de la session précédente et les bugs
sont dans REBUILD-HANDOFF.md §3-4.
```

---

## 1. La mission (rappel) & le FLOW cible (à écrire EN TÊTE de la cohorte)

Eurio entraîne un modèle de reconnaissance de pièces euro. Une **cohorte** = un
set de pièces qu'on veut savoir reconnaître. Le cockpit doit dérouler, **de façon
explicite et lisible**, tout le pipeline qui transforme une cohorte en dataset de
training. Le PO veut ce flow **écrit en haut de la page cohorte** :

1. **Sélection des pièces** de la cohorte.
2. **Capture device** : génère un CSV → poussé sur le téléphone → on photographie
   les **vraies pièces** physiques. Ces captures = **hold-out / benchmark** une
   fois le modèle entraîné (JAMAIS dans le train). Cf. [[cohort_capture_flow]].
3. **Scrape eBay** (par groupe de découverte) = source d'**images de training**.
4. **Download** des images des annonces.
5. **Crop automatique** (détection de la pièce dans la photo). Les crops
   **ratés/douteux** partent en **review**.
6. **Theme matcher** : attribue chaque crop à un `eurio_id` (année, wording du
   titre, visuel).
7. **Tri en lanes** : **auto-accept** (machine sûre) / **ccproxy** (arbitrage
   Claude vision) / **manuel** (humain).
8. **Validation** (par n'importe quel chemin) → l'image devient
   **training-eligible**.
9. **Enrichissement** : augmentation ×facteur pour atteindre **≥ 100 images /
   classe**.
10. **Run d'entraînement** ArcFace, benchmarké contre les captures device.

---

## 2. Direction technique voulue par le PO (NON négociable)

- **Modèle d'état EXPLICITE en base, fini les heuristiques temps-réel.** Chaque
  image a un cycle de vie ; **chaque transition d'état est écrite en base**
  (état, timestamp, raison, acteur), pas recalculée à l'affichage. Aujourd'hui
  trop de compteurs sont des `COUNT(...)` avec des `CASE`/`route_decision`
  recalculés → incohérents et trompeurs.
- **Nouvelles tables si besoin**, avec **primary keys + foreign keys** bien
  câblées. **Ne PAS toucher** les tables existantes qui fonctionnent (coins,
  source_images, image_assets cœur…) — créer des tables d'**état/événements** à
  côté plutôt que muter l'existant.
- **Le backend doit faire de vraies choses** : si un job tourne (scrape, recrop),
  ça doit être **observable** (progression réelle) et **persistée**, pas un
  thread opaque en mémoire.
- **UX** : prendre de la place, expliquer le flow, une **légende / ligne-exemple**.
  Le flow est long et conséquent — s'il est tassé, on n'y comprend rien.

---

## 3. Ce qui a été fait la session précédente (commits) + état RÉEL

Branche `sources-jo-wikipedia`. Commits (du plus récent au plus ancien) :

| Commit | Sujet | État réel constaté |
|---|---|---|
| `ac717e0` | review scopée par pièce + compteur = file vivante | Filtre `eurio_id` OK en API ; **non validé par le PO en UI** |
| `7f23719` | doc journal | — |
| `66b44ea` | mini-bench ccproxy + downscale images (WS5) | ccproxy fonctionne (89% acc sur 30 crops, suggestion→ack) ; downscale OK |
| `7f2dfa8` | funnel cockpit : enrichissement dynamique, rescue sœurs, recrop diagnostiqué | Formule ≥100 OK en base ; **recrop UI buggé** ; **boutons illisibles** |
| `20d2cdc` | lanes de review PERSISTÉES (manuel/auto/ccproxy) | Colonnes + backfill OK en base ; **les 3 cartes §C4 ne satisfont toujours pas** |

**Ce qui marche (vérifié en base) :**
- Les décisions de review **persistent** (`image_assets.training_eligible`,
  `eurio_id`, `review_queue.status='done'`). georg-henrik est passé de 3 → 10
  crops `training_eligible=1` durant la session.
- La **lane** est persistée (`review_queue.lane` + `lane_source`), backfillée
  (manual 469 / auto 158 / ccproxy 2018), et `triage-stats.by_lane` compte la
  colonne.
- La **formule d'enrichissement** est dynamique (`ceil(100/seed)`) et partagée
  affichage↔bake (`ml/foundation/enrichment.py`).

**Ce qui NE marche PAS / reste trompeur (= l'essentiel pour le PO) → voir §4.**

> Lecture honnête : la session a **empilé des correctifs** (lanes, scoping,
> compteurs) sur un modèle **heuristique + temps-réel** et une UX **tassée**. Le
> PO ne veut plus de patchs : il veut le **modèle d'état** et l'**UX** repensés.

---

## 4. BUGS & incohérences confirmés (à reproduire et corriger)

### B1 — « Scraper » sur un standard n'attribue RIEN à la pièce ciblée *(grave)*
Clic « Scraper » sur `be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait`.
Le run `8a29b6185bbf411991fc10190abb4012` **réussit** (32 raws, 68 crops) mais
attribue les annonces à **be-2014 (40), NULL (29), be-1999 (11), be-2025,
be-2024… 33 autres pièces BE — et 0 à be-2007**. Résultat UI : be-2007 reste
**« JAMAIS SCRAPÉ / aucun listing scrapé »** alors qu'un run vient de le toucher.
→ Le scrape d'un **standard** résout un groupe « BE 2€ » trop large et le theme
matcher disperse sur toutes les pièces BE ; la pièce visée ne reçoit rien. **Le
flow standard est cassé** + l'UI ment (« jamais scrapé »). Vérif :
`SELECT target_eurio_id, COUNT(*) FROM source_images WHERE run_id='8a29b…' GROUP BY 1`.

### B2 — Recrop : 0 feedback + 0 résultat
Clic « Recropper 164 » sur georg-henrik. Le job tourne en **thread mémoire
opaque** : aucune progression affichée, le bouton ne change pas, la page
re-propose « Recropper » après refresh. Et **0 crop récupéré** (`run_id LIKE
'recrop-zero%'` = 0 ligne) — inexpliqué (census recrop récupère normalement une
bonne partie ; ici 0, peut-être CPU-affamé par un scrape parallèle, ou gate qui
rejette tout, ou job mort silencieux). À investiguer ET à rendre **observable +
persisté** (pas un thread mémoire).

### B3 — `§C4 Review crops` : les 3 cartes (manuel/auto/ccproxy) ne satisfont pas
« Queue manuelle » bloquée sur **3** (avant 6). Le compteur = bucket Dino
`unknown` persistée en lane `manual` ; le PO le vit comme « bloqué, à chier ».
La sémantique des lanes n'est pas claire pour lui en usage réel.

### B4 — Compteurs/boutons de la liste illisibles & incohérents
- `50 listings → 200 crops → 58 review · 193 pending → 251 DL` : **personne ne
  sait ce que ça veut dire**. `DL` doit s'écrire **« download »**. `pending`
  n'est pas clair (« c'est quoi ? ça attend d'être review ? alors pourquoi un
  état pending distinct ? »).
- Boutons qui **se mélangent** selon l'état : `Reviewer 11` quand il y a des
  singles, juste `129 lots` sinon → **pas propre**.
- `Recropper` vs `crops` (lien bench) : **différence pas claire**. `filtres` /
  `crops` / `Recropper` / `Rescraper` / `Reviewer` cohabitent sans hiérarchie.
- Le **badge run-live** s'affiche **en haut** du tableau, pas dans la ligne de la
  pièce concernée → incohérent.

### B5 — Pas de légende / pas d'explication du flow
Le PO demande une **ligne-exemple** annotée : « ça = un eurio_id ; ça = total
trouvé sur eBay ; ça = ce que l'autocrop a résolu ; ça = en review ; etc. » et le
**flow écrit en tête**.

---

## 5. Pistes pour le modèle d'état (à concevoir, pas imposé)

Idée directrice : une **machine à états par image** persistée. Esquisse (à
challenger dans le workflow DESIGN) :

```
scraped → downloaded → crop_pending → cropped{ok|failed}
        → matched{eurio_id, confidence} → routed{lane}
        → reviewed{accepted|rejected|reattributed} → training_eligible → augmented
```

- Table d'**événements** (append-only) : `image_state_events(id, image_asset_id
  FK, from_state, to_state, reason, actor, run_id FK, created_at)` → l'historique
  complet, auditable, source des compteurs (plus de recompute heuristique).
- Table de **jobs** observable : `cohort_jobs(id, cohort_id FK, eurio_id, kind
  {scrape|recrop|...}, status, n_total, n_done, n_produced, started_at,
  finished_at, error)` → la progression du scrape/recrop est en BASE, pas en
  mémoire (corrige B2).
- Les compteurs du cockpit = `SELECT` sur l'**état courant** (vue matérialisée
  ou colonne d'état), pas un mélange `route_decision` + `review_queue.status` +
  Dino verdict recalculé.
- Le problème **B1 (standards)** relève du theme-matcher/attribution : à traiter
  séparément (un scrape « pour be-2007 » doit soit attribuer à be-2007, soit dire
  honnêtement « 0 trouvé pour cette pièce, N pour ses sœurs » — pas « jamais
  scrapé »).

⚠️ Garde-fous : **ne pas casser** `coins`, `source_images`, `image_assets`,
`review_queue` (le cœur scrape/crop/review marche). Ajouter des tables d'état/
événements/jobs **à côté**, avec FK propres. Migrations idempotentes via le
pattern `store._bootstrap()` / pré-bootstrap (cf. ce qui a été fait pour
`review_queue.lane`).

---

## 6. UX — ce que le PO veut

- **Le flow écrit en tête de la cohorte** (les 10 étapes du §1, version courte).
- **Une ligne-exemple annotée** qui explique chaque chiffre et chaque bouton.
- **Prendre de la place** : le flow est long ; ne pas tasser. Hiérarchiser les
  actions (1 action primaire claire par pièce selon l'état, pas 5 boutons à
  égalité).
- **Vocabulaire explicite** : « download » pas « DL » ; expliquer ou supprimer
  « pending » ; distinguer clairement « recropper » (re-détecter sur images déjà
  téléchargées) de « crops » (voir la qualité au bench) de « rescraper »
  (chercher de nouvelles annonces).
- **Cohérence des actions** : même grammaire de boutons quel que soit l'état.
- **Jobs visibles** : scrape/recrop affichent leur progression dans la ligne de
  la pièce, pas un badge global en haut.
- Utiliser le skill **frontend-design** pour un rendu clair et pas tassé.

---

## 7. À explorer (workflows de la prochaine session)

1. **Audit état réel** : cycle de vie d'une image en base, états vs affichage,
   reproduire B1–B4.
2. **Benchmark produits** : comment Label Studio / CVAT / Roboflow / Scale
   modélisent ingestion→annotation→QA→export et l'exposent (états, files,
   compteurs honnêtes).
3. **Design modèle d'état SQLite** (tables événements/jobs, PK/FK, zéro
   heuristique d'affichage).
4. **Redesign UX** (frontend-design) : flow lisible, légende, ligne-exemple,
   hiérarchie d'actions, jobs observables.
5. **Theme-matcher standards** (B1) : attribution correcte ou honnête pour les
   pièces standard.

---

## 8. Pointeurs techniques (fichiers de la session précédente)

- Backend funnel : `ml/serving/lab_routes.py` (`_cohort_funnel_status`, `_coin_tail`).
- Review/lanes : `ml/review/review_queue_routes.py`, `ml/foundation/review_lanes.py`.
- Enrichissement : `ml/foundation/enrichment.py`, `ml/training/iteration_augmentations.py`.
- Recrop : `ml/scan/recrop_zero.py`, endpoint `POST …/coins/{eurio_id}/recrop-zero`
  (thread mémoire `_recrop_jobs` dans `lab_routes.py` — à remplacer par une table jobs).
- Lanes backfill : `ml/scripts/backfill_review_lanes.py`.
- ccproxy bench : `ml/scripts/ccproxy_minibench.py`, `ml/foundation/claude_review.py`,
  `ml/ccproxy_client.py` (downscale).
- Front cockpit : `admin/packages/web/src/features/lab/components/CohortDrawerEbay.vue`
  (§C3 sourcing/funnel), `CohortDrawerCrop.vue` (§C4 les 3 cartes), types
  `admin/.../lab/types.ts`, review `admin/.../review/`.
- Migration lanes (modèle de pré-bootstrap idempotent) : `ml/state/store.py`,
  `ml/state/schema.sql`.

**Backup DB avant la session** : `ml/state/eurio.db.bak-pre-lanes` existe. En
refaire un avant toute migration de la prochaine session.
