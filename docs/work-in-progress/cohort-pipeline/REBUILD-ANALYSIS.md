# Cockpit cohorte — ANALYSE de reconstruction (2026-06-06)

> Sortie brute du workflow d'analyse `cockpit-rebuild-analysis` (ultracode) : 4 audits base (Sonnet) + 4 recherches data-labeling (Sonnet) + design modele d'etat (Opus) + redesign UX (Opus). Lecture seule, aucune mutation. Source des bugs : [REBUILD-HANDOFF.md](./REBUILD-HANDOFF.md) §4. La synthese + le plan + les arbitrages sont restitues au PO en chat ; ce doc = le materiau complet, durable.


## Sommaire

- AUDIT A1-lifecycle — AUDIT 1/4 — Machine à états de fait des images de cohorte (mix-zone-17)
- AUDIT A2-standards-B1 — Bug B1 — Cause racine : "Scraper" sur be-2007 attribue 0 à la pièce cible
- AUDIT A3-recrop-B2 — B2 — Audit recrop-zero : causes racines "0 crop" + opacité observabilité
- AUDIT A4-counters-B34 — Audit B3+B4 — Honnêteté de chaque compteur du cockpit cohorte mix-zone-17
- RECHERCHE R1-label-studio — Label Studio — modèle d'état & UX pipeline : leçons pour le cockpit cohorte Eurio
- RECHERCHE R2-cvat — CVAT — Machine d'états, QA loop et analytics : transpositions pour notre cockpit
- RECHERCHE R3-roboflow — Roboflow — modèle de curation dataset : idées fortes & transpositions cockpit
- RECHERCHE R4-scale-supervisely — Patterns UI data labeling (Scale/Supervisely + Label Studio/CVAT/Roboflow) — Transpositions cockpit Eurio
- DESIGN — Modèle d'état SQLite explicite par cohorte — DDL, machine à états, compteurs, migration
- UX — Redesign UX du cockpit cohorte /lab/cohorts/&lt;id&gt; — proposition pour arbitrage

---


# [AUDIT A1-lifecycle] AUDIT 1/4 — Machine à états de fait des images de cohorte (mix-zone-17)

**Resume.** Trois tables forment le backbone de l'état d'une image : source_images (pré-crop), image_assets (post-crop), review_queue (post-enqueue). La pipeline officielle enchaîne 9 steps (discover→persist→text_signal→download→detect→resolve→auto_validate→enqueue→price_aggregate). Deux paths alternatifs (recrop_zero / runs échoués) créent des image_assets en pending_match SANS jamais appeler resolve() ni enqueue(), laissant 544 assets invisibles à la review UI. Le route_decision de source_images est figé à l'étape enqueue et n'est JAMAIS mis à jour après une décision de review — il est donc une trace historique d'intention, pas un état courant. Cinq états ghost ou phantom sont identifiés : auto_name (enum présent, jamais écrit), pending_crop (enum présent, jamais écrit), cropped dans discovery_log (jamais atteint pour BCE/JO), route_decision frozen post-review (207 source_images), et manual+training_eligible=0 (39 assets exclus par la bench UI sans retirer le label manual).


**Takeaways**

- T1 CRITIQUE — recrop_zero.py doit appeler run_resolve() puis run_enqueue() (ou leur équivalent inline) après avoir créé les crops. Les 487 assets pending_match de census-recover-b0299ca0252b sont invisibles à la review et doivent être backfillés (resolve + enqueue) pour débloquer le pipeline.
- T2 DESIGN — route_decision est une trace historique d'intention, pas un état courant. Le cockpit doit cesser d'afficher n_review_single/n_review_lot comme 'reste à faire' et s'appuyer exclusivement sur n_open_review_single/n_open_review_lot (depuis rq.status='open'). Alternativement : ajouter un UPDATE route_decision dans decide_review/run_auto_accept.
- T3 — Les runs failed en mid-pipeline (ex : 63f5c8bc, 57 assets) laissent des pending_match orphelins. Un outil de backfill 'orphan-resolve' (detect toutes image_assets en pending_match sans review_queue, appelle resolve+enqueue) couvrirait T1 et T3 en une passe.
- T4 — Le skip_review laisse status='open' (jamais 'skipped' contrairement au CHECK). C'est intentionnel mais le compteur n_pending est gonflé. Documenter explicitement que 'skipped' comme status n'est pas utilisé, ou effectivement écrire status='skipped' pour que les compteurs soient honnêtes.
- T5+T6 — discovery_log.pipeline_state='downloaded' couvre 3 populations radicalement différentes : (a) images jamais cropées, (b) images cropées lors d'un re-run idempotent, (c) sources BCE/JO dont la pipeline ne passe jamais par detect_crop. Cet état est inutilisable comme indicateur de progression. Le rebuild du cockpit (SQLite explicite) devrait ignorer discovery_log.pipeline_state et lire directement source_images.crop_status.
- ENUM GHOSTS à supprimer du schéma ou à documenter explicitement : auto_name (jamais écrit, path commenté), pending_crop (jamais écrit), status='skipped' dans review_queue CHECK (jamais écrit comme status, confusion avec decision_notes='skipped').
- manual + training_eligible=0 (39 assets, ~20 en cohort) : la bench UI peut exclure un crop validé sans changer son resolution_status. La training pipeline filtre training_eligible=1 donc ce cas est safe pour l'entraînement, mais le cockpit qui compte les 'validés' par resolution_status='manual' surcompte. Ajouter training_eligible=1 comme condition dans les compteurs de 'crops validés' du cockpit.


## (a) Diagramme texte de la machine à états de fait

### Layer 1 : source_images (grain = listing/photo)

```
                        ┌─────────────────────────────────────────────────────────┐
                        │              SOURCE_IMAGES state machine                 │
                        │                                                          │
                        │  download_status  ×  crop_status  ×  route_decision    │
                        └─────────────────────────────────────────────────────────┘

[PERSIST step]
  → download_status = NULL, crop_status = NULL, route_decision = "pending"

[TEXT_SIGNAL step]     ──────────────────────────────────────→ route_decision = "rejected_text"
                       (si verdict contradict ; skips download)

[DOWNLOAD step]
  NULL  →  "success"  (storage_path set, storage_status=present)
  NULL  →  "failed"   (download_error set)
  NULL  →  "skipped"  (COALESCE, ne remplace pas valeur existante)
  !! Si route_decision='rejected_text', le download est sauté (crop_status reste NULL)

[DETECT_CROP step]
  → crop_status = "success"    (1..N crops créés)
  → crop_status = "zero_crops" (0 crop détecté — pas une erreur)
  → crop_status = "error"      (exception normalize / MinIO unreachable)
  NB : si source_image a déjà des image_assets → COALESCE(crop_status,'success'), skip réel

[ENQUEUE step]
  Lit les resolution_status des image_assets pour décider route_decision :
  → "review_single"  (au moins un needs_review, kind=single)
  → "review_lot"     (au moins un needs_review, kind=lot)
  → "auto_resolved"  (tous auto_phash / auto_name / manual / rejected)
  → "pending"        (no_crops_yet — source_image sans aucun asset)
  → "rejected"       (tous crops rejected)

  ⚠ FROZEN FOREVER après l'enqueue : aucune mutation post-review
    → 207 source_images en "review_single/review_lot" alors que tous leurs assets
      sont en rq.status='done' (état mensonger pour le cockpit)

States effectifs cohort (N=2663) :
  download_status = success : 2600 (97.6%)
               NULL : 59  (cas JO/BCE ou non encore traités)
             pending : 4   (fantôme — probablement stale)
  crop_status = zero_crops : 1598 (60%)
                  success : 989  (37%)
                     NULL : 76   (jamais cropé)
  route_decision = pending : 1907 (71%)
              review_single : 380
               review_lot  : 297
                     NULL  : 62
            rejected_text   : 16
            auto_resolved   : 1
```

### Layer 2 : image_assets (grain = crop détecté)

```
                    ┌──────────────────────────────────────────────────┐
                    │          IMAGE_ASSETS resolution_status           │
                    └──────────────────────────────────────────────────┘

[DETECT_CROP step — upsert_image_asset()]
  → "pending_match"  (crop sans match phash)
  → "auto_phash"     (phash Hamming ≤4 trouve un eurio_id existant)

[RESOLVE step — run_resolve()]
  "pending_match" → "needs_review"
  "auto_phash"    → (skip, terminal)
  "manual"        → (skip, terminal)
  "rejected"      → (skip, terminal)
  NOTE : "auto_name" est dans _TERMINAL_STATUSES mais jamais écrit (path commenté)

[REVIEW décision (admin / auto_dino / ccproxy)]
  "needs_review" → "manual"   (decide_review, run_auto_accept, ccproxy)
  "needs_review" → "rejected" (reject_review)
  "rejected"     → "needs_review" (restore endpoint — remet en queue manuelle)

[BENCH exclusion (bench_routes.py:1367)]
  "manual" → resolution_status INCHANGÉ, training_eligible=0
  (quality_reason='too_tilted' — pas de changement de status)

States effectifs cohort :
  needs_review : 1178
  pending_match : 506  ← DONT 481 sans review_queue (stuck forever)
  manual        : 130
  rejected      :  63
  auto_phash    :  12

training_eligible :
  0 : 1795 (95%)
  1 :   94 (5%)
```

### Layer 3 : review_queue (grain = 1 asset dans la file)

```
                    ┌──────────────────────────────────────────────────┐
                    │          REVIEW_QUEUE status × lane               │
                    └──────────────────────────────────────────────────┘

[ENQUEUE step — run_enqueue()]
  → INSERT (status='open', lane=compute_lane(dino_verdict))
  UNIQUE(image_asset_id) → idempotent re-run

Lane routing (review_lanes.py) :
  Dino verdict auto_candidate → lane "auto_accept"
  Dino verdict partial/divergent → lane "ccproxy"
  Dino verdict unknown → lane "manual"

[AUTO_VALIDATE step — post-enqueue re-route]
  → UPDATE review_queue SET lane=? WHERE lane_source='auto' AND status='open'
  (si Dino recalculé change d'avis → re-route vers bonne lane)

[Décisions (decide_review / run_auto_accept / ccproxy)]
  "open" → "done"   (+ image_assets mis à jour atomiquement)

[skip_review]
  "open" → rq.decision_notes='skipped' (status RESTE 'open' !)
  NB : "skipped" COUNT dans la query /triage-stats avec rq.status='open' !!
       → le compteur n_manual gonfle artificiellement

[move_lane]
  "open" → lane='manual', lane_source='human' (sticky)

States effectifs cohort :
  auto_accept open:47  done:52  skipped:14
  ccproxy     open:1109 done:138 skipped:1
  manual      open:7   done:3
```

### Layer 4 : discovery_log (grain = source_ref unique)

```
Pipeline officielle :
  discovered → persisted → downloaded → cropped → resolved

Transitions réelles :
  discovered  (INSERT OR IGNORE — store.py:896)
  persisted   (persist step — ml/sources/_base/steps/persist.py:89)
  downloaded  (download step + bce/jo custom pipeline)
  cropped     (detect_crop step, SEULEMENT si crops_for_image > 0)
  resolved    (resolve step, si au moins 1 image_asset)
  rejected    (discard step — dedup.py:563)

Gaps :
  - BCE/JO : bloqués à "downloaded" pour toujours (pas de detect_crop,
    canonical_promote ne fait pas avancer pipeline_state)
  - Idempotence detect_crop : si source_image déjà cropée → COALESCE crop_status
    mais PAS set_discovery_pipeline_state → reste à "downloaded"
  - recrop_zero : ne touche pas discovery_log du tout

States réels global :
  downloaded : 4894 (42%)  ← inclut BCE/JO + idempotence stale
  resolved   : 2543
  rejected   : 1968
  persisted  :  683
  discovered :  383
  cropped    :   20 (uniquement détections nouvelles, first run)
```

---

## (b) Tableau exhaustif champ × enum × écrit par × lu par × incoherence

| Table | Champ | Valeurs réelles (counts globaux) | Écrit par (fichier:fonction) | Lu/recalculé à l'affichage | Persisté | Incoherence |
|---|---|---|---|---|---|---|
| source_images | download_status | success:4779 / NULL:239 / pending:4 | `steps/download.py:run_download` (success/failed/skipped), `sources/jo/pipeline.py`, `sources/bce/pipeline.py` | `lab_routes.py:_coin_tail` (COUNT WHERE success/failed) | OUI | 4 rows 'pending' probablement stale (run jamais terminé) |
| source_images | crop_status | zero_crops:2575 / success:1657 / NULL:790 | `steps/detect_crop.py:run_detect_crop` (success/zero_crops/error), `scan/recrop_zero.py:recrop_zero_for_coin` (success) | `lab_routes.py:_coin_tail` (n_zero_crops = EXISTS check sur image_assets) | OUI | 295 rows: crop_status='success' + route_decision='pending' (recrop_zero n'appelle pas enqueue) |
| source_images | route_decision | pending:2953 / review_single:753 / NULL:613 / review_lot:581 / rejected_text:118 / auto_resolved:3 / rejected:1 | `steps/enqueue.py:run_enqueue`, `steps/text_signal.py:run_text_signal_extract`, `scripts/backfill_listing_kind_routing.py`, `api/sources_routes.py` (rescue) | `lab_routes.py:_coin_tail._roll()` (n_review_single/lot/pending/auto) | OUI (figé) | **FROZEN POST-REVIEW** : 207 source_images en review_single/lot dont tous les assets sont rq.status='done'. Jamais remis à 'auto_resolved' après review. |
| source_images | route_reason | single_unmatched/no_crops_yet/multi_coin_photo/is_lot_suspected/listing_kind_lot/all_crops_rejected/year/manual/auto_phash_match/rescued_from_discard:X | `steps/enqueue.py:_route_decision_for_source_image`, `steps/text_signal.py` | `bench_routes.py` (nodes funnel) | OUI | Même freeze que route_decision |
| source_images | storage_status | present:5022 (100%) | `steps/download.py` (implicite via storage_path SET) | — | OUI | Aucune incoherence — jamais 'missing' ni 'removed' |
| image_assets | resolution_status | needs_review:2496 / pending_match:544 / manual:145 / rejected:70 / auto_phash:15 | `steps/detect_crop.py` (pending_match/auto_phash), `steps/resolve.py:run_resolve` (needs_review), `api/review_queue_routes.py:decide_review` (manual), `api/review_queue_routes.py:reject_review` (rejected), `api/review_queue_routes.py:restore_rejected` (needs_review), `api/coin_assets_routes.py` (needs_review) | `api/review_queue_routes.py:triage-stats` (by_lane counts) | OUI | **GHOST** : `auto_name` dans CHECK mais jamais écrit (0 rows). `pending_crop` dans CHECK mais jamais écrit (0 rows). 544 pending_match SANS review_queue entry (invisibles à la review UI). 39 manual+training_eligible=0 (exclus bench mais label manual intact). |
| image_assets | training_eligible | 0:3161 / 1:109 | `api/review_queue_routes.py:decide_review` (1), `api/review_queue_routes.py:run_auto_accept` (1), `api/review_queue_routes.py:reject_review` (0), `api/bench_routes.py:crops_exclude` (0), `sources/_base/dedup.py:upsert_image_asset` (défaut 0) | `lab_routes.py:_cohort_funnel_status` (n_training_eligible) | OUI | 39 rows: resolution_status='manual' + training_eligible=0 (exclus bench — cohérent pour la training pipeline qui filtre training_eligible=1, mais trompeur si on lit resolution_status) |
| image_assets | eurio_id | NULL (majority) + valeurs eurio_id | `steps/detect_crop.py` (auto_phash path), `api/review_queue_routes.py:decide_review` et variants | — | OUI | Aucune |
| review_queue | status | open:2483 / done:215 / skipped:15 | `steps/enqueue.py:run_enqueue` (open), `api/review_queue_routes.py:decide_review` (done), `api/review_queue_routes.py:skip_review` (reste open ! decision_notes='skipped') | `triage-stats` (n_pending = COUNT WHERE status='open') | OUI | **GHOST STATUS** : "skipped" n'existe pas en colonne status — les items skippés restent status='open'. Ils sont comptés dans n_pending et dans by_lane.manual. Le CHECK() a 'skipped' comme valeur valide mais la colonne n'est jamais mise à 'skipped'. |
| review_queue | lane | ccproxy:2032 / manual:515 / auto_accept:166 | `steps/enqueue.py:run_enqueue` (via `compute_lane`), `steps/auto_validate.py:run_auto_validate_dino` (re-route), `api/review_queue_routes.py:move_lane` (sticky human), `run_auto_accept` (demote→manual) | `triage-stats` (by_lane counts) | OUI (figé ou sticky) | Aucune incoherence structurelle |
| review_queue | lane_source | auto:2713 (100%) | `steps/enqueue.py` (défaut 'auto'), `api/review_queue_routes.py:move_lane` ('human') | Filtre dans queries (AND lane_source='auto' pour re-route) | OUI | Toutes les rows ont lane_source='auto' → aucun override humain sticky dans la cohorte |
| discovery_log | pipeline_state | downloaded:4894 / resolved:2543 / rejected:1968 / persisted:683 / discovered:383 / cropped:20 | `steps/persist.py` (persisted), `steps/download.py` (downloaded), `steps/detect_crop.py` (cropped, SEULEMENT si crops>0), `steps/resolve.py` (resolved), `sources/bce/pipeline.py` (downloaded), `sources/jo/pipeline.py` (downloaded), `sources/_base/dedup.py:mark_discarded` (rejected) | — | OUI | **GHOST STATE** : 4894 'downloaded' dont ~499+428 sont des BCE/JO qui n'iront jamais à 'cropped'/'resolved'. L'état 'cropped' est skip pour les re-runs idempotents (detect_crop ne re-set pas quand skip). |

---

## (c) Transitions notées NULLE PART (perdues)

### T1 — recrop_zero ne clôture pas la pipeline

**Fichier** : `ml/scan/recrop_zero.py:recrop_zero_for_coin()`

- Écrit : `image_assets` (upsert, status=pending_match/auto_phash) + `source_images.crop_status='success'`
- **N'appelle PAS** : `run_resolve()` → image_assets reste en `pending_match` (au lieu de `needs_review`)
- **N'appelle PAS** : `run_enqueue()` → aucune review_queue entry créée
- **N'appelle PAS** : `set_discovery_pipeline_state('cropped'/'resolved')`

Résultat : **499 assets** (cohort mix-zone-17) sont en `pending_match` sans review_queue. Ils sont **invisibles à toutes les vues review** et **non comptés** dans `by_lane` du cockpit. La seule façon de les voir : requêtes directes en DB.

### T2 — route_decision jamais mis à jour post-review

**Aucun fichier** ne fait `UPDATE source_images SET route_decision=... WHERE ...` après une décision review.

- `decide_review` : met à jour `image_assets` + `review_queue` seulement
- `run_auto_accept` : idem
- Résultat : **207 source_images** (cohort) avec `route_decision IN ('review_single','review_lot')` dont tous les crops sont `rq.status='done'`. Le champ `n_review_single` dans `_coin_tail()` ment — il compte l'intention passée, pas le backlog actuel.

Le cockpit le gère en exposant à la fois `n_review_single` (figé) et `n_open_review_single` (depuis rq.status='open'). Mais la **distinction n'est pas documentée** et les deux sont retournés dans le même dict — confusion garantie.

### T3 — run échoué en mid-pipeline laisse des assets orphelins

**Fichier** : `ml/sources/_base/orchestrator.py`

Si un run échoue après `detect_crop` mais avant `resolve` :
- `image_assets` créés en `pending_match`
- `run_resolve` jamais appelé → `needs_review` jamais posé
- `run_enqueue` jamais appelé → pas de review_queue
- Run reste `status='failed'`, `current_step='detect'`

**57 assets** du run `63f5c8bc` (failed à detect) sont dans cet état. Un re-run en mode idempotent **sauterait** les crops existants (garde COALESCE) et ne recréerait pas de review_queue — la transition est perdue définitivement sauf backfill manuel.

### T4 — skip_review ne change pas status → état fantôme

**Fichier** : `ml/api/review_queue_routes.py:skip_review` (ligne ~2387)

Le skip pose `decision_notes='skipped'` mais laisse `status='open'`. Les 15 items globalement skippés (14 auto_accept + 1 ccproxy dans la cohorte) :
- Restent dans `n_pending` (compteur cockpit)
- Restent dans `by_lane.auto_accept` / `by_lane.ccproxy`
- Restent dans le feed de review (seront présentés à nouveau)

C'est intentionnel selon le commentaire ("report informationnel") mais le CHECK() du schéma autorise 'skipped' comme status valide → l'état n'est jamais utilisé comme prévu.

### T5 — discovery_log 'cropped' never reached for idempotent re-runs

**Fichier** : `ml/sources/_base/steps/detect_crop.py:run_detect_crop` (ligne 153)

Quand une source_image a déjà des image_assets (`existing_count > 0`) :
- `crop_status = COALESCE(crop_status, 'success')` — écrit
- `set_discovery_pipeline_state('cropped')` — **NON appelé**

Résultat : 281 source_images (run 059dc..., succès) restent à `pipeline_state='downloaded'` dans discovery_log même si leurs crops existent. L'état 'cropped' n'est posé que lors du **premier crop ever** — les re-runs le ratent.

### T6 — BCE/JO bloqués à 'downloaded' dans discovery_log

BCE/JO n'utilisent pas `detect_crop` mais `canonical_promote`. Ils n'appellent jamais `set_discovery_pipeline_state('cropped')` ni `('resolved')`. Les 475+71 items BCE/JO restent à `downloaded` pour l'éternité.

---

## Résumé chiffré des assets invisibles (cohort mix-zone-17)

| Catégorie | N | Statut DB | Visible review UI? |
|---|---|---|---|
| pending_match sans review_queue (recrop_zero) | 487 | pending_match, no rq | ❌ |
| pending_match sans review_queue (run failed) | 12 | auto_phash (de census-recover, auto OK) | n/a |
| auto_phash sans review_queue (normal) | 12 | auto_phash, no rq | n/a (normal) |
| manual + training_eligible=0 | ~20 (cohort) | manual, te=0 | visible review, invisible training |
| source_images route_decision figé post-review | 207 | review_single/lot (stale) | cockpit trompe sur n_review |



---


# [AUDIT A2-standards-B1] Bug B1 — Cause racine : "Scraper" sur be-2007 attribue 0 à la pièce cible

**Resume.** Le clic "Scraper" sur be-2007-2eur-standard lancé le run 8a29b6185bbf411991fc10190abb4012, qui a exécuté une recherche eBay large sur le groupe "(2.0 EUR, BE, année=null, kind=standard)". Ce groupe couvre les 5 ères de design belges, pas uniquement be-2007. L'attribution se fait par appartenance de plage d'années (eras_for_year), et le résultat est donc structurellement dépendant des millésimes trouvés par eBay — qui ce jour-là n'a renvoyé aucun listing avec 2007 dans le titre. Zéro listing ne peut donc être attribué à be-2007. L'UI affiche "jamais scrapé" car _coin_tail compte COUNT(*) WHERE source='ebay' AND target_eurio_id='be-2007...' = 0, et cette requête ne regarde que target_eurio_id, jamais ce qui est entré dans le run.


**Takeaways**

- CAUSE RACINE : be-2007 couvre uniquement year_from=2007, year_to=2007 (plage d'un an). Les 250 listings BE retournés par eBay (top-125 par mkt) ne contenaient aucun millésime 2007 — pas un bug d'algorithme, une sous-représentation statistique d'une ère courte dans les résultats paginés.
- CHEMIN DE CODE ATTRIBUTION : adapter.py:_resolve_group(→ group year=None) → discover() → _attribute_standard_row() → standards.py:attribute_standard_listing() → eras_for_year() → année absente dans eBay results → target_eurio_id reste NULL ou va aux ères longues (1999, 2009, 2014).
- REQUETE UI 'jamais scrape' : lab_routes.py:1317-1326, COUNT(*) FROM source_images WHERE source='ebay' AND target_eurio_id='be-2007-...' = 0. C'est factuellement vrai mais trompeur : le run a bien cherché le groupe BE, juste be-2007 n'a reçu aucune attribution.
- OPTION LA MOINS RISQUEE (A) : corriger l'affichage UI pour distinguer 'groupe scrapé N fois' vs 'pièce attribuée M fois'. Ajouter group_run_count (COUNT runs ayant produit des source_images pour une ère du même groupe BE). Aucun changement pipeline requis.
- OPTION COMPLEMENTAIRE (D) : rappeler que les 29 listings NULL target_eurio_id sont en review candidats=[5 ères BE] — le reviewer peut manuellement assigner be-2007. Ces listings sont déjà dans la file review_queue, rien à coder.
- POINT HONNETE : be-2007 (Albert II, 2ème carte, 1er type, 1er portrait) a été frappée de 1999 à 2007 mais les listings eBay pour 2007 spécifiquement sont rares dans le top-125. Même une recherche plus large pourrait ne pas résoudre le problème — la pièce est simplement moins listée sur eBay avec le millésime 2007 explicite.


## Étape 1 — Résolution du périmètre eBay pour un standard

**Fichier clé : `ml/sources/cohort_scope.py` (lignes 110–118) + `ml/sources/ebay/adapter.py` (`_resolve_group`, lignes 419–448)**

Quand le front envoie `POST /sources/ebay/runs` avec `target_eurio_id = "be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait"`, l'adapter résout le groupe via `_resolve_group` :

```python
# adapter.py:439-444
return DiscoveryGroup(
    denomination=coin.face_value,   # 2.0
    country=coin.country,           # "BE"
    year=None,                      # ← standard : JAMAIS d'année dans le groupe
    kind="standard",
)
```

Le groupe résolu est donc `(denom=2.0, country=BE, year=None)` — **identique** pour toutes les 5 ères belges. C'est confirmé par les `discovery_searches` :

```sql
-- query_filters_json extrait des 2 lignes discovery_searches du run
{"group": {"denomination": 2.0, "country": "BE", "year": null}, "kind": "standard"}
```

**La recherche eBay ("2 euro Belgien", "2 euro Bélgica") est donc une recherche large sur tout le BE, couvrant les 5 ères (1999, 2007, 2008, 2009, 2014) — et aussi toutes les commémos BE.**

Ce comportement est délibéré et documenté dans `cohort_scope.py:1–16` : "Une seule recherche large couvre toutes les ères du pays, attribuées en aval par appartenance de plage d'années."

---

## Étape 2 — Attribution : comment target_eurio_id est posé sur chaque annonce

**Fichier clé : `ml/sources/ebay/standards.py:201–273` (`attribute_standard_listing`) + `adapter.py:511–531` (`_attribute_standard_row`)**

Le funnel d'attribution pour chaque listing retenu :

1. **Garde contradiction pays/dénom** → discard si axe pays ou dénom contredit
2. **Mot-clé commémo** (Gedenkmünze/conmemorativo/commémorative) → discard si trouvé sans mot-clé standard
3. **Millésime unique requis** : si 0 ou ≥2 années dans le titre → `ambiguous` (target_eurio_id=**None**, candidates=toutes les ères)
4. **Exclusion commémo par theme-match** : si le millésime trouve une commémo → discard
5. **`eras_for_year`** (lignes 161–172) : prend le max des `year_from ≤ year_listing` parmi les ères → retourne l'ère dont le `year_from` est le plus élevé ≤ au millésime

**Plages calculées pour BE 2EUR standard :**

| eurio_id | year_from | year_to (calculé) |
|---|---|---|
| be-1999 | 1999 | 2006 |
| be-2007 | 2007 | **2007** (next era = 2008, donc 2008-1=2007) |
| be-2008 | 2008 | 2008 |
| be-2009 | 2009 | 2013 |
| be-2014 | 2014 | 9999 |

Un listing avec "2007" dans le titre devrait correctement être attribué à be-2007. **Mais aucun listing 2007 n'a été retourné par eBay dans ce run** (vérifié : 0 entrée avec "2007" dans title dans `source_images` ET `discarded_listings` pour ce run).

**Résultat observé :**
- be-2014 reçoit 40 images (listings 2015–2025, plage ouverte → toujours l'ère la plus récente)
- be-2009 reçoit 9 images (listings 2009–2013)
- be-2007 reçoit **0 images** (eBay n'a pas retourné de listing avec millésime 2007 dans les 125 premiers résultats par mkt)
- 29 images ont `target_eurio_id=NULL` (listings yearless/multi-années → `ambiguous`)

La cause n'est pas un bug d'algorithme : `eras_for_year` calculerait correctement `be-2007` pour un listing millésimé 2007. **La cause est l'absence de ces listings dans la réponse eBay** (pièce banale, peu recherchée, écrasée par les commémos et les millésimes récents dans les 125 premiers résultats).

---

## Étape 3 — Pourquoi l'UI dit "jamais scrapé"

**Fichiers : `ml/api/lab_routes.py:1314–1335` (`_coin_tail`) + `1585` + `admin/packages/web/src/features/lab/components/CohortDrawerEbay.vue:292–295`**

La requête backend exacte qui détermine `never_scraped` :

```python
# lab_routes.py:1317-1326
breakdown = conn.execute("""
    SELECT route_decision, route_reason, COUNT(*) AS n
      FROM source_images
     WHERE source='ebay' AND target_eurio_id=?
     GROUP BY route_decision, route_reason
""", (eurio_id,)).fetchall()
# ...
n_source_images = sum(r["n"] for r in breakdown)
# lab_routes.py:1585
never_scraped = tail["n_source_images"] == 0
```

Cette requête filtre sur `target_eurio_id='be-2007-...'` — **exactement 0 ligne dans toute la base**. L'UI affiche donc "jamais scrapé" alors que le run a bien tourné et a produit 198 `source_images`, mais aucune n'est attribuée à be-2007.

Le badge Vue :
```html
<!-- CohortDrawerEbay.vue:292-295 -->
<span v-if="c.never_scraped" class="coin__badge coin__badge--danger"
  title="Jamais scrapé — 0 listing eBay pour cette pièce">
  jamais scrapé
</span>
```

---

## Étape 4 — Le run eBay : paramètres de départ

```
source_runs.id = '8a29b6185bbf411991fc10190abb4012'
filters_json = {
  "target_eurio_id": "be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait",
  "discovery_group": null,          ← résolu dynamiquement dans _resolve_group
  ...
}
→ groupe résolu = (2.0, BE, year=None, standard)
→ 2 searches : EBAY_DE 125 raw/77 kept + EBAY_ES 125 raw/52 kept
→ 30 discards (commemo_keyword:8, text_contradict_year:19, group_contradict_denomination:1, rescued:2)
→ 198 source_images créées, 0 pour be-2007
```

---

## Cause racine synthétique

**be-2007 n'a reçu aucune image car l'ère be-2007 ne couvre qu'une seule année de millésime (year_from=2007, year_to=2007).** Sur 250 listings BE retournés par eBay (125+125, avec dédup cross-mkt → 198 kept), aucun n'avait "2007" comme seul millésime dans son titre. Les listings millésimés 2007 sont probablement présents sur eBay mais n'apparaissent pas dans les 125 premiers résultats par mkt car ils sont noyés par les commémos et les standards récents (2014+).

Ce n'est pas un bug d'attribution : l'algorithme fonctionnerait correctement si eBay renvoyait un listing "2 euro Belgien 2007". C'est un problème de **couverture de la recherche large** : la be-2007 est une ère d'un an, statistiquement sous-représentée dans les top-125 d'eBay par rapport aux ères longues (1999–2006, 2009–2013, 2014–∞).

---

## Options de correction (sans recommandation)

### Option A — Ne pas changer l'algorithme, corriger l'affichage UI

**Ce que ça fait :** Distinguer "0 attribué à cette pièce" de "aucun run n'a jamais cherché ce groupe".

`never_scraped` serait remplacé par deux métriques :
- `group_run_count = COUNT(DISTINCT run_id) FROM source_images WHERE target_eurio_id IN (ères du même groupe BE)`
- `coin_attributed = tail["n_source_images"]`

L'UI afficherait "0 attribué (groupe scrapé N fois)" au lieu de "jamais scrapé". **Honnêteté maximale** : expose exactement ce qui s'est passé.

**Implication :** Aucun changement pipeline. L'info reste correcte — be-2007 n'a vraiment reçu aucun listing — mais le contexte (le run a tourné) est visible. Le badge "jamais scrapé" ne s'affiche plus faussement pour une pièce dont le groupe a été cherché.

### Option B — Augmenter la limite de search pour les standards

**Ce que ça fait :** Passer `search_limit` de 125 à 250 (ou plus) pour les groupes standards avec N ères élevé. Plus de résultats → plus de chances de voir des millésimes minoritaires.

**Implication :** Double le coût Browse API par run standard. La be-2007 resterait sous-représentée si les vendeurs 2007 se retrouvent réellement dans les résultats 125–250. Aucune garantie.

### Option C — Recherche ciblée complémentaire ("année exacte" injected)

**Ce que ça fait :** Pour une pièce standard ciblée spécifiquement (comme ici via `target_eurio_id`), faire une deuxième search `"2 euro Belgien 2007"` en plus de la search large. Les standards à ère 1 an méritent un boost.

**Implication :** Casse la doctrine "1 search par groupe" (D-14). Ajoute de la complexité. Les résultats 2007 peuvent être noyés par les commémos 2007 (thème Louis Braille etc.) que le filtre `attribute_standard_listing` devrait exclure via theme-match, mais cela ajoute des calls API. À hybrider avec Option A.

### Option D — Exposer les listings "ambiguous" (target=NULL) comme appartenant au groupe

**Ce que ça fait :** Les 29 listings à `target_eurio_id=NULL` + `route_reason='no_crops_yet'` appartiennent au groupe BE standard (ils ont passé `accept_listing`). Certains d'entre eux pourraient être des be-2007 (yearless listings, "Belgien Kursmünze Jahr nach Wahl").

En review humaine, le reviewer voit ces listings avec les candidats = 5 ères BE. Si le reviewer assigne be-2007, `ia.eurio_id` = be-2007 → comptabilisé dans `n_training_eligible`.

**Implication :** Rien à coder (c'est déjà le flux review manuel existant). `never_scraped` reste affiché, mais les listings ambiguous peuvent être revus et assignés à be-2007 à la main. Limitation : ne résout pas l'affichage UI trompeur.



---


# [AUDIT A3-recrop-B2] B2 — Audit recrop-zero : causes racines "0 crop" + opacité observabilité

**Resume.** Le bug B2 ("Recropper N → 0 crop, bouton figé") a deux causes distinctes. Cause A (0 crop produit) : les 1 599 raws encore à zero-crop sont structurellement épuisés — le script CLI census-recover v2 les a DÉJÀ tous tentés au même τ=0.55 que l'endpoint et obtenu 0 pour chacun d'eux. L'endpoint ne crashe pas, il produit un résultat parfaitement correct (0) mais invisible et non distinguable d'un vrai crash. Cause B (opacité) : l'état du job vit uniquement dans un dict Python en mémoire (_recrop_jobs), perdu à chaque restart serveur, sans timestamp, sans compteur de progression, et non consommé par le front — le front ne poll pas /recrop-zero/status mais /funnel-status, qui reste inchangé quand 0 crop est produit. L'UX résultante est un bouton qui re-propose indéfiniment le même résultat impossible.


**Takeaways**

- A.1 — Les 1 599 raws zero-crop sont ÉPUISÉS : census-recover v2 (τ=0.55) les a tous tentés. Relancer l'endpoint produit structurellement 0 crop. Action utile : baisser τ à 0.40-0.45 (τ=0.45 avait récupéré 733 crops) — mais nécessite décision PO car plus de fragments passent le gate.
- A.2 — Ajouter un marquage 'recrop_attempted_at' (timestamp) dans source_images ou cohort_jobs lors d'un run à 0 crops, pour que le cockpit puisse distinguer 'jamais tenté' de 'tenté et épuisé' et griser le bouton.
- A.3 — Le commentaire doc (τ par défaut 0.45) dans recrop_cohort_census.py:11 est OBSOLÈTE depuis probe v2 (τ=0.55) — à corriger dans le docstring.
- B.1 — Créer la table cohort_jobs (DDL fourni ci-dessus) avec au minimum : id, kind, eurio_id, cohort_id, status, n_total, n_done, n_produced, tau, started_at, finished_at, note. L'endpoint recrop_zero_coin doit insérer une ligne au départ et l'updater à la fin (ou périodiquement pour n_done).
- B.2 — Le front doit poll /recrop-zero/status (ou cohort_jobs) pour afficher l'état réel du job (spinner tant que running, '0 crop — épuisé' quand done+crops=0). Aujourd'hui le polling de funnel-status est insuffisant car il reste inchangé à 0 crops.
- B.3 — Decision à trancher : faut-il griser définitivement le bouton 'Recropper N' pour les raws déjà épuisés à τ actuel, ou exposer un bouton 'Recropper (force τ=0.45)' pour laisser passer plus de crops au coût d'une review plus lourde ?


## A) Cause racine "0 crop" — Épuisement structurel des candidats

### 1. Chronologie des runs census-recover

| Version | Script | τ | Raws tentés | Crops produits | Raws restants |
|---|---|---|---|---|---|
| v1 (≤ 2026-06-05) | `scripts/recrop_cohort_census.py --tau 0.45` | 0.45 | 1 899 | 733 | — |
| **v2 (actuel)** | `scripts/recrop_cohort_census.py` (probe v2) | **0.55** | **1 899** | **499** (run_id `census-recover-b0299ca0252b`) | **1 599** |

Source : `docs/cohort-pipeline/census-detector-design.md §9` + `SELECT COUNT(*) FROM image_assets WHERE run_id='census-recover-b0299ca0252b'` → 499.

Les 1 599 raws restants sont ceux que **census-recover v2 a déjà essayés à τ=0.55 et trouvés vides** (photos de lot scellé, emballage, certificat, fond uni…). Ils ne contiennent pas de pièce détectable au niveau de confidence du gate.

### 2. L'endpoint utilise exactement le même τ=0.55

`ml/scan/normalize_snap.py:499` :
```python
return float(os.environ.get("EURIO_CENSUS_FRAGMENT_TAU", "0.55"))
```

`ml/scan/recrop_zero.py:86` :
```python
results = [res for res in normalize_listing(bgr, census=True) if res.image is not None]
```

Le paramètre `census=True` est passé explicitement → `normalize_listing` appelle `_census_fragment_tau()` qui renvoie 0.55 (aucune variable d'env définie dans le contexte FastAPI). L'endpoint tourne au même τ que le CLI v2.

### 3. Vérification base

Scope de `recrop_zero_for_coin` (SQL ligne 61-72 de `recrop_zero.py`) = raws eBay avec `storage_path IS NOT NULL` ET `(SELECT COUNT(*) FROM image_assets WHERE source_image_id=si.id AND storage_status='present') = 0` :

```sql
SELECT COUNT(*) FROM source_images si
WHERE si.source='ebay'
  AND si.target_eurio_id IN (<cohort_eurio_ids>)
  AND si.storage_path IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM image_assets ia
                  WHERE ia.source_image_id=si.id AND ia.storage_status='present');
```
→ **1 599 raws** (identique au résidu v2). La commande `cockpit n_zero_crops` en SQL de `lab_routes.py:1369` compte la même chose avec `download_status='success'` en plus → **1 598** (différence d'1 raw avec `crop_status=NULL` pour `at-2002`).

Distribution par pièce :

| Pièce | Raws zero-crop |
|---|---|
| fi-2017-2eur-100-years-of-independence | 196 |
| fr-2008-2eur-french-presidency | 187 |
| es-2016-2eur-old-town-of-segovia | 178 |
| fr-2016-2eur-mitterrand | 177 |
| be-2011-2eur-womens-day | 172 |
| fi-2016-2eur-georg-henrik | 164 |
| de-2020-2eur-german-polish | 146 |
| at-2005-2eur-austrian-state-treaty | 145 |
| … (6 autres) | |
| **TOTAL** | **1 599** |

14 des 16 pièces de la cohorte affichent encore `n_zero_crops > 0` → bouton "Recropper N" visible sur 14 lignes, toutes infructueuses.

### 4. Ce que recrop_zero.py ne fait PAS quand il trouve 0 résultats

`recrop_zero.py:86-89` :
```python
results = [res for res in normalize_listing(bgr, census=True) if res.image is not None]
if not results:
    continue  # ← PAS d'UPDATE source_images, crop_status reste 'zero_crops'
```

Contrairement à `detect_crop.py:178-188` qui écrit `crop_status='zero_crops'` + `crop_error`, `recrop_zero` **ne laisse aucune trace en base quand un raw produit 0 crops**. Il est donc impossible de distinguer "recrop n'a pas encore tourné" de "recrop a tourné et trouvé 0" en lisant la DB.

### 5. Résumé cause A

Le bouton "Recropper N" propose une action qui **ne peut pas fonctionner** car les raws candidats ont déjà été épuisés par le CLI v2 au même algorithme (τ=0.55, census=True, YOLO@0.10 + nms_concentric + gate DINO). Ce n'est pas un crash ni un bug de code — c'est une absence de marquage "tenté-et-épuisé" dans la DB.

---

## B) Cause racine "0 observabilité" — Thread in-memory + pas de polling côté front

### 1. Architecture actuelle de _recrop_jobs

`ml/api/lab_routes.py:1730` :
```python
_recrop_jobs: dict[str, dict] = {}   # keyed by eurio_id, in-process only
_recrop_jobs_lock = threading.Lock()
```

Structure d'un job :
```python
# Au lancement (ligne 1770)
{"status": "running", "run_id": "recrop-zero-<eurio_id>"}

# Au succès (ligne 1779)
{"status": "done", "run_id": "...", "scanned": N, "recovered": N, "crops": N, "auto_phash": N}

# En échec (ligne 1784)
{"status": "failed", "run_id": "...", "error": str(exc)}
```

**Manques structurels** :

| Donnée absente | Impact |
|---|---|
| `started_at` / `finished_at` | Impossible de savoir depuis combien de temps le job tourne |
| `n_total` (nombre de raws à scanner) | Pas de barre de progression |
| `n_done` (raws traités en temps réel) | Pas de feedback pendant le run |
| Persistance DB | Perdu à chaque restart FastAPI (thread `daemon=True`) |
| `cohort_id` | Pas de contexte cohorte pour les requêtes |
| Trace "0 crops — raison" | Si 0 crops produits, impossible de diagnostiquer (gate? pas de pièce?) |

### 2. Le front ne poll pas /recrop-zero/status

`admin/packages/web/src/features/lab/composables/useLabApi.ts:223` : `triggerRecropZeroCoin` est le seul appel à l'endpoint recrop-zero. L'endpoint `GET /recrop-zero/status` (lab_routes.py:1796) **n'est jamais appelé par le front**.

Le front poll uniquement `/funnel-status` (toutes les 4 s via `refetchInterval: 4000` quand `pollWhileBusy`). Si le job produit 0 crops : `funnel-status` est inchangé → `n_zero_crops` identique → bouton ré-affiche "Recropper N" comme si le job n'avait jamais tourné.

### 3. Cycle d'échec UX actuel

```
Clic "Recropper 29"
  → POST /recrop-zero  →  202 {"status":"started"}
  → recroppingCoin=null (finally)  →  bouton re-enabled
  → job background: scanne 29 raws à τ=0.55  →  0 crops (même résultat que v2)
  → _recrop_jobs[eurio_id] = {"status":"done", crops:0}  (invisible depuis front)
  → funnel-status inchangé
  → bouton affiche toujours "Recropper 29"
  → Restart serveur  →  _recrop_jobs = {}
  → /recrop-zero/status → "idle"
  → bouton re-propose identiquement
```

### 4. Specs minimales d'une table cohort_jobs

```sql
CREATE TABLE cohort_jobs (
  id           TEXT PRIMARY KEY,         -- uuid hex
  kind         TEXT NOT NULL             -- 'recrop_zero' | 'census_recover' | ...
                CHECK (kind IN ('recrop_zero','census_recover')),
  cohort_id    TEXT REFERENCES experiment_cohorts(id),
  eurio_id     TEXT,                     -- NULL si job cohorte entière
  run_id       TEXT,                     -- lien avec image_assets.run_id
  status       TEXT NOT NULL DEFAULT 'running'
               CHECK (status IN ('running','done','failed','skipped')),
  n_total      INTEGER,                  -- raws dans le scope au lancement
  n_done       INTEGER NOT NULL DEFAULT 0,  -- raws traités (mis à jour en temps réel)
  n_produced   INTEGER NOT NULL DEFAULT 0,  -- crops créés
  tau          REAL,                     -- τ utilisé (pour diagnostiquer pourquoi 0)
  started_at   TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at  TEXT,
  error        TEXT,                     -- stacktrace si failed
  note         TEXT                      -- ex: "exhausted at tau=0.55, 0 crops possible"
);
```

**Clés de conception** :
- `n_done` mis à jour à chaque raw traité (UPDATE en autocommit) → polling progress réel
- `note` permettrait d'écrire `"0 crops — tous raws déjà épuisés à τ=0.55"` au lieu du silence actuel
- `tau` trace quelle sévérité de gate a été utilisée → aide à distinguer "gate trop strict" de "vraie absence de pièce"
- `n_total` calculé au début du job → barre de progression = `n_done / n_total`
- Persistance → survit aux restarts, bouton peut afficher `done (0 crops)` au lieu de `idle`

---

## Tableau de synthèse

| Axe | Cause | Preuve base/code |
|---|---|---|
| **A — 0 crop** | census-recover v2 (τ=0.55) a déjà épuisé les 1 599 raws restants | `SELECT COUNT(*) FROM image_assets WHERE run_id='census-recover-b0299ca0252b'` → 499 ; 1899-300=1599 résidu documenté §9 |
| **A — même τ** | Endpoint utilise τ=0.55 (env var default `normalize_snap.py:499`) = même que le CLI v2 | `os.environ.get("EURIO_CENSUS_FRAGMENT_TAU", "0.55")` |
| **A — pas de trace** | `recrop_zero.py:88` fait `continue` silencieusement quand 0 résultats, pas d'UPDATE | `recrop_zero.py:86-89` |
| **B — in-memory** | `_recrop_jobs` dict Python, `daemon=True` thread, perdu au restart | `lab_routes.py:1730, 1791` |
| **B — front aveugle** | `triggerRecropZeroCoin` = seul appel, `/status` jamais pollé, front poll `funnel-status` inchangé | `useLabApi.ts:223`, `lab_routes.py:1796` |
| **B — bouton zombie** | 0 crops → funnel-status inchangé → `n_zero_crops` identique → bouton ré-affiché pour toujours | `lab_routes.py:1369-1381` + `CohortDrawerEbay.vue:65` |



---


# [AUDIT A4-counters-B34] Audit B3+B4 — Honnêteté de chaque compteur du cockpit cohorte mix-zone-17

**Resume.** Chaque chiffre du cockpit a été tracé jusqu'à sa requête SQL exacte et comparé aux données réelles de la DB. Le cockpit contient 6 compteurs mensongers ou insuffisamment étiquetés, répartis entre le ruban C3 et les 4 cartes C4. Le pire problème est le « en review » du ruban (677) qui compte l'intention de routage gelée au moment du scrape (route_decision='review_single/lot') alors que la vraie file ouverte est 1 163 crops. Le « pending » du ruban (1 907) représente des listings non encore téléchargés/routés — pas une file d'attente review — mais son libellé suggère l'inverse. Les cartes C4 manual/auto/ccproxy n'affichent que les singles (kind='single'), les lots en lane manuelle (4) disparaissent dans la carte « Lots » sans signalisation, et le chiffre « manuel = 3 » est exact mais sa définition exclut silencieusement 4 lots manuels. La phrase funnel par pièce affiche « N review » figé alors que l'action « Reviewer N » utilise correctement la file vivante — incohérence interne. Le label « DL » est positionné après « review/pending » dans la phrase, induisant en erreur sur l'ordre pipeline (download est avant crop, pas après review).


**Takeaways**

- P0 — Ruban C3 « en review » : remplacer totals.review = sum(n_review_single + n_review_lot) par sum(n_open_review_single + n_open_review_lot). La valeur gelée (677) est fausse dès qu'une décision est prise ; la valeur vivante est 1 163 (197 singles + 966 lots). Même fix pour la phrase funnel par pièce.
- P0 — Phrase funnel par pièce : `c.n_review_single + c.n_review_lot` (route_decision figé, CohortDrawerEbay.vue ligne 331) doit devenir `c.n_open_review_single + c.n_open_review_lot`. Pour fi-2016 la phrase affiche '58 review' alors que 27 singles sont déjà done et 0 reste ouvert.
- P1 — Renommer le 'pending' du ruban (1 907) en 'non routés' ou 'à router' : ce chiffre compte les source_images avec route_decision='pending' (listings pas encore téléchargés/routés), pas une file de review. Le terme 'pending' en C4 signifie la chose opposée (crops en attente de review).
- P1 — Carte IV Lots (966) : agrège toutes lanes sans distinction. Ajouter la décomposition par lane (manuel=4, auto_accept=42, ccproxy=920) pour que le PO sache quels lots nécessitent action humaine vs traitement auto.
- P2 — Carte I 'Queue manuelle = 3' est exact MAIS exclut silencieusement 4 lots en lane=manual (captés dans la carte IV). Mentionner '+ N lots' dans la carte manuelle ou fusionner les 7 items.
- P2 — Label 'DL' : positionné APRÈS review et pending avec une flèche →, mais download précède crop dans le pipeline. Déplacer avant 'crops extraits' ou supprimer quand n_downloaded == n_source_images (information nulle).
- P3 — Bouton 'N lots' par pièce route vers /review/manual?mode=lot&cohort=X sans scope eurio_id, le reviewer voit tous les lots de la cohort. Ajouter &eurio_id=Y pour scoper (comme le bouton Reviewer qui le fait déjà).
- Decision à trancher : unifier la définition de 'pending' dans l'UI — soit toujours 'en attente de review' (→ supprimer le ruban pending ou renommer), soit documenter clairement les deux niveaux pipeline (routing-pending vs review-pending) avec des libellés distincts.


## Données de référence — cohorte mix-zone-17 (`b0299ca0252b`, 16 pièces)

```
source_images total          : 2 651
image_assets (crops) total   : 1 889
download_status='success'    : 2 588   (63 non téléchargés : null/pending route_decision)
route_decision breakdown:
  pending                    : 1 907   (listings non encore routés/téléchargés)
  review_single              :   380   (intention au moment du scrape, GELÉE)
  review_lot                 :   297   (intention, GELÉE)
  NULL (non routés)          :    50
  rejected_text              :    16
  auto_resolved              :     1

review_queue (cohort-scopée):
  single open                :   197   (par lane: manual=3, auto_accept=5, ccproxy=189)
  lot open                   :   966   (par lane: manual=4, auto_accept=42, ccproxy=920)
  single done                :   183 + 52 auto + 138 ccproxy + 3 manual = 376
  status='skipped' (global)  :    15 lot + 14 auto_accept = distinct de decision_notes='skipped'

image_assets.resolution_status (dans review_queue, cohort):
  needs_review               : 1 178
  manual                     :   130   (décidé humain)
  rejected                   :    63   (récupérables)
```

---

## Tableau central d'audit

| Libellé UI | Emplacement | Signification réelle | Requête / champ source | Honnête ou Heuristique | Problème / incohérence |
|---|---|---|---|---|---|
| **listings retenus** (ruban C3) | `totals.listings` = `sum(c.n_source_images)` | Lignes dans `source_images` où `source='ebay' AND target_eurio_id IN cohort` — listings **attribués** après theme-match | `SELECT COUNT(*) FROM source_images WHERE source='ebay' AND target_eurio_id=?` par pièce | **Honnête** | Libellé correct. `be-2007` et `es-1999` = 0 car jamais scrapés (badge « jamais scrapé » présent) |
| **crops extraits** (ruban C3) | `totals.crops` = `sum(c.n_crops)` | `image_assets` liés à ces source_images (`JOIN source_images`) | `SELECT COUNT(*) FROM image_assets ia JOIN source_images si...` | **Honnête** | Valeur réelle : 1 889. OK |
| **en review** (ruban C3, grand chiffre bleu) | `totals.review` = `sum(c.n_review_single + c.n_review_lot)` | Count de `source_images` avec `route_decision IN ('review_single','review_lot')` — **intention gelée au moment du scrape** | Champ `n_review_single` + `n_review_lot` de `_coin_tail` = GROUP BY `route_decision` sur `source_images` | **HEURISTIQUE / MENSONGER** | **B4 principal.** Valeur affichée : **677** (380+297). File ouverte réelle : **1 163** (197 single + 966 lot). Après review, le `route_decision` ne se met PAS à jour — les 27 singles de fi-2016 déjà traités comptent encore comme « en review ». Le PO voit 677 mais il reste en réalité 1 163 à traiter. |
| **pending** (ruban C3, texte gris côté) | `totals.pending` = `sum(c.n_pending)` | Count de `source_images` avec `route_decision='pending'` — listings **pas encore téléchargés ou routés** | Champ `n_pending` de `_coin_tail` via `_roll(lambda d: d == 'pending')` | **HEURISTIQUE / MAL LIBELLÉ** | **B4.** Valeur : **1 907**. Pas une file de review mais un arriéré de scrape/routing. Le libellé « pending » est ambigu : le PO comprend « en attente de review » alors qu'il s'agit de listings jamais téléchargés. Renommer en « non téléchargés » ou « à traiter » |
| **rejetés** (ruban C3, aside) | `totals.rejected` = `sum(c.n_rejected)` | `route_decision` startswith `'rejected'` sur `source_images` (= `rejected_text` ici) | `_roll(lambda d: bool(d) and d.startswith('rejected'))` | **HONNÊTE** | Valeur : 16 (tous `rejected_text`). Distinct des `image_assets.resolution_status='rejected'` (63) |
| **N DL** (phrase funnel par pièce) | `c.n_downloaded` | `source_images` avec `download_status='success'` pour ce coin | `SELECT COUNT(*) FROM source_images WHERE download_status='success' AND target_eurio_id=?` | **Honnête en données** | **MAL POSITIONNÉ.** Dans la phrase : `listings → crops → review · pending → N DL`. « DL » apparaît APRÈS review et pending avec une flèche `→`, suggérant que c'est une étape ultérieure. Or le téléchargement est **antérieur** au crop. Pour `fi-2016` : 251 DL = 251 total (toujours inutile à afficher). Valeur globale : 2 588 — souvent égale à n_source_images, donc sans information marginale |
| **en review** (phrase funnel par pièce, bleu) | `c.n_review_single + c.n_review_lot` | Même données gelées que le ruban (route_decision) | Idem ruban « en review » | **HEURISTIQUE / MENSONGER** | Même bug que le ruban : fi-2016 affiche « 58 review » dans la phrase alors que 27 singles sont `status='done'` et 0 single reste ouvert. Incohérence interne avec le bouton « Reviewer N » qui, lui, utilise `n_open_review_single` (correct, file vivante) |
| **Reviewer N** (bouton action par pièce) | `reviewCount(c)` = `c.n_open_review_single` | `review_queue.status='open' AND kind='single'` joint à `source_images.target_eurio_id=eid` | `SELECT COUNT(*) FROM review_queue rq JOIN image_assets ia JOIN source_images si WHERE status='open' AND kind='single' AND target_eurio_id=?` | **HONNÊTE** | Correct. fi-2016 : 0 bouton affiché (0 single open). Le fix du bug « reviewer scopé par pièce » est en place |
| **N lots** (bouton action par pièce) | `lotReviewCount(c)` = `c.n_open_review_lot` | `review_queue.status='open' AND kind='lot'` pour ce coin | Même query que ci-dessus mais `kind='lot'` | **Honnête** | Correct. fi-2016 : 129 lots open. Mais la route vers `/review/manual?mode=lot&cohort=X` ne scope PAS sur `eurio_id` — le reviewer voit tous les lots de la cohort, pas ceux de fi-2016 uniquement |
| **Recropper N** (bouton action par pièce) | `recropCount(c)` = `c.n_zero_crops` | Raws téléchargés sans aucun crop (`storage_status='present'`) | `SELECT COUNT(*) FROM source_images si WHERE download_status='success' AND NOT EXISTS (SELECT 1 FROM image_assets ia WHERE ia.source_image_id=si.id AND storage_status='present')` | **Honnête** | Valeur totale cohort : ~1 399 (somme par pièce). Correct et actionnable |
| **C4 — Queue manuelle = 3** (carte I) | `manualCount` = `stats.by_lane.manual` | `review_queue.status='open' AND kind='single' AND (lane='manual' OR lane IS NULL)`, cohort-scopé | `_count('rq.status=open AND (lane=manual OR lane IS NULL)', [], kind_clause=True)` = kind='single' par défaut | **Honnête techniquement** | **B3 résolu.** Les 3 vrais singles manuels ouverts. Mais **4 lots en lane manuelle ne sont PAS comptés ici** — ils entrent dans la carte IV « Lots » (n_lot_crops = tous lots open, toutes lanes). Le PO voit « Manuel = 3 » mais il y a 7 items en lane manuelle réels (3 single + 4 lot). Le libellé « à trancher à la main » est trompeur sans mention du découpage single/lot |
| **C4 — Auto-accept = 5** (carte II) | `autoCount` = `stats.by_lane.auto_accept` | `review_queue.status='open' AND kind='single' AND lane='auto_accept'`, cohort-scopé | Idem, `lane='auto_accept'` | **Honnête** | 5 singles. Les 42 lots auto_accept sont dans la carte IV. Non signalé |
| **C4 — CCProxy = 189** (carte III) | `claudeCount` = `stats.by_lane.ccproxy` | `review_queue.status='open' AND kind='single' AND lane='ccproxy'`, cohort-scopé | Idem, `lane='ccproxy'` | **Honnête** | 189 singles. 920 lots ccproxy dans la carte IV. La carte « Lots = 966 » est un fourre-tout qui mélange toutes les lanes |
| **C4 — Lots = 966** (carte IV) | `lotCount` = `stats.n_lot_crops` | `review_queue.status='open' AND kind='lot'`, cohort-scopé, **TOUTES lanes** | `SELECT COUNT(*) FROM review_queue rq JOIN ... WHERE rq.status='open' AND rq.kind='lot'` | **Honnête en données** | **MAL STRUCTURÉ.** La carte IV est hétérogène (manual=4 + auto=42 + ccproxy=920). La carte « Lots = 966 » cache que 920/966 sont en lane ccproxy (traitement automatisable) vs 4 qui nécessitent le même flow manuel que la carte I |
| **C4 — n_pending** (état de la section) | `stats.n_pending` | `review_queue.status='open' AND kind='single'`, cohort-scopé (pas ALL kinds) | `_count('rq.status=open', [], kind_clause=True)` → kind='single' = 197 | **Partiellement honnête** | `n_pending=197` ne reflète que les singles. L'état `partial` est déclenché par `n_pending > 0 OR lotCount > 0` ce qui est correct, mais l'affichage du chiffre brut 197 ne dit pas « singles seulement » |
| **63 rejetés à récupérer** (strip C4) | `rejectedCount` = `stats.n_rejected` | `image_assets.resolution_status='rejected'`, cohort-scopé (join review_queue) | `SELECT COUNT(*) WHERE a.resolution_status='rejected'` | **Honnête** | 63 items rejetés (rq.status='done' + resolution='rejected'). Distingué correctement des 16 `rejected_text` du ruban C3 |
| **4 skippés** (strip C4) | `skippedCount` = `stats.n_skipped` | `review_queue.status='open' AND decision_notes='skipped'`, cohort-scopé | Requête dédiée, pas `status='skipped'` | **Honnête** | Ces 4 items sont **aussi comptés dans n_pending** (status='open'). Le strip les signale correctement comme « dans la queue » mais l'utilisateur peut croire qu'ils s'ajoutent aux cartes I/II/III |
| **by_verdict** (non affiché en C4, fourni par l'API) | Non utilisé dans C4 | Recompute au moment de la requête via `compute_auto_validate_verdict_from_row` + Dino predictions | Scan Python sur tous les items open, NOT stored per item | **HEURISTIQUE** | Non utilisé dans C4 (uniquement dans ReviewDashboardPage global et ClaudeReviewPage). Correct de ne pas l'afficher ici |

---

## Explication de B3 — « manuelle bloquée sur 3 »

La carte I (Queue manuelle) affiche **3** parce que :

1. La requête `by_lane.manual` est appelée avec `kind_clause=True` (défaut `kind='single'`)
2. Les 4 lots en lane manuelle (`rq.lane='manual' AND rq.kind='lot'`) sont **exclus** de cette carte
3. Ils atterrissent dans la carte IV « Lots = 966 » qui agrège TOUTES les lanes

Ce « 3 » est donc **exact** pour les singles manuels, mais **cache** 4 lots manuels et 120 singles manuels non-cohort (global = 124). La global manual open est 512 (tous kinds + toutes cohortes).

```
Réalité lane=manual pour cohort b0299ca0252b :
  kind='single', open : 3   ← affiché dans carte I
  kind='lot',    open : 4   ← noyé dans carte IV (966 total)
  TOTAL lane manual        : 7

Global (toutes cohortes + tous kinds) :
  status='open'            : 2 483
  lane=manual (tous kinds) : 512   ← le chiffre de recon initial
```

---

## Explication de B4 — « pending » vs « review » vs DL

```
Concept         | Libellé UI         | Valeur réelle | Signification réelle
----------------|--------------------|--------------|-----------------------
route_decision='pending' | « pending » ruban | 1 907 | Listings eBay en attente de download+routing (PAS de review)
route_decision='review_*' | « en review » ruban | 677 | Intention gelée au scrape — certains sont DÉJÀ TRAITÉS
review_queue status='open' single | n_pending C4 | 197 | Singles réellement en attente de review humaine
review_queue status='open' lot | n_lot_crops C4 | 966 | Lots réellement en attente de review
download_status='success' | « DL » phrase | 2 588 | Images téléchargées en storage — PAS une étape après review
```

Le terme **« pending »** est utilisé avec deux sens contradictoires :
- Dans le ruban C3 : `route_decision='pending'` = listings pas encore traités par le pipeline de routage (1 907)
- Dans C4 (`n_pending`) : `review_queue.status='open'` = crops attendant une décision review (197 singles)

---

## Liste priorisée des corrections

| Priorité | Compteur | Action |
|---|---|---|
| P0 | **Ruban « en review »** | Remplacer `n_review_single + n_review_lot` (gelé) par `n_open_review_single + n_open_review_lot` (vivant) = 197+966 = 1 163 |
| P0 | **Phrase funnel « N review »** | Même fix : utiliser `n_open_review_single + n_open_review_lot` au lieu de `n_review_single + n_review_lot` |
| P1 | **Ruban « pending »** | Renommer en « non routés » ou « à traiter » (route_decision='pending' = arriéré scrape, pas review) |
| P1 | **Carte IV Lots = 966** | Décomposer en sous-compteurs par lane (manuel : 4, auto : 42, ccproxy : 920) ou ajouter un badge « dont 920 ccproxy » |
| P2 | **Carte I « Queue manuelle = 3 »** | Ajouter mention « + 4 lots » (lane=manual kind=lot non comptés ici) ou regrouper dans la carte I |
| P2 | **Label « DL »** | Déplacer avant « crops extraits » dans la phrase funnel (ordre pipeline) ou supprimer si toujours = n_source_images |
| P3 | **Lots bouton « N lots »** | Scoper la route `/review/manual?mode=lot&cohort=X&eurio_id=Y` pour filtrer la file par pièce (actuellement montre toute la cohort) |
| P3 | **n_skipped strip C4** | Ajouter note « (inclus dans les cartes ci-dessus) » pour éviter double-compte perçu |



---


# [RECHERCHE R1-label-studio] Label Studio — modèle d'état & UX pipeline : leçons pour le cockpit cohorte Eurio

**Resume.** Label Studio (Enterprise) modélise chaque tâche comme un objet avec un cycle de vie explicite à 5 états (Unlabeled → Annotating → Needs Review → Done / Rejected), des compteurs honnêtes séparés (annotated ≠ reviewed ≠ accepted), et deux files physiquement distinctes : le labeling stream (annotateurs) et le review stream (reviewers). L'annotation est un sous-objet propre avec son propre enum last_action (submitted / accepted / rejected / fixed_and_accepted / skipped). Les compteurs du dashboard ne mentent pas : "Annotated Tasks" ≠ "Done" — un task est done uniquement quand il passe le review gate configuré. L'export est un snapshot asynchrone versionné, découplé de la file live. Ces patterns sont directement transposables à notre cockpit cohorte eBay→crop→match→review→training-eligible, où chaque image doit avoir un statut explicite, des compteurs par étage, et une séparation nette entre "crop fait" et "review validé".


**Takeaways**

- DÉCISION : Ajouter `image_assets.status` comme enum explicite (scraped / crop_failed / crop_done / review_pending / accepted / rejected / training_ready / trashed) — remplace les heuristiques temps-réel actuelles du cockpit.
- DÉCISION : Séparer physiquement le crop-stream et le review-stream dans /lab (deux tabs/vues), avec des compteurs indépendants par étage — ne plus avoir un seul % global.
- DÉCISION : Ajouter `last_review_action`, `reviewed_by`, `reviewed_at`, `rejection_reason` sur `image_assets` pour l'audit trail — sur le modèle du `last_action` enum de Label Studio.
- DÉCISION : Implémenter un gate explicite `accepted → training_ready` : pas de promotion silencieuse, le bouton affiche combien d'images sont concernées et lesquelles sont encore en `pending`.
- DÉCISION : Créer `export_training_snapshot.py` qui produit un snapshot versionné immutable (JSON avec metadata cohort/date/stats) découplé de la file live — reproductibilité des runs training.
- A TRANCHER : Où vit le status enum ? Sur `image_assets` directement (colonne) ou dans une table d'événements séparée (log d'états) ? Le log d'états est plus riche (historique complet) mais plus lourd à requêter pour le cockpit.
- A TRANCHER : Les `rejection_reason` doivent-elles être un enum fixe (tilt / hors-cible / multi-coin / basse-qualité / doublon) ou du texte libre ? Label Studio utilise du texte libre ancré sur la règle — l'enum est plus exploitable pour les stats pipeline.
- NEXT : Le handoff cockpit rebuild (docs/cohort-pipeline/REBUILD-HANDOFF.md) doit intégrer ces 6 états et les 5 étages de compteurs comme contrat de l'UI — à faire avant de toucher le frontend.


## 1. Modèle d'état d'une Task — ce que Label Studio fait bien

### 1.1 Cycle de vie complet d'une task

```
UNLABELED
   │
   ▼ (annotateur soumet)
ANNOTATING / ANNOTATED
   │
   ▼ (seuil minimum annotations atteint)
NEEDS REVIEW            ← file du reviewer
   │           │
   ▼           ▼
ACCEPTED    REJECTED → requeue → retour ANNOTATING
   │
   ▼
DONE  (état terminal)
```

Variante sans reviewer configuré : ANNOTATED → DONE directement (court-circuit explicite, pas silencieux).

**Champs clés sur l'objet Task (API `/tasks/{id}`)** :

| Champ | Type | Sémantique |
|---|---|---|
| `is_labeled` | bool | `total_annotations >= max_completions` — **définition précise**, pas "a au moins une annotation" |
| `reviewed` | bool | review terminée selon le gate configuré |
| `ground_truth` | bool | annotation de référence désignée manuellement |
| `total_annotations` | int | toutes annotations soumises (y compris rejetées) |
| `cancelled_annotations` | int | annotations skippées (l'annotateur a passé) |
| `reviews_accepted` | int | compteur reviewer accept |
| `reviews_rejected` | int | compteur reviewer reject |
| `avg_lead_time` | float | temps moyen d'annotation |
| `state` | string | état courant de la task |

### 1.2 Cycle de vie d'une Annotation (sous-objet)

L'annotation a son propre enum `last_action` :

```
prediction          → importée depuis un modèle ML
imported            → importée depuis fichier
submitted           → soumise par annotateur
updated             → modifiée après soumission
skipped             → annotateur a passé (was_cancelled=true)
accepted            → reviewer a accepté
rejected            → reviewer a rejeté
fixed_and_accepted  → reviewer a corrigé puis accepté
deleted_review      → review supprimée (retour arrière)
propagated_annotation → propagée depuis une autre task
```

**Point fort** : la dernière action est tracée sur l'objet lui-même → audit trail natif sans table externe.

---

## 2. Files de travail — Data Manager, vues par rôle

### 2.1 Deux streams physiquement séparés

| Stream | Qui y accède | Ce qu'il contient |
|---|---|---|
| **Labeling stream** | Annotateurs | Tasks `UNLABELED` assignées à eux |
| **Review stream** | Reviewers | Tasks `NEEDS_REVIEW` (au moins une annotation soumise) |

Le reviewer peut trier son stream par : annotateur, niveau d'agreement, score de confiance modèle. L'annotateur ne voit que ses tasks assignées.

### 2.2 Data Manager = vue SQL-like sur les tasks

- Colonnes activables : Ground Truth, Agreement Score, Total Annotations, Review Status, etc.
- **Tabs = vues filtrées persistées** : on peut créer un tab "À annoter", un tab "En review", un tab "Rejetés", etc.
- Filtres structurés (Enterprise) : par label, statut, annotateur, score, date.
- Assignment bulk : sélectionner N tasks → assigner à annotateur X via dropdown.

### 2.3 Distribution automatique vs manuelle

- **Auto** : les annotateurs sont assignés aux tasks en entrant dans le labeling stream.
- **Manuel** : l'admin choisit quelle task va à quel annotateur → modèle pour notre cockpit où c'est un humain qui review.

---

## 3. Compteurs et progression — honnêteté des métriques

### 3.1 Dashboard Projet — 8 KPI cards

| KPI card | Ce qu'il mesure précisément |
|---|---|
| **Annotated Tasks** | tasks avec `is_labeled=true` + % sur total + skipped count |
| **Reviewed Annotations** | annotations passées en review, splitté accepted/rejected |
| **Submitted Annotations** | toutes soumissions y compris skipped |
| **Remaining Tasks** | tasks sans `is_labeled=true` + % remaining |
| **Tasks Pending Review** | tasks en `NEEDS_REVIEW` dans la période |
| **Lead Time** | moyenne heures pour compléter toutes annotations d'une task |
| **Avg Time Per Task** | durée moyenne en minutes |
| **Regions Created** | somme des régions annotées (bbox, polygones...) |

**Règle d'or** : `Annotated Tasks` ≠ `Done`. Une task annotée qui n'a pas encore passé le review gate n'est PAS comptée dans "Done". Les compteurs ne mentent pas sur l'avancement réel.

### 3.2 Agreement Matrix (Members Dashboard)

- Matrice croisant annotateurs × annotateurs : score d'agreement pairwise
- Permet de détecter les annotateurs outliers
- Calculé comme mean agreement score sur les control tags

### 3.3 Séries temporelles

Graphiques time-series pour : tasks annotées, reviews soumises, annotations créées, labels distribués. Fenêtre temporelle configurable. Utile pour mesurer la vélocité et détecter les goulots.

---

## 4. Séparation Annotation / Review / QA

### 4.1 Trois phases explicites avec gates configurables

```
Phase 1 — Annotation
  - Seuil : min_annotations (ex: 1 ou 3 par task)
  - Gate : quand atteint → NEEDS_REVIEW automatique

Phase 2 — Review
  - Reviewer : Accept / Fix & Accept / Reject (+Remove ou +Requeue)
  - Gate configuré : "accept 1 annotation suffit" OU "review toutes les annotations"
  - Requeue = retour à l'annotateur avec commentaire
  - Remove = rejet définitif

Phase 3 — QA / Ground Truth
  - Ground truth = annotation désignée comme vérité terrain
  - Utilisée pour évaluer les nouveaux annotateurs (onboarding gates)
  - Permet de mesurer recall/precision par annotateur
```

### 4.2 Feedback loop documenté

- Rejet = toujours accompagné d'un commentaire ancré sur la règle spécifique.
- Les patterns de rejets répétés signalent que le rubric doit être mis à jour.
- La boucle : annotation → rejection → rubric update → re-annotation → acceptance.

---

## 5. Export Dataset — snapshots versionnés

### 5.1 Concept de snapshot

- Snapshot = export asynchrone immutable d'un état du projet à un instant T.
- Process : `POST /export` → retourne un `export_pk` → `GET /export/{pk}/status` → `GET /export/{pk}/download`.
- Découplé de la file live : le snapshot fige l'état, la file continue.
- Formats : JSON (complet), JSON_MIN (léger), COCO, YOLO, Pascal VOC, CSV, CoNLL...

### 5.2 Ce qui est inclus/exclu

- Par défaut : toutes tasks annotées, y compris cancelled.
- `download_all_tasks=true` : inclut tasks sans annotation.
- Pas de filtre natif "accepted only" exposé directement, mais les tabs permettent de pré-filtrer avant l'export.

---

## 6. Idées CONCRÈTES transposables au cockpit cohorte Eurio

Notre pipeline cible : `eBay scrape → crop → match → review → training-eligible → enrichissement`

### Idée A — Statuts explicites par image (pas par cohorte)

Modéliser chaque image comme un objet avec son propre `status` enum, sur le modèle du `last_action` de Label Studio :

```python
class ImageStatus(str, Enum):
    scraped        = "scraped"        # eBay item téléchargé, pas encore cropé
    crop_failed    = "crop_failed"    # Hough/YOLO n'a pas trouvé de cercle
    crop_done      = "crop_done"      # crop disponible, pas encore reviewé
    review_pending = "review_pending" # dans la file reviewer
    accepted       = "accepted"       # reviewer a validé
    rejected       = "rejected"       # reviewer a rejeté (+ raison)
    training_ready = "training_ready" # eligible → dataset training
    trashed        = "trashed"        # éliminé définitivement
```

Actuellement dans eurio.db : les statuts sont implicites (présence/absence de colonnes). Rendre ça explicite dans `image_assets.status` évite les heuristiques temps-réel qui cassent le cockpit.

### Idée B — Deux vues séparées comme Label Studio : "crop stream" vs "review stream"

Créer deux tabs distincts dans `/lab` :
- **Crop stream** : images en `scraped` → affiche le crop auto, l'opérateur valide le cercle ou recadre.
- **Review stream** : images en `crop_done` → affiche l'image croppée, l'opérateur match/valide l'eurio_id.

Séparation nette : l'opérateur qui crop n'est pas forcément celui qui review le match. Et surtout : les compteurs de chaque stream sont indépendants.

### Idée C — Compteurs honnêtes par étage de pipeline (pas un seul % global)

Sur le modèle des 8 KPI cards du dashboard Label Studio, afficher dans le cockpit :

```
Étage 1 — Scrape     : N items eBay | N images téléchargées | N failed
Étage 2 — Crop       : N cropé      | N crop_failed          | N en attente
Étage 3 — Match      : N matched    | N no_match             | N ambiguous
Étage 4 — Review     : N accepted   | N rejected             | N pending_review
Étage 5 — Training   : N training_ready | N trashed
```

Règle importée de Label Studio : `crop_done ≠ training_ready`. Le cockpit ne doit jamais additionner des étages différents dans un seul % d'avancement.

### Idée D — Gate de transition explicite (pas de promotion silencieuse)

Label Studio : une task ne passe jamais de ANNOTATED à DONE sans passer par le review gate — même si le reviewer n'est pas configuré, c'est une décision explicite (bypass documenté).

Pour Eurio : aucune image ne passe en `training_ready` sans passer par `accepted`. Rendre le gate visible dans l'UI : un bouton "Validate batch → training_ready" qui affiche combien d'images vont être promues et lesquelles sont encore en `pending`.

### Idée E — Audit trail sur chaque transition (modèle `last_action`)

Label Studio trace `last_action` sur chaque annotation. Pour `image_assets`, ajouter :

```sql
ALTER TABLE image_assets ADD COLUMN last_review_action TEXT; -- accepted/rejected/fixed/trashed
ALTER TABLE image_assets ADD COLUMN reviewed_by TEXT;        -- username ou 'auto'
ALTER TABLE image_assets ADD COLUMN reviewed_at TIMESTAMP;
ALTER TABLE image_assets ADD COLUMN rejection_reason TEXT;   -- ancré sur une règle (tilt/multi-coin/hors-cible...)
```

Le rejection_reason ancré sur une règle (comme Label Studio l'exige) permet ensuite d'agréger : "18% des rejets = tilt, 30% = hors-cible" → informe le pipeline crop.

### Idée F — Snapshot d'export versionné pour chaque run training

Au lieu d'un export "live" qui change à chaque fois, créer un snapshot à date fixe :

```python
# ml/sources/_base/steps/export_training_snapshot.py
snapshot = {
    "version": "cohorte-mix-zone-17-v2",
    "created_at": "2026-06-06T...",
    "filter": {"status": "training_ready", "cohort_id": "mix-zone-17"},
    "stats": {"total": 847, "classes": 23, "avg_per_class": 36.8},
    "images": [...],
}
```

Découplé de la file live : le modèle est entraîné sur un snapshot immutable, pas sur une requête SQLite dynamique. Permet de re-entraîner sur la même version des données sans surprise.

---

## Résumé — Ce que Label Studio fait bien (à imiter)

| Pratique Label Studio | Problème qu'elle résout | Transposition Eurio |
|---|---|---|
| État explicite par objet (`last_action` enum) | Pas de "où en est cette image ?" sans recalcul | `image_assets.status` enum explicite |
| Deux streams séparés (labeling / review) | Mélange des rôles, mauvaise priorisation | `/lab` crop-stream vs review-stream |
| Compteurs par phase (annotated ≠ done) | Un seul % global qui ment | Funnel 5 étages affiché |
| Gate de transition configurable | Promotion silencieuse → données sales en training | Gate `accepted → training_ready` visible |
| Rejection avec raison ancrée sur règle | Rejets non exploitables, rubric ne s'améliore pas | `rejection_reason` enum (tilt/hors-cible/multi...) |
| Snapshot versionné découplé de la file | Résultats training non reproductibles | `export_training_snapshot.py` immutable |


---


# [RECHERCHE R2-cvat] CVAT — Machine d'états, QA loop et analytics : transpositions pour notre cockpit

**Resume.** CVAT structure son pipeline en 3 couches orthogonales : une hiérarchie Project→Task→Job, un axe stage (annotation/validation/acceptance) et un axe state (new/in_progress/rejected/completed). Ces deux axes indépendants forment une machine d'états à 12 cellules potentielles qui pilote tout : affichage de la progress bar, routage vers le bon assignee, et déclenchement des QA automatiques. La boucle review→rejet→ré-annotation est explicite et limitée par un paramètre 'max_validations_per_job', évitant les cycles infinis. Les honeypots (frames GT insérées secrètement dans les jobs normaux) permettent de mesurer la qualité sans coût de validation 1:1. L'analytique est pyramidale : projet→tâche→job→user, avec objets/heure, temps de travail, et quality score par job. Ces patterns sont directement transposables à notre cockpit de pipeline cohorte.


**Takeaways**

- T1 — Adopter deux champs orthogonaux pipeline_stage × item_state dans la table SQLite des crops, plutôt qu'un seul champ 'status'. La machine d'états CVAT à 12 cellules est le bon modèle.
- T2 — Ajouter review_attempts (int) par crop + plafond configurable pour éviter les boucles review infinies. Escalader vers 'needs_manual' au lieu de boucler indéfiniment.
- T3 — La progress bar cockpit doit être pondérée par étage (detect/done < review/done < train/done), pas un simple comptage de frames. Définir les poids avant d'implémenter l'UI.
- T4 — Implémenter des 'gold frames' (subset captures physiques validées) injectées secrètement dans les batches review eBay. Score quality gold = KPI de fiabilité reviewer, mesurable sans surcoût.
- T5 — Ajouter une vue throughput par cohorte×étage×session dans le cockpit : crops validés/h et taux de rejet par étage, pour identifier les goulots réels du pipeline.
- T6 — Anticiper un champ assignee sur les batches de review dans le schéma SQLite, même en mode solo, pour la séparation future vue 'pipeline ops' vs vue 'review queue'.


## 1. Hiérarchie Project → Task → Job

```
Project
└── Task (= dataset / cohorte)
    ├── Job 1  [stage=annotation, state=in_progress, assignee=alice]
    ├── Job 2  [stage=validation, state=new,          assignee=bob]
    ├── Job 3  [stage=acceptance, state=completed,    assignee=—]
    └── Job GT [stage=acceptance, state=completed]   ← Ground Truth job (spécial)
```

- Un **Task** correspond à un jeu de données (notre équivalent : une cohorte de pièces).
- Chaque **Job** est une tranche assignable d'une tâche (notre équivalent : un lot de crops par étage du pipeline).
- Le **Ground Truth job** est un job spécial, non modifiable par les annotators, qui sert de référence pour les scores automatiques.

---

## 2. Machine d'états : stage × state

### Axe stage (rôle de l'étape)
| Stage | Signification |
|---|---|
| `annotation` | Travail de labelling en cours |
| `validation` | Vérification QA par un reviewer |
| `acceptance` | Accepté — prêt à l'export |

### Axe state (progression dans l'étape)
| State | Signification |
|---|---|
| `new` | Assigné mais pas démarré |
| `in_progress` | Actif |
| `rejected` | Refusé par le reviewer → retour annotator |
| `completed` | Étape terminée |

### Transitions clés documentées

```
[annotation / new]
  → [annotation / in_progress]  (annotator commence)
  → [annotation / completed]    (annotator soumet)
  → [validation / new]          (manager re-assigne au reviewer)

[validation / in_progress]
  → [validation / completed]    (reviewer approuve)
  → [annotation / rejected]     (reviewer rejette → re-annotation)
        ↑________________________|  (boucle, limitée par max_validations_per_job)

[acceptance / completed]        (job GT ou job final validé → qualité calculable)
```

**Point clé** : stage et state sont **indépendants** — on peut avoir `stage=validation, state=new` (assigné au reviewer mais pas encore ouvert). Ce découpage permet d'afficher l'état précis sans ambiguïté.

---

## 3. Honeypots et Ground Truth : mécanique QA

### Ground Truth (GT)
- Job spécial `acceptance/completed` dans la tâche.
- Frames annotées par un expert, invisibles aux annotators normaux.
- Calcul automatique : TP / FP / FN par comparaison forme à forme.
- Métriques : **Accuracy**, **Precision**, **Recall** (configurable lequel est le target metric).

### Honeypots
- Variante du GT : les frames GT sont **injectées secrètement** dans les jobs normaux.
- L'annotator ne sait pas quelles frames sont de contrôle.
- Le même pool de frames GT est réutilisé sur plusieurs jobs → coût de validation divisé par N.
- Limitation : images uniquement (pas vidéo/séquence ordonnée), gelé à la création du task.

### Score et feedback immédiat
- Dès qu'un job passe à `completed`, le score est calculé et **affiché à l'annotator** immédiatement (dialog de complétion).
- Si score < `target_metric_threshold` → le job repasse en `rejected`, l'annotator est invité à corriger.
- `max_validations_per_job` plafonne le nombre de tentatives → évite les boucles infinies.

---

## 4. Affichage de la progression

### Progress bar tâche
- Alimentée par les `stage` + `state` de chaque job enfant.
- Pas un simple compteur "% frames annotées" — c'est une **agrégation pondérée** par étape.

### Vue Jobs dans une tâche
Colonnes affichées par job :
| Colonne | Contenu |
|---|---|
| Stage | annotation / validation / acceptance |
| State | new / in_progress / rejected / completed |
| Assignee | user assigné à ce stage |
| Duration | temps cumulé passé sur ce job |
| Quality | score QA si GT disponible |

Filtrable + triable par : status, assignee, date de mise à jour.

### Analytics pyramidales (3 niveaux)
- **Projet** : agrégat de toutes les tâches
- **Tâche** : agrégat de tous les jobs
- **Job** : granularité individuelle

---

## 5. Analytics / Throughput

### Métriques clés
| Métrique | Définition |
|---|---|
| `objects_diff` | Créations − suppressions sur la période |
| `avg_annotation_speed` | Objets annotés / heure (peut être négatif si beaucoup de suppressions) |
| `total_working_time` | Temps total cumulé par user/job/task |
| `total_images` | Volume de frames traitées |

### Dashboards Grafana (self-hosted)
3 dashboards : **All Events** / **Management** / **Monitoring**
- All Events : timeline brute des actions (create, update, delete shape)
- Management : vue opérationnelle par task/user, working time, throughput
- Monitoring : santé serveur + erreurs

### Contrôle d'accès aux analytics
| Rôle | Visibilité |
|---|---|
| Owner / Maintainer | Toutes les analytics |
| Supervisor | Ses projets assignés |
| Worker | Ses propres jobs uniquement |

---

## 6. Export formats

20+ formats supportés via la couche **Datumaro** (framework de conversion interne) :

| Famille | Formats |
|---|---|
| Détection | COCO, YOLO (Ultralytics), Pascal VOC, KITTI |
| Segmentation | COCO-Seg, Cityscapes, Segmentation Mask |
| Tracking | MOT, MOTS |
| Divers | LabelMe, ImageNet, WiderFace, VGGFace2, Market-1501, CamVid |
| Natif | Datumaro (format pivot CVAT) |

Export disponible depuis projet, tâche, ou job individuel (exports partiels possibles).

---

## 7. Transpositions concrètes pour notre cockpit cohorte

| # | Pattern CVAT | Transposition cockpit Eurio |
|---|---|---|
| **T1** | Stage × State orthogonaux (12 cellules) | Modéliser chaque crop avec `pipeline_stage` (fetch/detect/crop/review/train) × `item_state` (pending/in_progress/rejected/done). Afficher les deux axes dans le cockpit — pas un seul champ "status" ambigu. |
| **T2** | Boucle review→rejected→ré-annotation limitée par `max_validations` | Pour nos crops en review admin : ajouter un compteur `review_attempts` par crop_id, plafond configurable (ex. 3). Après le plafond, escalader vers une file "needs_manual" plutôt que boucle infinie. |
| **T3** | Progress bar alimentée par stage+state agrégés, pas par frames brutes | La progress bar du cockpit par cohorte = somme pondérée par étage : 1 crop en `detect/done` vaut moins qu'1 crop en `review/done`. Définir les poids par étage pour avoir un % cockpit significatif. |
| **T4** | Honeypots : même pool GT réutilisé sur N jobs, annotator aveugle | Pour notre bench : subset fixe de crops "gold" (captures physiques validées) injecté dans chaque batch de review eBay. Le reviewer ne sait pas lesquels sont gold → mesure de la cohérence reviewer sans surcoût. Score quality gold = métrique de fiabilité reviewer. |
| **T5** | Analytics pyramidales projet→tâche→job→user avec objets/heure | Cockpit : ajouter une vue throughput par cohorte → par étage → par session : nb crops validés/h, nb crops rejetés/h, taux de rejet par étage. Permet d'identifier les goulots (ex. crop-bench = goulot vs fetch = fluide). |
| **T6** | Rôle-based visibility des analytics (owner voit tout, worker voit soi) | Dans notre cas solo, moins critique — mais utile pour le futur : séparer les vues "pipeline ops" (tous les jobs) de la vue "review queue" (mes jobs assignés). Anticiper dans le schéma SQLite avec un champ `assignee` sur les batches de review. |

---

## Sources consultées

- [JobStage reference — docs.cvat.ai](https://docs.cvat.ai/docs/api_sdk/sdk/reference/models/job-stage/)
- [Automated QA, Review & Honeypots — docs.cvat.ai](https://docs.cvat.ai/docs/qa-analytics/auto-qa/)
- [Quality control — docs.cvat.ai](https://docs.cvat.ai/docs/qa-analytics/quality-control/)
- [Analytics — docs.cvat.ai](https://docs.cvat.ai/docs/qa-analytics/analytics/)
- [Tasks page — docs.cvat.ai](https://docs.cvat.ai/docs/workspace/tasks-page/)
- [Workflow for organizations — docs.cvat.ai](https://docs.cvat.ai/docs/guides/workflow-org/)
- [Honeypots blog — cvat.ai](https://www.cvat.ai/resources/blog/annotation-qa-honeypots)
- [Quality control academy — cvat.ai](https://www.cvat.ai/academy/labeling-quality-control)
- [Dataset formats — docs.cvat.ai](https://docs.cvat.ai/docs/dataset_management/formats/)



---


# [RECHERCHE R3-roboflow] Roboflow — modèle de curation dataset : idées fortes & transpositions cockpit

**Resume.** Roboflow articule la curation dataset autour de trois primitives orthogonales : (1) le pipeline d'images à états (Unassigned → Annotating → Review → Dataset) organisé en batches trackables, (2) la version figée (snapshot immuable déclenché explicitement par "Generate") qui sépare le dataset vivant du dataset d'entraînement, (3) le Dataset Health Check qui expose class balance, null images, dimension outliers et annotation heatmap dans un seul écran de diagnostic. Le multiplicateur d'augmentation ("Maximum Version Size" 2x/3x) est positionné comme levier pour atteindre un volume cible par classe — pas juste une option technique. Ces trois primitives mappent directement sur les besoins du cockpit cohorte : pipeline par étage observable, version freeze avant run d'entraînement, et health check par classe avec gap-to-target visible. Six transpositions concrètes sont identifiées.


**Takeaways**

- T1 (priorité haute) — Modéliser le cockpit cohorte en sections pipeline par étage (SCRAPED → CROPS_OK → TRAINING_ELIGIBLE → IN_VERSION) plutôt qu'une liste plate. Chaque transition = critère vérifiable.
- T2 (priorité haute) — Ajouter un bouton 'Geler pour entraînement' qui crée un snapshot immuable (timestamp + liste images + params augmentation + split). Correspond à la mécanique 'Generate' de Roboflow, équivalent git tag sur le corpus.
- T3 (priorité haute) — Avant le freeze, afficher pour chaque classe : raw × facteur_aug → images_train estimées vs cible 100. Warning rouge si même 3x est insuffisant → signal 'collecter plus, pas juste augmenter'.
- T4 (priorité haute) — Section 'Santé dataset' : tableau par classe avec colonnes raw / aug×Nx / gap-to-100 / statut (vert/orange/rouge). Barres de progression horizontales. Roboflow ne fait PAS ce calcul gap-to-target automatiquement — c'est notre différenciation.
- T5 (priorité moyenne) — Distribution tilt_deg et axis_ratio par classe comme équivalent de l'annotation heatmap Roboflow : détecter les biais visuels systémiques dans les captures d'une classe avant d'entraîner.
- T6 (priorité moyenne) — Rendre visible la file UNRESOLVED (images sans eurio_id matchée) dans le cockpit avec compteur explicite, à l'image des 'missing annotations' de Roboflow. Ne jamais les écarter silencieusement.
- Insight architectural : Roboflow sépare strictement dataset vivant (pipeline d'états) et dataset d'entraînement (version figée). Cette séparation est le vrai pattern à adopter — pas juste un bouton 'export'.
- Recommandation augmentation : Roboflow recommande de commencer SANS augmentation pour valider la qualité brute du dataset. Appliquer cette discipline : run baseline sans aug, puis 2x ou 3x seulement si les métriques brutes sont insuffisantes.


## 1. Cycle de vie image : pipeline à états explicites

### Modèle Roboflow

| État | Déclencheur entrant | Déclencheur sortant |
|---|---|---|
| **Unassigned** | Upload (batch auto-créé) | Assignation à un annotateur |
| **Annotating** | Assignation batch | Soumission annotation |
| **Review** | Annotation soumise | Approbation / Rejet |
| **Dataset** | Approbation review | (état final pour cette image) |

- Chaque upload crée un **batch** automatiquement. Un batch = groupe d'images trackées ensemble tout au long du pipeline.
- Les batches peuvent être **partiellement assignés** : les images non sélectionnées restent dans un nouveau batch en Unassigned.
- La colonne "Annotating" = file de travail vivante. La colonne "Dataset" = corpus figé disponible pour une version.
- **Mark as Null** : image de fond sans objet — compte dans le dataset mais sans annotation. Distinct de "missing annotation" (image oubliée).

### Transposition cockpit Eurio

> **T1 — Colonne par étage pipeline, pas par statut image**
> 
> Modéliser chaque cohorte en sections `SCRAPED → CROPS_OK → TRAINING_ELIGIBLE → IN_VERSION` à l'image des colonnes Roboflow. Chaque transition = critère explicite (recrop passé, tilt_deg acceptable, classe matchée). L'étage `IN_VERSION` correspond au freeze.

---

## 2. Version figée : le "Generate" comme action de commit dataset

### Modèle Roboflow

- **Version = snapshot point-in-time** : toute modification postérieure (ajout/suppression d'images, re-annotation) n'affecte **jamais** les versions déjà créées.
- Workflow de génération (wizard 3 étapes) :
  1. **Train/Test/Valid split** — configurable avec bouton "Rebalance"
  2. **Preprocessing steps** — appliqués en premier (resize, grayscale, etc.)
  3. **Augmentations** — appliquées après preprocessing, uniquement sur le split train
- **"Generate"** = action explicite et irréversible qui fige le dataset → équivalent d'un `git tag` sur le corpus.
- Une fois généré, la version est **exportable en N formats** (YOLOv8, COCO, Pascal VOC…) de façon déterministe.
- **Reproducibilité garantie** : on sait exactement quelles images, quel preprocessing, quelles augmentations ont produit quel modèle.

### Multiplicateur d'augmentation

```
"Maximum Version Size" = Nx
→ chaque image source donne N images dans le split train :
  - 1 image = preprocessing only (pas d'augmentation)
  - N-1 images = variants augmentés aléatoirement

Exemple : 70 images train × 3x = ~210 images train en sortie
(avec dédup et Filter Null possibles → chiffre légèrement inférieur)
```

Roboflow recommande **2x ou 3x** comme point de départ raisonnable. Le multiplicateur est un levier explicite pour combler un gap de volume par classe, pas juste une option cosmétique.

### Transposition cockpit Eurio

> **T2 — "Freeze Version" comme action explicite dans le cockpit**
>
> Bouton "Geler pour entraînement" qui crée un snapshot SQLite (ou enregistre dans `training_runs`) avec : liste exacte des images éligibles, facteur d'augmentation appliqué, split train/val, timestamp. Pas de modification possible après freeze. Correspond à la doctrine "1 run = N classes snapshot" déjà en place.

> **T3 — Multiplicateur d'augmentation affiché par classe avant freeze**
>
> Avant de geler, afficher pour chaque classe :
> `images_raw=42 × augmentation=3x → images_train=~126 (cible: 100 ✓)`
> Si `images_raw × Nx < 100` → warning rouge "insufficient même à 3x — collecter plus".

---

## 3. Dataset Health Check : diagnostic en un écran

### Métriques affichées par Roboflow

| Section | Ce qui est montré |
|---|---|
| **Overview** | Total images, total annotations, images missing annotations, null annotations, average image size, median aspect ratio |
| **Class Balance** | Nombre d'annotations par classe pour chaque split (train/test/valid) — breakdown visuel |
| **Dimension Insights** | Dot chart de toutes les tailles d'images + distribution des aspect ratios |
| **Annotation Heatmap** | Carte thermique de la position des objets annotés → détecte le "géo-overfitting" |
| **Object Count Histogram** | Distribution du nombre d'objets annotés par image (interactif : cliquer sur une barre → voir les images correspondantes) |

### Signalement des problèmes

Roboflow **notifie** sur :
- Classes sévèrement sous-représentées
- Images avec annotations manquantes
- Images null (fond sans objet)
- Images aux dimensions anormales (aspect ratio outlier)
- Biais positionnel des annotations

La **class balance** est présentée visuellement (graphique bar par classe, ventilé par split). Elle révèle immédiatement quelle classe est sur- ou sous-représentée. Roboflow ne fixe pas de seuil absolu (pas de "minimum 100 images/classe" codé en dur) mais l'imbalance est visible au premier coup d'œil.

### Absence notable

Roboflow n'affiche **pas** de "gap-to-target" calculé automatiquement (ex: "il manque 58 images à la classe X pour atteindre 100"). C'est une opportunité de différenciation pour le cockpit Eurio.

### Transpositions cockpit Eurio

> **T4 — Health Check par classe, section dédiée dans le cockpit**
>
> Une section "Santé dataset" affichant pour chaque design_group/classe :
> ```
> Classe              | Raw | Aug×3 | Gap→100 | Statut
> 2€ Allemagne (A1)   |  42 |  126  |   ✓     | OK
> 2€ France (A12)     |  18 |   54  |  -46    | ⚠ SOUS-REPRÉSENTÉE
> 2€ Vatican (A44)    |   3 |    9  |  -91    | ✗ CRITIQUE
> ```
> Barres de progression horizontales colorées (vert/orange/rouge) selon `min(aug_count, 100) / 100`.

> **T5 — Annotation heatmap → équivalent "crop position heatmap"**
>
> Roboflow détecte le géo-overfitting via la heatmap de position des annotations. Transposition : afficher la distribution tilt_deg et axis_ratio par classe pour détecter les biais visuels (ex: toutes les captures d'une classe sont inclinées à 30°+, ce qui biaiserait l'entraînement).

> **T6 — "Missing annotations" → équivalent "images sans eurio_id résolu"**
>
> Images scrapées sans match eurio.db = équivalent des images missing annotations de Roboflow. Les mettre dans une file d'audit explicite `UNRESOLVED` visible dans le cockpit, avec compteur, et non silencieusement écartées.

---

## Synthèse des 6 transpositions

| # | Concept Roboflow | Transposition cockpit Eurio | Priorité |
|---|---|---|---|
| T1 | Pipeline à colonnes (Unassigned→Dataset) | Sections par étage pipeline par cohorte (SCRAPED→IN_VERSION) | Haute |
| T2 | "Generate" = freeze irréversible | Bouton "Geler version" → snapshot SQLite avec métadonnées complètes | Haute |
| T3 | Multiplicateur Nx affiché avant generate | Calcul `raw × Nx → images_train` + warning si insuffisant même à Nx | Haute |
| T4 | Class balance bar chart par split | Tableau gap-to-target par classe avec barres colorées vert/orange/rouge | Haute |
| T5 | Annotation heatmap (géo-overfitting) | Distribution tilt_deg/axis_ratio par classe (biais visuel) | Moyenne |
| T6 | Missing annotations = file d'audit | Images UNRESOLVED (sans eurio_id) visibles et comptées, non silencieuses | Moyenne |

---

## Sources consultées

- [Upload Images, Videos, and Annotations | Roboflow Docs](https://docs.roboflow.com/datasets/adding-data)
- [Dataset Batches | Roboflow Docs](https://docs.roboflow.com/datasets/manage-datasets/manage-batches)
- [Dataset Versions | Roboflow Docs](https://docs.roboflow.com/datasets/dataset-versions)
- [Create a Dataset Version | Roboflow Docs](https://docs.roboflow.com/datasets/dataset-versions/create-a-dataset-version)
- [Image Augmentation | Roboflow Docs](https://docs.roboflow.com/datasets/dataset-versions/image-augmentation)
- [Dataset Health Check | Roboflow Docs](https://docs.roboflow.com/datasets/dataset-health-check)
- [How to Handle Unbalanced Classes | Roboflow Blog](https://blog.roboflow.com/handling-unbalanced-classes/)
- [Annotate an Image | Roboflow Docs](https://docs.roboflow.com/annotate/use-roboflow-annotate)
- [Launch: Improving Collaboration in Roboflow | Roboflow Blog](https://blog.roboflow.com/annotation-updates/)


---


# [RECHERCHE R4-scale-supervisely] Patterns UI data labeling (Scale/Supervisely + Label Studio/CVAT/Roboflow) — Transpositions cockpit Eurio

**Resume.** Cinq plateformes (Scale Rapid, Scale Nucleus, Supervisely, CVAT/Label Studio, Encord) convergent vers un même modèle d'état explicite : chaque item a un statut persisté (pending → in_progress → submitted/completed → accepted/rejected), les compteurs sont honnêtes par étape (jamais un spinner global), et la navigation classe→item est un clic direct depuis les agrégats. La qualité est un flux séparé du débit : throughput (combien passe) vs quality (combien est bon). Le rework est une boucle première classe, pas un cas limite. Les vues "où en est chaque classe" (class distribution bar, confusion matrix clickable) sont le pattern dominant pour diagnostiquer les gaps de pipeline. Transposés au cockpit cohorte Eurio, ces patterns donnent 6 décisions d'architecture UI concrètes.


**Takeaways**

- T1 (décision architecture) : ajouter une colonne `pipeline_status` enum sur la table captures/images en SQLite — le cockpit ne recompute jamais, il lit ce champ. Les steps Python écrivent ce champ explicitement avant et après leur traitement.
- T2 (composant UI prioritaire) : le bloc 'funnel cohorte' (stacked bar ou tableau ligne/étape) est le composant central du cockpit — une requête GROUP BY status suffit, pas de logique temps réel.
- T3 + T4 (navigation) : chaque compteur dans le funnel ET dans le tableau par classe est un lien cliquable qui filtre la grid sous-jacente — aucune page intermédiaire, aucun écran de chargement.
- T5 (alertes) : implémenter une section 'issues' avec 3 niveaux (Blocking/Severe/Regular) calquée sur Scale Rapid Quality Lab — un SELECT simple sur les classes sous seuil ou les étapes bloquées.
- T6 (header métriques) : afficher en permanence deux KPIs distincts — Throughput (% items ayant passé le pipeline) et Quality (acceptance rate au review) — éviter de fusionner les deux dans un seul chiffre.
- Anti-pattern à valider avant implem : vérifier que les steps Python actuels (normalize, score, auto_validate) écrivent bien un statut en base APRÈS chaque item traité, pas seulement un log fichier — sinon le cockpit ne peut pas être honnête.


## 1. Modèle d'état par plateforme

### Scale Rapid (pipeline annotation humain)

| Étape | Acteur | Statuts possibles |
|---|---|---|
| Attempt | Attempter | `pending` → `in_progress` → `submitted` |
| Review | Reviewer | `submitted` → `accepted` \| `rejected` → retour attempt |
| Audit (optionnel) | Auditor | `completed` → `accepted` \| `rejected` \| `fixed` |

- Deux stages L1 / L2 audit (actors différents obligatoires).
- **Rework = boucle explicite** : reject en review renvoie automatiquement en attempt ; auditor peut `Fix` (édition inline) ou `Reject` (retour queue).
- **Métriques throughput** : Detection Recall (FN), Detection Precision (FP), Annotation Precision (geometry / label / attribute errors).
- Issues Queue (Quality Lab) : 3 niveaux de sévérité (Blocking / Severe / Regular), liste triable, résolution individuelle.

### Scale Nucleus (curation dataset + debug modèle)

- **Slices** = sous-ensembles nommés d'items ; tout agrégat est filtrable par slice.
- **Class Distribution chart** (page Charts) : barre par classe, hover = count absolu, clic = grid des items de cette classe. Dropdown Ground Truth vs modèle sélectionnable.
- **Confusion Matrix** : cellule hover = score normalisé, clic = grid filtrée sur les (predicted, actual) de la cellule. Accès direct aux FP/FN.
- **Navigation invariante** : agrégat → clic → grid items. Jamais de page intermédiaire.
- **Autotag** : exemples positifs/négatifs pour construire une slice par similarité visuelle (embedding-based), itérations multiples.

### Supervisely (labeling jobs + quality control)

**Cycle de vie d'un job :**

```
Created
  ↓
Active (annotateurs pullent depuis queue commune)
  ↓
Submitted (annotateur clique Submit)
  ↓
Under Review (reviewer dans toolbox)
  ↓
Accepted ✓  |  Rejected ✗ → nouveau job de re-annotation
```

**Queue pull-based** : pas d'assignation manuelle, "whoever labels first". Rejected retourne au même annotateur (pas à la queue commune).

**Métriques Labeling Performance (11 charts) :**

| Métrique | Type |
|---|---|
| Status of Assets | stacked bar (pending/submitted/rejected/accepted) |
| Objects (par classe) | bar chart + scatter temporel |
| Labeling Actions | count create/tag |
| Team Activity Heatmap | daily actions/member |
| Labeling Time | temps actif (idle > 5 min exclus) |
| Labeling Speed | objets/heure |
| Average Time per Object | — |
| Acceptance Rate (%) | — |
| Review Time | — |
| Average Review Time/asset | — |

**Members Performance Table** : par annotateur — objects créés, speed, acceptance rate, accepted/rejected count, temps actif.

**Class & Tag Stats Table** : par classe — count objets, assets concernés, temps moyen/objet.

**QC Stats** (quality control dédié) :
- Geometric Accuracy (% correct geometry)
- Class Accuracy (% correct class)
- Tags Accuracy
- Annotations Recall (reviewed / total)
- Reviewed Annotations (count reviewed vs non-reviewed)

**Export** : PDF ou Excel filtré.

### Scale SGP (annotation queue interne)

```
Pending → In Progress → Completed → L1 Audit → L2 Audit
```
- FIFO centralisé, claim manuel possible, skip → retour queue.
- Dashboard manager : queue depth, per-task status, priority, temps pris, items flaggés.
- Throughput : tasks completed over time. Bottleneck identification.

### CVAT / Label Studio / Encord (patterns communs)

- **CVAT** : annotation → review → accepted/rejected par task. Analytics : annotation progress, team performance, time spent per project/job.
- **Label Studio** : predictions uploadées, review human-in-loop, export filtré par status.
- **Encord Active** : per-class accuracy, embedding visualization pour surfacer edge cases, navigation classe → items, integration pipeline curation ↔ annotation dans une seule UI.

---

## 2. Patterns convergents (synthèse des 4 recherches)

### P1. État persisté par item, jamais un spinner global

Toutes les plateformes exposent le statut **de chaque item** (pending/in_progress/submitted/accepted/rejected) en base. Le dashboard manager lit ces statuts ; il ne recalcule pas en temps réel. Les compteurs sont fiables même après reload.

> Transposition cockpit Eurio : chaque `capture` ou `ebay_image` a un `status` en base SQLite (raw / normalized / scored / accepted / rejected). Le cockpit lit ces statuts, il n'interroge pas les fichiers disque ni ne recompute.

### P2. Compteurs honnêtes par étape = funnel visible

Scale Rapid sépare Throughput (débit) et Quality (taux de bon). Supervisely affiche un stacked bar "Status of Assets" par étape. L'utilisateur voit **combien est en cours à chaque étape**, pas seulement un total global.

> Transposition : le cockpit cohorte affiche une ligne par étape de pipeline (scrape → normalize → score → review → accepted) avec compteur `N items` par statut. Chaque nombre est une requête SQL directe sur la colonne `status`.

### P3. Clic sur agrégat → grid d'items (navigation directe)

Nucleus, Supervisely, Encord : cliquer sur une barre de classe ou une cellule de confusion matrix filtre **immédiatement** la grid sous-jacente. Aucune page intermédiaire.

> Transposition : cliquer sur un compteur d'étape dans le cockpit ouvre la liste des items à cet état. Cliquer sur une classe dans la vue "par classe" filtre la grid sur cette classe.

### P4. Vue "par classe" obligatoire (pas seulement un total)

Class Distribution chart (Nucleus), Class & Tag Stats Table (Supervisely), per-class accuracy (Encord) : on voit **quelle classe** a combien d'items, à quelle vitesse, avec quel taux d'acceptation.

> Transposition : la section "par design_group / eurio_id" du cockpit montre le count de captures à chaque étape, le recall du modèle par classe (si disponible), et signale les classes sous le seuil cible (~100 images/classe).

### P5. Rework = boucle première classe, pas un cas limite

Scale : reject → retour attempt automatique. Supervisely : rejected → nouveau job tracé. L'UI fait apparaître les items "en rework" comme une étape à part entière avec son propre compteur.

> Transposition : le cockpit a une section "en révision manuelle" (items rejected ou needs_review) avec le count et un lien direct vers l'outil de review admin. Ce n'est pas une zone morte.

### P6. Throughput ≠ Quality, les deux sont affichés séparément

Scale Rapid : onglet Throughput (débit brut) vs onglet Quality (precision/recall/errors). Supervisely : Labeling Speed séparé d'Acceptance Rate.

> Transposition : le cockpit sépare visuellement "pipeline progress" (combien d'items ont passé chaque étape) de "quality signal" (score moyen du modèle par étape, taux accepted/rejected au review). Les deux sont lisibles d'un coup d'œil sans confusion.

---

## 3. Transpositions concrètes pour le cockpit Eurio

| # | Pattern source | Transposition cockpit cohorte |
|---|---|---|
| T1 | **Scale Rapid — task statuses persistés** | Colonne `pipeline_status` enum sur `cohort_captures` : `raw / normalized / scored / in_review / accepted / rejected`. Jamais inféré, toujours écrit par le step. |
| T2 | **Supervisely — stacked bar "Status of Assets"** | Section "Funnel cohorte" : une ligne par étape, compteur `N` items à cet état, pourcentage de passage. Vue cockpit principale, chargée par `SELECT status, COUNT(*) FROM cohort_captures WHERE cohort_id=? GROUP BY status`. |
| T3 | **Nucleus — clic bar → grid items** | Chaque compteur est un lien `<a href="/cohort/{id}?status=normalized">`. La page suivante liste les items filtrés. |
| T4 | **Nucleus — class distribution clickable** | Section "par classe" : tableau `eurio_id / design_group | count_raw | count_accepted | recall_model | gap_to_target`. Clic → grid des captures de cette classe. Classe sous seuil = fond orange. |
| T5 | **Scale Rapid — Issues Queue (sévérité)** | Section "alertes cockpit" : anomalies classées (Blocking = cohorte bloquée, Severe = classe vide, Regular = classe sous 50 items). Chaque alerte linkée à l'étape concernée. |
| T6 | **Supervisely — Members Performance / Scale Rapid — throughput vs quality** | Deux métriques clés en header cockpit : `Throughput` = items accepted / items total (%; barre de progression), `Quality` = acceptance_rate au review (%). Pas de spinner, valeurs SQL live. |

---

## 4. Anti-patterns à éviter (observés dans les plateformes)

- **Spinner global sans état persisté** : quand le backend plante, l'UI ne sait pas où elle en est. Solution = écrire le statut AVANT de lancer le step (optimistic status = `in_progress`), écrire le résultat après.
- **Agrégats sans drill-down** : un total "3847 items processed" sans possibilité de voir lesquels a quelle étape. Chaque compteur doit être un filtre.
- **Rework invisible** : items rejected qui disparaissent de la vue principale. Solution = statut `rejected` visible dans le funnel avec son propre compteur.
- **Throughput confondu avec qualité** : "90% completed" peut vouloir dire 90% ont fini l'étape mais 40% ont été rejected. Toujours séparer les deux axes.



---


# [DESIGN] Modèle d'état SQLite explicite par cohorte — DDL, machine à états, compteurs, migration

**Resume.** Proposition d'un modèle d'état additif qui ne touche pas le coeur (coins/source_images/image_assets/review_queue). Le grain canonique est le crop (image_assets.id) : une machine à états unique de 9 valeurs réconcilie source_images.crop_status, image_assets.resolution_status et review_queue.status. Trois objets nouveaux : image_state_events (journal append-only, alimenté en applicatif via un helper emit_state_event appelé aux ~12 points de transition déjà identifiés, PAS par triggers), image_state_current (matérialisation 1 ligne/crop tenue à jour dans la même transaction — recommandée vs vue dérivée pour la perf des compteurs cockpit), et cohort_jobs (remplace le thread mémoire _recrop_jobs, corrige B2). B1 est représenté honnêtement par un champ target_eurio_id sur le job + comptage d'attribution réel (jamais-scrapé devient 0-attribué-sur-groupe-scrapé-N-fois). Migration idempotente sur le pattern bootstrap existant (CREATE TABLE IF NOT EXISTS + backfill one-shot gardé par sentinelle), user_version reste 0. Tout est en lecture seule ici : aucune écriture DB, aucune migration lancée, aucun fichier édité.


**Takeaways**

- Grain canonique = le crop (image_assets.id) ; machine à états unique de 9 valeurs (detected, auto_matched, queued, in_review, skipped, resolved, rejected, orphaned, superseded) réconciliant crop_status + resolution_status + review_queue.status. L'état 'orphaned' rend visibles les 544 pending_match sans review_queue (confirmé en DB).
- image_state_events = journal append-only (PK INTEGER AUTOINCREMENT pour ordre total, FK image_assets, cohort_id dénormalisé pour scoping sans JOIN sur le JSON array). Alimenté en APPLICATIF via helper emit_state_event aux 12 call-sites identifiés, PAS par trigger SQLite (un trigger ne connaît ni l'acteur ni le run_id ni la reason — l'exigence PO).
- Compteur courant : table matérialisée image_state_current (1 ligne/crop, UPSERT dans la même transaction que l'event) recommandée vs vue dérivée — le cockpit poll toutes les 4s, la window-function 'dernier event' serait gaspilleuse. Compteurs cockpit = GROUP BY current_state ; 'en review' devient IN ('queued','in_review') (vivant) et corrige B4.
- cohort_jobs remplace le thread mémoire _recrop_jobs (lab_routes.py:1730, perdu au restart) : n_total/n_done/n_produced/tau/note/started/finished, FK experiment_cohorts. Le worker écrit sa progression en autocommit. note='épuisé à tau=0.55, 0 crop' supprime le bouton zombie B2 ; couplé au fix T1 (recrop câble resolve/enqueue).
- B1 corrigé au niveau modèle (pas algo) : cohort_jobs.target_eurio_id + n_attributed_target distinguent 'jamais scrapé' (group_scrape_count=0) de '0 attribué sur groupe scrapé N fois' (cas be-2007). Le badge rouge trompeur disparaît.
- Migration idempotente sur le pattern bootstrap existant (user_version reste 0) : CREATE TABLE IF NOT EXISTS dans schema.sql + backfill one-shot gardé par sentinelle NOT EXISTS, cohort_id rempli en Python depuis eurio_ids_json. ZÉRO ALTER/DROP sur tables coeur. Ordre : schema → backfill → code instrumenté.
- 6 arbitrages soumis au PO : satellite vs colonne current_state, applicatif vs trigger (tranché applicatif), journalisation move_lane, warn-vs-raise sur transition illégale, cohort_id multi-cohorte, fréquence update n_done (K=10 proposé).
- PHASE D'ANALYSE STRICTE respectée : uniquement des SELECT sqlite3 et lectures/grep de fichiers ; aucune écriture DB, aucune migration lancée, aucun fichier édité.


## 0. Principe directeur et ce que je NE touche pas

Grain canonique = **le crop** (`image_assets.id`). C'est le seul grain où coexistent les 3 sous-machines (`source_images.crop_status` en amont, `image_assets.resolution_status` au centre, `review_queue.status` en aval) et c'est l'unité que le reviewer humain tranche. Le listing (`source_images`) est un grain agrégateur dérivé (un listing = N crops) ; on dérive son état des crops, on ne lui invente pas une machine séparée.

Tables coeur **inchangées** (zéro ALTER, zéro DROP) : `coins`, `source_images`, `image_assets`, `review_queue`, `discovery_log`. Vérifié : leur surface d'écriture est bornée et connue (cf. §2.3). On **ajoute 3 objets à côté** :

| Objet | Rôle | Grain |
|---|---|---|
| `image_state_events` | Journal append-only de chaque transition | 1 ligne / transition |
| `image_state_current` | Matérialisation de l'état courant (compteurs cockpit) | 1 ligne / crop |
| `cohort_jobs` | Jobs observables (scrape/recrop), corrige B2 | 1 ligne / job |

Arbitrage de fond soumis au PO : **on n'ajoute PAS de colonne `current_state` sur `image_assets`** (table coeur) — on isole l'état canonique dans `image_state_current` (table satellite, FK 1:1). Avantage : `image_assets` reste strictement le coeur qui marche ; rollback = `DROP TABLE`. Inconvénient : un JOIN de plus pour lire l'état. Je recommande la table satellite (§3). *Choix ouvert à valider.*

---

## 1. Machine à états CANONIQUE d'un crop

### 1.1 L'enum unique (9 états)

Réconcilie les 3 sous-machines en **un seul vocabulaire** lisible par le cockpit. Mapping de réconciliation à droite (la colonne calculée à partir de l'existant lors du backfill).

| `state` canonique | Sens métier | Reconstruit depuis (existant) |
|---|---|---|
| `detected` | Crop créé, pas encore matché | `ia.resolution_status='pending_match'` ET pas de `review_queue` |
| `auto_matched` | Match phash automatique, terminal sans humain | `ia.resolution_status IN ('auto_phash','auto_name')` |
| `queued` | En file de review, ouvert | `rq.status='open'` ET `ia.resolution_status='needs_review'` |
| `in_review` | Pris par un acteur (lane/claude en cours) | `rq.status='in_progress'` |
| `skipped` | Reporté par l'humain, reste à traiter | `rq.decision_notes='skipped'` ET `rq.status='open'` (B3/T4) |
| `resolved` | Tranché → eurio_id posé (humain/auto/claude) | `ia.resolution_status='manual'` ET `rq.status='done'` |
| `rejected` | Crop écarté (pas une pièce / illisible) | `ia.resolution_status='rejected'` |
| `orphaned` | Crop sans file ni résolution (T1/T3) | `ia.resolution_status='pending_match'` ET pas de `rq` ET run terminé |
| `superseded` | Crop remplacé par un recrop ultérieur | aucun équivalent actuel (nouveau, posé par recrop) |

`orphaned` est la nouveauté qui rend visibles les **544 `pending_match` sans review_queue** (vérifié en DB) — aujourd'hui invisibles à toute vue. `skipped` devient un état de 1ère classe (résout l'ambiguïté B3 où skipped reste compté dans `open`).

### 1.2 Catalogue des transitions légales

`actor` ∈ {`pipeline`, `human`, `auto_dino`, `ccproxy`, `recrop`, `system`}. Toute transition hors de ce tableau est un bug à logguer (le helper d'émission §2.1 valide `(from_state → to_state)`).

| from → to | Déclencheur (fonction) | actor | reason (exemple) |
|---|---|---|---|
| ∅ → `detected` | `detect_crop.run_detect_crop` (pending_match) | pipeline | `crop_detected` |
| ∅ → `auto_matched` | `detect_crop` (phash hit) / `recrop_zero` (phash hit) | pipeline / recrop | `phash_match` |
| ∅ → `detected` | `recrop_zero_for_coin` (pending_match) | recrop | `recrop_detected` |
| `detected` → `queued` | `resolve.run_resolve` + `enqueue.run_enqueue` | pipeline | `enqueued` |
| `detected` → `orphaned` | run terminé sans resolve/enqueue (T1/T3) | system | `pipeline_aborted` / `recrop_no_enqueue` |
| `orphaned` → `queued` | backfill enqueue (réparation) | system | `backfill_enqueue` |
| `queued` → `in_review` | prise en charge (lane claude batch) | ccproxy/auto_dino | `picked_up` |
| `queued`/`in_review` → `resolved` | `decide_review` / `run_auto_accept` / ccproxy ack | human/auto_dino/ccproxy | `human_decided` / `auto_accept` / `claude_ack` |
| `queued`/`in_review` → `rejected` | `reject_review` | human | `rejected_not_coin` |
| `queued` → `skipped` | `skip_review` | human | `deferred` |
| `skipped` → `queued` | restauration / réouverture | human | `unskip` |
| `rejected` → `queued` | `restore_rejected` | human | `restored` |
| `resolved` → `queued` | ré-ouverture éditoriale (rare) | human | `reopened` |
| `*` → `superseded` | `recrop_zero` régénère un meilleur crop | recrop | `superseded_by_recrop` |

Note: `move_lane` ne change PAS l'état canonique (l'item reste `queued`), il change la lane → c'est un événement de routage, hors de cette machine. On peut soit l'ignorer, soit le journaliser avec `from_state=to_state='queued'` + `reason='moved_to_manual'` pour l'audit. *Choix ouvert : journaliser les changements de lane ou non.* Je penche pour oui (audit complet) mais en `reason` distinct.

---

## 2. Table `image_state_events` (journal append-only)

### 2.1 DDL exacte

```sql
-- ─── Machine à états explicite des crops (cohort-pipeline rebuild) ─────────
-- Journal append-only : 1 ligne par transition d'état d'un crop. Source de
-- vérité historique. Alimenté en APPLICATIF (helper emit_state_event dans
-- store.py), JAMAIS par trigger SQLite (cf. justification §2.2).
-- Additif : ne touche aucune table coeur. FK -> image_assets(id).
CREATE TABLE IF NOT EXISTS image_state_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,   -- ordre total stable
  asset_id      TEXT NOT NULL
                REFERENCES image_assets(id) ON DELETE CASCADE,
  from_state    TEXT,                                -- NULL = première transition (∅ → detected)
  to_state      TEXT NOT NULL
                CHECK (to_state IN (
                  'detected','auto_matched','queued','in_review',
                  'skipped','resolved','rejected','orphaned','superseded'
                )),
  actor         TEXT NOT NULL
                CHECK (actor IN (
                  'pipeline','human','auto_dino','ccproxy','recrop','system'
                )),
  reason        TEXT,                                -- code court stable (cf. catalogue §1.2)
  eurio_id      TEXT,                                -- eurio_id décidé/posé à cette transition (si applicable)
  run_id        TEXT,                                -- source_runs.id OU cohort_jobs.id selon l'acteur
  cohort_id     TEXT,                                -- dénormalisé pour scoping cockpit sans JOIN
  detail_json   TEXT,                                -- libre : {sim, spread, top1, notes, reject_reason...}
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ise_asset
  ON image_state_events(asset_id, id DESC);          -- "dernier event d'un crop"
CREATE INDEX IF NOT EXISTS idx_ise_cohort_to
  ON image_state_events(cohort_id, to_state);        -- audit par cohorte
CREATE INDEX IF NOT EXISTS idx_ise_run
  ON image_state_events(run_id);                     -- "tous les events d'un job"
CREATE INDEX IF NOT EXISTS idx_ise_created
  ON image_state_events(created_at DESC);            -- timeline cockpit
```

Choix de PK : `INTEGER AUTOINCREMENT` (pas uuid) — donne un **ordre total monotone** gratuit, indispensable pour « le dernier event d'un crop » sans dépendre de la précision de `created_at` (deux events à la même seconde sont fréquents dans un run batch). `run_id` n'a **pas** de FK (il peut pointer soit `source_runs` soit `cohort_jobs`) — c'est volontaire, on garde un champ libre indexé.

`cohort_id` est **dénormalisé** sur l'event : un crop n'a pas de cohort_id natif (il faut remonter `image_assets → source_images.target_eurio_id → experiment_cohorts.eurio_ids_json` qui est un JSON array, donc pas joignable en SQL). Le dénormaliser à l'écriture rend les compteurs cohort triviaux. *Choix ouvert : si un eurio_id appartient à plusieurs cohortes, on perd l'info ; acceptable car le scoping cockpit se fait par eurio_id de toute façon.*

### 2.2 Alimentation : applicatif (helper) vs triggers — TRANCHÉ : applicatif

**Recommandation : écriture applicative via un helper unique `Store.emit_state_event(...)`, PAS de trigger SQLite.** Justification chiffrée et structurelle :

1. **La surface d'écriture est petite et déjà connue.** Grep exhaustif (vérifié) : les transitions partent de ~12 fonctions identifiables — `detect_crop.run_detect_crop`, `resolve.run_resolve`, `enqueue.run_enqueue`, `decide_review` (l.1620), `reject_review` (l.1817), `restore_rejected` (l.889), `skip_review` (l.2413), `run_auto_accept` (l.2664), ccproxy ack (l.3233/3258), `coin_assets_routes` (l.252/268), `recrop_zero_for_coin` (l.120-132). Instrumenter 12 call-sites avec un `emit_state_event(...)` est trivial et explicite.

2. **Les triggers ne voient pas le contexte métier.** Un trigger `AFTER UPDATE ON image_assets` saurait que `resolution_status` est passé à `manual`, mais **pas** qui (human vs auto_dino vs ccproxy), ni le `run_id`/`cohort_id`, ni la `reason`. Ces colonnes sont précisément l'exigence PO non négociable (« raison, acteur, run_id »). Un trigger devrait lire des variables de session inexistantes en SQLite → on retomberait sur des heuristiques, l'anti-pattern qu'on supprime.

3. **`review_queue` et `image_assets` sont écrits dans deux UPDATE séparés** (cf. `decide_review` l.1614-1648 : un UPDATE image_assets puis un UPDATE review_queue dans la même transaction). Un trigger par table émettrait DEUX events pour une seule décision logique. L'applicatif émet UN event au bon moment.

4. **Transaction unique.** `decide_review` ouvre déjà `BEGIN ... COMMIT` (l.1612-1655). On insère l'event **dans la même transaction** → atomicité event ⇔ mutation garantie, zéro drift possible. Un trigger garantirait l'atomicité mais perdrait le contexte (point 2).

Helper proposé (signature, à implémenter dans `store.py` à côté de `set_discovery_pipeline_state`) :

```python
def emit_state_event(conn, *, asset_id, to_state, actor, reason=None,
                     from_state=None, eurio_id=None, run_id=None,
                     cohort_id=None, detail=None) -> None:
    # 1. from_state auto-résolu depuis image_state_current si non fourni
    # 2. valide (from_state -> to_state) contre la table de transitions légales
    # 3. INSERT image_state_events (...)
    # 4. UPSERT image_state_current (cf. §3)  -- même transaction
```

Garde-fou : si `(from_state → to_state)` n'est pas dans le catalogue §1.2, le helper **logge un warning et écrit quand même** (on ne casse pas la prod pour un event illégal — on l'observe). *Choix ouvert : warn-and-write vs raise.* Je recommande warn-and-write en phase de rodage, puis raise une fois stabilisé.

### 2.3 Points d'instrumentation précis (12 call-sites)

| Fichier:ligne | Mutation existante | Event à émetter |
|---|---|---|
| `detect_crop.py:256` (upsert) | crée asset pending_match/auto_phash | `→ detected` / `→ auto_matched` (pipeline) |
| `resolve.py:95` | pending_match → needs_review | (pas d'event ici, attendre enqueue) |
| `enqueue.py:179` (INSERT rq) | needs_review → open | `detected → queued` (pipeline) |
| `enqueue.py:191` (UPDATE si) | pose route_decision | (agrégat listing, dérivé — pas d'event crop) |
| `review_queue_routes.py:1620` `decide_review` | → manual + rq done | `queued → resolved` (human) |
| `:1817` `reject_review` | → rejected | `queued → rejected` (human) |
| `:889` `restore_rejected` | rejected → needs_review | `rejected → queued` (human) |
| `:2413` `skip_review` | decision_notes=skipped | `queued → skipped` (human) |
| `:2664` `run_auto_accept` | → manual + done | `queued → resolved` (auto_dino) |
| `:3233/3258` ccproxy ack | → manual + done | `in_review → resolved` (ccproxy) |
| `coin_assets_routes.py:252/268` | needs_review + enqueue | `→ queued` (human) |
| `recrop_zero.py:120-132` | upsert + crop_status success | `→ detected`/`→ auto_matched` (recrop) + **fix T1** |

Le **fix T1** (recrop ne clôt pas la pipeline) consiste à appeler, juste après l'upsert dans `recrop_zero_for_coin`, le même `run_resolve`+`run_enqueue` (ou directement émettre `→ queued`) pour que les crops recroppés deviennent `queued` et non `orphaned`. C'est une correction de câblage, pas du modèle.

---

## 3. État courant pour les compteurs : table matérialisée vs vue dérivée

### 3.1 Comparatif

| Critère | Vue dérivée (dernier event) | Table matérialisée `image_state_current` |
|---|---|---|
| Fraîcheur | Toujours exacte (lit le journal) | Exacte si UPSERT dans la même txn |
| Perf compteur | `GROUP BY` sur sous-requête « dernier event/crop » → window function sur ~5k+ events, recalculé à chaque appel cockpit (poll 4s) | `GROUP BY current_state` sur 1 ligne/crop, index direct |
| Risque drift | Nul | Nul si UPSERT systématique dans le helper |
| Touche le coeur | Non | Non (table satellite, pas de colonne sur image_assets) |
| Rollback | DROP VIEW | DROP TABLE |

La vue dérivée « dernier event par crop » s'écrit :

```sql
CREATE VIEW v_image_state_current AS
SELECT e.asset_id, e.to_state AS current_state, e.eurio_id, e.cohort_id,
       e.actor, e.reason, e.created_at AS state_since
  FROM image_state_events e
  JOIN (SELECT asset_id, MAX(id) AS max_id
          FROM image_state_events GROUP BY asset_id) last
    ON last.asset_id = e.asset_id AND last.max_id = e.id;
```

C'est correct mais le cockpit poll toutes les 4s (`refetchInterval: 4000`, vérifié dans le handoff) et fait ~6 compteurs par pièce × 16 pièces. Recalculer la window-function à chaque tick est gaspilleur.

### 3.2 Recommandation : table matérialisée

```sql
-- État courant matérialisé : 1 ligne par crop, tenue à jour par emit_state_event
-- dans la même transaction que l'INSERT du journal. Source des compteurs cockpit.
CREATE TABLE IF NOT EXISTS image_state_current (
  asset_id      TEXT PRIMARY KEY
                REFERENCES image_assets(id) ON DELETE CASCADE,
  current_state TEXT NOT NULL
                CHECK (current_state IN (
                  'detected','auto_matched','queued','in_review',
                  'skipped','resolved','rejected','orphaned','superseded'
                )),
  eurio_id      TEXT,                       -- eurio_id courant (NULL tant que non résolu)
  cohort_id     TEXT,                       -- dénormalisé (cf. §2.1)
  last_event_id INTEGER REFERENCES image_state_events(id),
  actor         TEXT,                       -- acteur de la dernière transition
  state_since   TEXT NOT NULL DEFAULT (datetime('now'))  -- timestamp d'entrée dans l'état courant
);

CREATE INDEX IF NOT EXISTS idx_isc_cohort_state
  ON image_state_current(cohort_id, current_state);
CREATE INDEX IF NOT EXISTS idx_isc_state
  ON image_state_current(current_state);
```

`emit_state_event` fait, dans la même transaction : `INSERT image_state_events` puis `INSERT ... ON CONFLICT(asset_id) DO UPDATE SET current_state=..., last_event_id=..., state_since=...`. La table est une **projection garantie cohérente** du journal (le journal reste la source de vérité auditable ; la table est un cache transactionnel). En cas de doute, on peut toujours la reconstruire depuis le journal (`v_image_state_current` ci-dessus sert de vue de réconciliation/test).

### 3.3 Mapping compteur cockpit → SELECT

Remplace les heuristiques `_coin_tail` (`route_decision` gelé, cf. B4) et la dérivation temps-réel par des SELECT directs sur `image_state_current`. Scoping par `cohort_id` (dénormalisé) ou par `eurio_id`.

```sql
-- Compteur principal cockpit : ventilation par état, pour une cohorte
SELECT current_state, COUNT(*) AS n
  FROM image_state_current
 WHERE cohort_id = :cohort_id
 GROUP BY current_state;
```

| Libellé UI (cible, corrige B4) | SELECT |
|---|---|
| crops détectés | `current_state='detected'` |
| auto-matchés | `current_state='auto_matched'` |
| **en review (vivant)** | `current_state IN ('queued','in_review')` ← remplace `n_review_single+n_review_lot` gelé |
| skippés (à reprendre) | `current_state='skipped'` |
| résolus (training-ready) | `current_state='resolved'` |
| rejetés (récupérables) | `current_state='rejected'` |
| **orphelins (invisibles → visibles)** | `current_state='orphaned'` (les 544 pending_match sans rq) |

Pour conserver le découpage single/lot et par lane (cartes C4), on joint `review_queue` UNIQUEMENT pour les états `queued`/`in_review` (la lane reste portée par `review_queue`, c'est du routage, pas de l'état canonique) :

```sql
-- Cartes lane C4 (corrige B3) : décompte par lane des items réellement en file
SELECT rq.lane, rq.kind, COUNT(*) AS n
  FROM image_state_current c
  JOIN review_queue rq ON rq.image_asset_id = c.asset_id
 WHERE c.cohort_id = :cohort_id
   AND c.current_state IN ('queued','in_review')
 GROUP BY rq.lane, rq.kind;
```

Cela règle B3 : la « queue manuelle » affiche `lane='manual'` tous kinds (single + lot), au lieu de masquer les 4 lots manuels dans la carte fourre-tout « Lots ».

---

## 4. Table `cohort_jobs` (corrige B2 — observabilité)

Remplace le thread mémoire `_recrop_jobs` (`lab_routes.py:1730`, perdu au restart) par un état DB. Le scrape (`source_runs`) et le recrop y écrivent leur progression au fil de l'eau.

```sql
-- Jobs cohorte observables (scrape eBay, recrop-zero). Remplace le dict
-- in-memory _recrop_jobs (perdu au restart FastAPI). Le worker écrit sa
-- progression en autocommit → polling réel + survit aux restarts.
CREATE TABLE IF NOT EXISTS cohort_jobs (
  id            TEXT PRIMARY KEY,                    -- uuid hex
  kind          TEXT NOT NULL
                CHECK (kind IN ('scrape_ebay','recrop_zero','census_recover')),
  cohort_id     TEXT NOT NULL REFERENCES experiment_cohorts(id) ON DELETE CASCADE,
  eurio_id      TEXT,                                -- NULL = job cohorte entière
  target_eurio_id TEXT,                              -- B5 : pièce CIBLÉE par le scrape (cf. §5)
  run_id        TEXT,                                -- lien source_runs.id / image_assets.run_id
  status        TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','done','failed','skipped')),
  n_total       INTEGER,                             -- items dans le scope au lancement (barre de progression)
  n_done        INTEGER NOT NULL DEFAULT 0,          -- items traités (mis à jour au fil de l'eau)
  n_produced    INTEGER NOT NULL DEFAULT 0,          -- crops/listings produits
  n_attributed_target INTEGER NOT NULL DEFAULT 0,    -- B5 : combien attribués à target_eurio_id
  tau           REAL,                                -- seuil census utilisé (diagnostic "0 crop")
  started_at    TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at   TEXT,
  error         TEXT,
  note          TEXT                                 -- ex: "épuisé à tau=0.55, 0 crop possible"
);

CREATE INDEX IF NOT EXISTS idx_cohort_jobs_cohort
  ON cohort_jobs(cohort_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cohort_jobs_status
  ON cohort_jobs(status) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_cohort_jobs_target
  ON cohort_jobs(target_eurio_id);
```

Câblage (remplace `recrop_zero_coin._runner`) :
- **Au lancement** : `INSERT cohort_jobs(... status='running', n_total=<scope count>, tau=0.55)`.
- **Au fil de l'eau** : la boucle de `recrop_zero_for_coin` fait `UPDATE cohort_jobs SET n_done=n_done+1 WHERE id=?` tous les K items (autocommit, connexion dédiée déjà ouverte l.1740).
- **À la fin** : `UPDATE ... SET status='done', finished_at=..., n_produced=<crops>, note=<diag>`. Si `n_produced=0` : `note='épuisé à tau=0.55 — 0 crop récupérable'` → le bouton « Recropper N » peut afficher « tenté (0) » au lieu de re-proposer indéfiniment (corrige le **bouton zombie** B2).
- **Front** : poll `GET /cohorts/{id}/jobs` (liste depuis la table) au lieu de l'endpoint `/recrop-zero/status` mémoire.

Note transversale : le fix T1 (recrop câble resolve/enqueue) + cohort_jobs.note ensemble suppriment la double opacité B2 (« 0 crop sans trace » ET « job perdu au restart »).

---

## 5. B1 — Représenter honnêtement « scrapé pour be-2007 mais 0 attribué »

Le bug B1 n'est pas un bug d'algorithme (l'audit A2 le confirme : `eras_for_year` attribuerait correctement be-2007 si eBay renvoyait un listing 2007 ; il n'en a pas renvoyé). Le mensonge est **dans le modèle d'affichage** : `never_scraped = (n_source_images_for_eurio == 0)` confond « jamais cherché » et « cherché, 0 attribué ».

Le modèle corrige ça **sans toucher l'algo** via `cohort_jobs` :

- `cohort_jobs.target_eurio_id = 'be-2007-...'` : le job SAIT pour quelle pièce le scrape a été lancé (le run a tourné, c'est tracé).
- `cohort_jobs.n_attributed_target` : compté à la fin du job = `COUNT(source_images WHERE run_id=job.run_id AND target_eurio_id=job.target_eurio_id)` → vaut 0 pour be-2007.
- `cohort_jobs.n_produced` : 198 (listings BE produits par le groupe large).

Le cockpit calcule alors deux métriques distinctes (remplace `never_scraped`) :

```sql
-- A-t-on DÉJÀ lancé un scrape ciblant cette pièce (peu importe le résultat) ?
SELECT COUNT(*) AS group_scrape_count, MAX(started_at) AS last_scrape,
       SUM(n_attributed_target) AS total_attributed
  FROM cohort_jobs
 WHERE kind='scrape_ebay' AND target_eurio_id = :eurio_id;
```

| Cas | Affichage cockpit (honnête) |
|---|---|
| `group_scrape_count=0` | « jamais scrapé » (vrai) |
| `group_scrape_count≥1 AND total_attributed=0` | « 0 attribué (groupe scrapé N fois, dernier le …) » ← cas be-2007 |
| `total_attributed>0` | « N listings attribués » |

C'est l'Option A de l'audit A2, mais **portée par le modèle d'état** (la table `cohort_jobs` est la mémoire persistante du « on a cherché »), pas par une requête ad hoc sur `source_images`. Le badge rouge trompeur « jamais scrapé » disparaît pour be-2007.

---

## 6. Plan de migration idempotent

### 6.1 Pattern et garde-fous

Le repo n'utilise **pas** `user_version` (vérifié : `PRAGMA user_version = 0`). La migration suit le pattern `_bootstrap()` existant : `CREATE TABLE IF NOT EXISTS` dans `schema.sql` (rejoué à chaque démarrage, idempotent) + backfill one-shot gardé par sentinelle dans `store.py`.

**Ordre dans `schema.sql`** (après `review_queue`/`discovery_log`, avant les vues qui pourraient les référencer) :
1. `image_state_events`
2. `image_state_current`
3. `cohort_jobs`
4. indexes des 3.

Toutes en `IF NOT EXISTS` → rejouables sans erreur sur DB fraîche comme existante. **Aucun ALTER sur table coeur** → garde-fou R0 respecté.

### 6.2 Backfill (one-shot, gardé)

`image_state_current` et `image_state_events` doivent être **amorcés** depuis l'état actuel des ~1889 crops de la cohorte (et au-delà). Backfill = un seul event synthétique par crop (`from_state=NULL`, `actor='system'`, `reason='backfill'`) reconstruit via le mapping §1.1, + l'UPSERT correspondant dans `image_state_current`.

```sql
-- Pseudo-backfill (exécuté UNE fois, gardé par sentinelle)
-- to_state dérivé par CASE depuis l'existant :
INSERT INTO image_state_current(asset_id, current_state, eurio_id, cohort_id, state_since)
SELECT ia.id,
  CASE
    WHEN ia.resolution_status='rejected'                      THEN 'rejected'
    WHEN ia.resolution_status='manual' AND rq.status='done'   THEN 'resolved'
    WHEN ia.resolution_status IN ('auto_phash','auto_name')   THEN 'auto_matched'
    WHEN rq.status='open' AND rq.decision_notes='skipped'     THEN 'skipped'
    WHEN rq.status='in_progress'                              THEN 'in_review'
    WHEN rq.status='open'                                     THEN 'queued'
    WHEN ia.resolution_status='pending_match' AND rq.id IS NULL THEN 'orphaned'  -- les 544
    WHEN ia.resolution_status='needs_review' AND rq.id IS NULL THEN 'orphaned'
    ELSE 'detected'
  END AS current_state,
  ia.eurio_id,
  /* cohort_id résolu en Python depuis experiment_cohorts.eurio_ids_json
     (JSON array non joignable en pur SQL) */ NULL,
  COALESCE(ia.resolved_at, ia.fetched_at)
  FROM image_assets ia
  LEFT JOIN review_queue rq ON rq.image_asset_id = ia.id;
```

**Garde-fou sentinelle** : le backfill ne tourne que si `image_state_current` est vide pour les crops concernés — `WHERE NOT EXISTS (SELECT 1 FROM image_state_current isc WHERE isc.asset_id=ia.id)`. Idempotent : un 2e démarrage ne re-backfille pas. Le `cohort_id` est rempli en Python (lecture `experiment_cohorts.eurio_ids_json` → map eurio_id→cohort_id) car le JSON array n'est pas joignable en SQL pur — cohérent avec la façon dont le cockpit scope déjà les cohortes.

`cohort_jobs` : **pas de backfill** (les jobs passés du thread mémoire sont perdus de toute façon — on démarre le journal des jobs à neuf, c'est acceptable).

### 6.3 Additif vs backfill — synthèse

| Objet | Additif (schema.sql) | Backfill requis | Sentinelle |
|---|---|---|---|
| `image_state_events` | oui (IF NOT EXISTS) | oui (1 event synthétique/crop) | `NOT EXISTS` sur asset_id |
| `image_state_current` | oui | oui (CASE depuis existant) | table/ligne absente |
| `cohort_jobs` | oui | non | n/a |
| instrumentation 12 call-sites | code (emit_state_event) | non | n/a |

Ordre d'exécution global : (1) schema.sql crée les tables → (2) backfill gardé amorce events+current → (3) déploiement du code instrumenté (les 12 call-sites + le helper). Étapes 1-2 sont sûres même sans 3 (les tables existent, peuplées, juste plus alimentées). Étape 3 sans 1-2 planterait (FK) → respecter l'ordre.

---

## 7. Arbitrages ouverts à valider par le PO

1. **Table satellite `image_state_current` vs colonne `current_state` sur `image_assets`** → je recommande satellite (coeur intact, rollback = DROP). Le PO peut préférer la colonne pour éviter un JOIN.
2. **Applicatif vs trigger** → tranché applicatif (contexte métier indispensable, surface bornée). Soumis pour validation formelle.
3. **`move_lane` journalisé ou non** → je penche pour oui (audit complet) avec `from_state=to_state`.
4. **Helper warn-and-write vs raise sur transition illégale** → warn pendant le rodage, raise après stabilisation.
5. **Granularité `cohort_id` dénormalisé** si un eurio_id est dans plusieurs cohortes (perte d'info théorique, acceptable car scoping par eurio_id).
6. **`n_done` tous les K items vs chaque item** dans cohort_jobs (compromis perf write / fraîcheur barre de progression) — proposé K=10.


---


# [UX] Redesign UX du cockpit cohorte /lab/cohorts/&lt;id&gt; — proposition pour arbitrage

**Resume.** Le cockpit actuel est illisible parce qu'il affiche trois sous-machines d'état non réconciliées (route_decision figé de source_images, resolution_status de image_assets, status de review_queue) avec un vocabulaire cryptique ("pending", "DL", "review"), des compteurs trompeurs (677 "en review" gelés vs 1163 vivants ; 1907 "pending" qui sont en fait des listings non téléchargés), et des boutons sans hiérarchie ni grammaire cohérente. Je propose un cockpit organisé autour du modèle d'état canonique du crop (9 états) : un en-tête avec le flow 10 étapes en frise, une ligne-exemple annotée (légende) ouverte par défaut, et une row par pièce où CHAQUE chiffre est mappé à un champ persisté (image_state_current.current_state, cohort_jobs) et où une SEULE action primaire est exposée selon l'état (jamais scrapé→Scraper ; crops à 0→Recropper ; en review→Reviewer ; assez→rien). Les jobs scrape/recrop s'affichent en barre de progression DANS la row (n_done/n_total lus depuis cohort_jobs), supprimant le badge run-live global. Toutes les données sont confirmées contre eurio.db en lecture seule : be-2007 a réellement 0 listing (scrape parti vers be-2014=40), fi-2016 a 13 résolus/129 en review/9 rejetés, 544 crops orphelins invisibles, 39 crops "manual" surcomptés car training_eligible=0. Le livrable inclut maquettes ASCII, grammaire d'actions, tableau de vocabulaire ancien→nouveau, et découpe en 6 chunks front auditables avec mapping précis vers CohortDrawerEbay.vue / CohortDrawerCrop.vue / CohortDetailPage.vue. C'est une proposition d'arbitrage ; l'implémentation passera par le skill frontend-design.


**Takeaways**

- Le cockpit doit s'ancrer sur l'état canonique du crop (image_state_current.current_state) : remplacer immédiatement les chiffres figés route_decision par les chiffres vivants (queued+in_review pour 'en review', training_eligible=1 pour 'résolus'). Vérifié : 677 'en review' figé vs 1163 vivant ; 145 'manual' vs 106 réellement training-ready.
- Grammaire d'actions invariante : exactement 0 ou 1 bouton primaire (plein) par row, déterminé par un arbre de priorité (review>recrop>scrape>rien). Les secondaires sont visuellement subordonnés quel que soit l'état. Règle le grief 'boutons qui se mélangent'.
- Le 'pending=1907' du ruban n'est PAS une file de review : c'est route_decision='pending' (listings non téléchargés/routés). Le renommer 'non routés' ou le retirer du ruban. Confirmé en DB.
- Rendre visibles les 544 crops orphelins (pending_match sans review_queue) via l'état 'jamais croppés'/orphaned — aujourd'hui invisibles à toute vue, ce qui fausse tous les totaux.
- Les jobs (scrape/recrop) doivent s'afficher en barre de progression DANS la row de la pièce (lue depuis cohort_jobs, n_done/n_total), pas en badge global en haut. Supprime le bouton recrop zombie via cohort_jobs.note ('tenté, 0 récupérable').
- B1 (be-2007 : 0 source_images, scrape parti vers be-2014=40) doit être affiché '0 attribué (groupe scrapé Nx)' et non 'jamais scrapé' — exige cohort_jobs.total_attributed côté back.
- Découpe front en 6 chunks : F1 (vocabulaire+chiffres vivants) + F2 (grammaire actions) + F6 (lanes honnêtes) sont livrables SANS toucher au back et corrigent déjà B3/B4 d'affichage. F5 (jobs in-row) attend la table cohort_jobs.
- Arbitrages PO ouverts : la frise flow remplace-t-elle le ruban actuel ? ; pour le cas '0 attribué' (be-2007), l'action primaire devrait-elle être 'assigner depuis la file lot' (29 listings NULL déjà en review) plutôt que 'Rescraper le groupe' qui re-disperse vers les sœurs ?


# Cockpit cohorte — proposition de redesign (phase analyse, lecture seule)

> Périmètre : `admin/packages/web/src/features/lab/pages/CohortDetailPage.vue`, `components/CohortDrawerEbay.vue` (§C3), `components/CohortDrawerCrop.vue` (§C4). Tout chiffre proposé est mappé à un champ persisté du **modèle d'état** (`image_state_current.current_state`, `cohort_jobs.*`) — **aucune heuristique temps-réel**. Données vérifiées contre `eurio.db` (cohort `b0299ca0252b` = mix-zone-17, 16 pièces).

---

## 0. Diagnostic : pourquoi le cockpit actuel est illisible

J'ai tracé chaque chiffre du cockpit jusqu'à sa requête. Le problème de fond n'est pas cosmétique : **le cockpit affiche trois sous-machines d'état qui ne parlent pas de la même chose, sans le dire.**

| Chiffre affiché | Lu depuis | Ce que ça veut VRAIMENT dire | Mensonge |
|---|---|---|---|
| « 677 en review » (ruban) | `route_decision IN (review_single, review_lot)` (`source_images`, figé à l'enqueue) | intention de routage au moment du scrape | **gelé** : ne bouge pas quand on tranche. Vrai vivant = `1163` (rq.status='open') |
| « 1 907 pending » (ruban) | `route_decision='pending'` (vérifié : 1907) | listings **pas encore téléchargés/routés** | « pending » suggère « en attente de review ». Faux sens total |
| « → 251 DL » (phrase) | `download_status='success'` | téléchargés | placé APRÈS review dans la flèche alors que download est AVANT crop |
| « manuelle = 3 » (carte I) | `lane='manual' AND status='done'`… en fait 3 done / 512 open | file manuelle | exclut silencieusement 4 lots en `lane='manual'`, et confond done/open |
| « Recropper N » | `n_zero_crops` (raws sans crop) | candidats recrop | re-proposé à l'infini même si le job précédent a rendu 0 (bouton zombie B2) |
| badge run-live (haut du tiroir) | `/sources/ebay/runs?status=running` | un run tourne | en haut, déconnecté de la pièce concernée |

**Vérifié en DB (cohort mix-zone-17) :**
- `resolution_status` global : `needs_review=2496`, `pending_match=544`, `manual=145`, `rejected=70`, `auto_phash=15`.
- **544 crops orphelins** (`pending_match` sans `review_queue`) — invisibles à toute vue actuelle.
- `manual` : `106` avec `training_eligible=1` (vrais résolus training-ready) + **39 avec `training_eligible=0`** → surcomptés comme « validés » par le cockpit.
- `be-2007-2eur-standard…` : **0 source_images** (le scrape `8a29…` est parti vers les sœurs : `be-2014=40`, `be-1999=11`, NULL=29…). C'est le cas B1.
- `fi-2016-…von-wright` : `13 manual` + `129 needs_review` + `9 rejected` → c'est la pièce « bloquée » de l'audit.

Conclusion : **on ne corrige pas en renommant des labels, on réorganise autour de l'état canonique du crop.** Le modèle d'état proposé (9 états + `cohort_jobs`) donne exactement les champs dont l'UI a besoin.

---

## 1. En-tête de page cohorte — le flow 10 étapes en frise

Le PO veut le flow **écrit en tête**. Je le rends comme une frise horizontale d'étapes, chacune avec un **statut dérivé d'un compteur d'état persisté**. La frise est le contrat de lecture du reste de la page : chaque tiroir plus bas est un zoom sur une étape.

Trois familles d'étapes, distinguées visuellement (le PO doit comprendre d'un coup d'œil ce qui est manuel / hold-out / auto) :
- **Capture (hold-out)** = étapes 1-2 : pièces réelles → bench. Jamais du training. Liseré distinct.
- **Sourcing & crop (auto + review)** = étapes 3-8 : eBay → training-eligible.
- **Entraînement** = étapes 9-10 : enrichissement + run.

```
┌─ FLOW COHORTE ─ comment une pièce passe de la sélection au benchmark ───────────────────────────┐
│                                                                                                  │
│  CAPTURE (hold-out, jamais training)        SOURCING + CROP eBay (auto + review humaine)         │
│  ┌────────┐  ┌────────┐   ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐ │
│  │ 1      │  │ 2      │   │ 3      │  │ 4      │  │ 5      │  │ 6      │  │ 7      │  │ 8      │ │
│  │Sélec-  │→ │Capture │ → │Scrape  │→ │Télé-   │→ │Crop    │→ │Theme   │→ │Tri     │→ │Valider │ │
│  │tion    │  │device  │   │eBay    │  │charge- │  │auto    │  │matcher │  │lanes   │  │→train- │ │
│  │16 pcs  │  │photos  │   │groupe  │  │ment    │  │(ratés  │  │→eurio  │  │auto/cc/│  │elig.   │ │
│  │        │  │réelles │   │        │  │        │  │→review)│  │_id     │  │manuel  │  │        │ │
│  │ ✓ 16/16│  │ ⚠ 9/16 │   │ ✓ 14/16│  │ ✓ 2.6k │  │ ◐ 1.1k │  │ ◐      │  │ ◐ 1.2k │  │ ◐ 106  │ │
│  └────────┘  └────────┘   └────────┘  └────────┘  └────────┘  └────────┘  └────────┘  └────────┘ │
│                                                                            ENTRAÎNEMENT           │
│                                                                          ┌────────┐  ┌────────┐  │
│                                                                          │ 9      │  │ 10     │  │
│                                                                       →  │Enrichir│→ │Run     │  │
│                                                                          │≥100/cl │  │ArcFace │  │
│                                                                          │(×fact.)│  │vs device│ │
│                                                                          │ ⚠ 14   │  │ — 0    │  │
│                                                                          └────────┘  └────────┘  │
│  Légende statut :  ✓ complet   ◐ en cours   ⚠ attention/gap   — pas démarré   ⏳ job en cours      │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Mapping de chaque statut d'étape à un compteur d'état (pas d'heuristique) :**

| Étape | Statut dérivé de | Règle ✓/◐/⚠/— |
|---|---|---|
| 1 Sélection | `experiment_cohorts.eurio_ids_json` len | toujours ✓ si cohort existe |
| 2 Capture device | `cohort_progress.c2` (déjà existant) | ✓ si `fully_captured==total`, ⚠ sinon (ici 9/16) |
| 3 Scrape eBay | `cohort_jobs` kind=scrape_ebay par `target_eurio_id` distinct | ✓ = N pièces ayant ≥1 job ; ⚠ si pièce scrapable sans job |
| 4 Téléchargement | Σ `source_images.download_status='success'` | ✓ si `download_failed==0` |
| 5 Crop auto | Σ `current_state IN (detected, auto_matched, queued…)` | ◐ tant que des `detected`/`orphaned` restent |
| 6 Theme matcher | Σ crops avec `eurio_id` posé (state ≠ detected/orphaned) | ◐ |
| 7 Tri lanes | Σ `current_state IN (queued, in_review)` par lane | ◐ tant que >0 |
| 8 Valider | Σ `current_state='resolved' AND training_eligible=1` | compteur = 106 (pas 145) |
| 9 Enrichir | Σ pièces `n_seed >= min_real_sources` | ⚠ = nb pièces sous plancher (=14) |
| 10 Run | `iterations` de la cohort | — si aucune itération |

> Note design : la frise **prend de la place** (le PO le demande explicitement) — c'est l'élément le plus haut et le plus large, pas un ruban tassé. Les chiffres y sont indicatifs (santé globale) ; le détail actionnable est dans les rows.

---

## 2. La LIGNE-EXEMPLE annotée (légende, ouverte par défaut)

Avant la première vraie row, une **row fictive figée** avec des callouts. C'est la pièce maîtresse : elle explique chaque chiffre et chaque bouton une fois pour toutes. Elle ne disparaît pas (ou repliable mais ouverte par défaut au premier chargement).

```
┌─ COMMENT LIRE UNE LIGNE ─ (exemple, données fictives) ─────────────────────────────────────────┐
│                                                                                                  │
│  xx-2099-2eur-exemple                                              [142 réels] ████████░░ ≥100 ✓│
│  ╰─┬──────────────╯                                                ╰──┬─────╯ ╰───┬───╯ ╰─┬─╯   │
│    │ ① eurio_id : identité catalogue de la pièce.                     │           │      │      │
│    │                                            ⑨ sources réelles ────╯           │      │      │
│    │                                               distinctes (crops eBay validés │      │      │
│    │                                               + avers Numista + réf BCE).     │      │      │
│    │                                            ⑩ jauge enrichissement ───────────╯      │      │
│    │                                               (réels × facteur aug → cible 100).     │      │
│    │                                            ⑪ « ≥100 ✓ » = assez : rien à faire ──────╯      │
│    │                                                                                              │
│  ②185 trouvés eBay → ③160 téléchargés → ④120 crops auto → ⑤14 auto-matchés · ⑥38 en review ·    │
│   ╰──┬──────────╯     ╰────┬──────────╯    ╰───┬───────╯     ╰────┬─────╯      ╰───┬────╯         │
│      │ listings retenus    │ images vraiment   │ crops produits   │ matchés     │ crops qui      │
│      │ (attribués à cette  │ rapatriées        │ par l'autocrop   │ sans humain │ attendent une  │
│      │ pièce sur eBay)     │ (download OK)     │ (≠ recropper)    │ (phash)     │ décision       │
│                                                                                                  │
│   ⑦52 résolus (training) · ⑧3 rejetés · ⓪6 jamais croppés                                        │
│    ╰────┬─────────────╯     ╰──┬────╯     ╰────┬──────╯                                           │
│         │ tranchés → eurio_id  │ écartés      │ raws téléchargés SANS crop → bouton « Recropper »│
│         │ posé, comptent       │ (récupé-                                                         │
│         │ pour le training      │ rables)                                                          │
│                                                                                                  │
│  ⏵ ACTIONS :   [▸ Reviewer 38]   ( Recropper 6 )   ( Rescraper )   filtres↗  crops↗              │
│                 ╰──┬─────────╯     ╰─────┬─────╯     ╰────┬────╯                                  │
│                    │ PRIMAIRE (pleine    │ secondaire    │ secondaire (consomme quota eBay)       │
│                    │ couleur) = la seule │ (en retrait)  │                                        │
│                    │ chose à faire main- │               │                                        │
│                    │ tenant pour avancer │               │                                        │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Table de la légende (chaque callout → champ d'état canonique) :**

| # | Libellé | Source d'état (modèle proposé) | Ancien champ (à retirer) |
|---|---|---|---|
| ① | eurio_id | `image_state_current.eurio_id` / cohort membre | — |
| ② | trouvés eBay | `cohort_jobs.n_produced` / `COUNT(source_images target=…)` | `n_source_images` |
| ③ | téléchargés | `source_images.download_status='success'` | `n_downloaded` |
| ④ | crops auto | `COUNT(image_state_current state ≠ orphaned)` | `n_crops` |
| ⑤ | auto-matchés | `current_state='auto_matched'` | partiel dans `n_auto` |
| ⑥ | en review | `current_state IN (queued, in_review)` | `n_review_single+lot` (figé) ❌ |
| ⑦ | résolus (training) | `current_state='resolved' AND training_eligible=1` | `resolution_status='manual'` (surcompte) |
| ⑧ | rejetés | `current_state='rejected'` | `n_rejected` |
| ⓪ | jamais croppés | `current_state='orphaned'` OU `n_zero_crops` | invisible aujourd'hui |
| ⑨ | sources réelles | `n_seed` | `n_seed` (gardé) |
| ⑩ | jauge | `n_projected` / `training_target` | gardé |
| ⑪ | assez ✓ | `n_seed >= min_real_sources` | `enough` (gardé) |

---

## 3. Anatomie d'une row pièce + grammaire d'actions

### 3.1 Structure de la row (3 bandes)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ BANDE 1 — identité + santé enrichissement                                             │
│   eurio_id  [badge état-pièce]                          [N réels] ▓▓▓▓░ proj/cible  ✓/⚠│
│                                                                                         │
│ BANDE 2 — funnel d'état (phrase lue de gauche à droite, ordre = pipeline)              │
│   ②→③→④  puis  ⑤ · ⑥ · ⑦ · ⑧ · ⓪   (chaque segment cliquable → grid filtrée)         │
│                                                                                         │
│ BANDE 3 — actions (1 primaire pleine + secondaires en retrait + audit liens)          │
│   [▸ ACTION PRIMAIRE]   ( secondaire )   ( secondaire )        filtres↗  crops↗        │
│   └ OU barre de progression si un job tourne (cf. §4)                                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Badge d'état-pièce (un seul, dérivé du compteur dominant)

Au lieu du badge `never_scraped` seul (qui ment pour be-2007), un badge unique qui résume l'état de la pièce :

| Badge | Condition (état canonique) | Couleur |
|---|---|---|
| `jamais scrapé` | aucun `cohort_jobs` kind=scrape_ebay AND `n_source_images=0` | rouge |
| `0 attribué` | `cohort_jobs` scrape ≥1 mais `total_attributed=0` (cas be-2007) | orange |
| `Numista-only` | `scrapable=false` | gris |
| `à reviewer` | `current_state IN (queued,in_review) > 0` | indigo |
| `prêt` | `n_seed >= min_real_sources` AND review==0 | vert |
| `à enrichir` | `n_seed < min_real_sources` AND review==0 | orange |

### 3.3 Grammaire d'actions — UNE primaire par état, cohérente

Règle invariante (le PO veut « 1 action primaire claire par pièce selon l'état ») : on calcule l'état dominant de la pièce et on en déduit **une seule** action primaire (bouton plein couleur). Le reste passe en secondaire (contour discret) ou disparaît.

**Arbre de décision de l'action primaire (ordre de priorité strict) :**

```
si current_state(queued|in_review) > 0          → PRIMAIRE = [▸ Reviewer N]
sinon si orphaned > 0 OU n_zero_crops > 0        → PRIMAIRE = [▸ Recropper N]
sinon si n_seed < min_real_sources AND scrapable → PRIMAIRE = [▸ Scraper] / [▸ Rescraper]
sinon si n_seed >= min_real_sources              → PRIMAIRE = (aucune) « prêt ✓ »
sinon (Numista-only, rien à faire)               → PRIMAIRE = (aucune) « hors eBay »
```

| État pièce | Action PRIMAIRE (pleine) | Secondaires (retrait) | Jamais affiché |
|---|---|---|---|
| crops en review | `▸ Reviewer N` (scopé eurio_id) | `Recropper`, `Rescraper`, lots, audit | « Scraper » comme primaire |
| crops à 0 / orphelins | `▸ Recropper N` | `Rescraper`, audit | « Reviewer 0 » |
| sous plancher, scrapable | `▸ Scraper` (jamais scrapé) / `▸ Rescraper` | audit | « Reviewer 0 » |
| 0 attribué (be-2007) | `▸ Rescraper (groupe)` + note « groupe scrapé N× » | audit | « jamais scrapé » trompeur |
| assez | aucune — pastille `prêt ✓` | audit | tout bouton d'action |
| Numista-only | aucune — pastille `hors eBay` | — | scrape/recrop/review |

**Cohérence visuelle (3 tons seulement) :**
- **Primaire** = fond indigo plein, texte blanc, icône pleine. Une par row max.
- **Secondaire** = contour `surface-3`, texte `ink-500`. `Rescraper` porte une pastille « quota » car il consomme l'API eBay (distinction gratuit/payant).
- **Audit** = liens texte discrets (`filtres↗`, `crops↗`), poids minimal.

Cela règle le grief « boutons qui se mélangent selon l'état » : il y a **toujours** au plus une action pleine, et les secondaires sont visuellement subordonnés quel que soit l'état.

---

## 4. Jobs observables DANS la row (cohort_jobs, pas badge global)

Le badge run-live global (haut du tiroir) disparaît. Quand un `cohort_jobs` est `running` pour une pièce, la **bande 3 de SA row** se transforme en barre de progression. Polling `GET /cohorts/{id}/jobs` (table, survit au restart — corrige B2).

```
┌─ Row avec scrape en cours ──────────────────────────────────────────────────┐
│ fr-2016-…mitterrand   [à reviewer]                  [3 réels] ▓░░░░ 100  ⚠   │
│ 307 trouvés → 307 téléchargés → 175 crops · 0 auto · 122 en review · 3 résolus│
│ ⏳ Scrape eBay   ▓▓▓▓▓▓▓▓▓░░░░░░  62 / 100   (job 9f3a · démarré il y a 40s)  │
└──────────────────────────────────────────────────────────────────────────────┘

┌─ Row avec recrop terminé à 0 (corrige le bouton zombie) ─────────────────────┐
│ de-2007-…mecklenburg  [à reviewer]                  [0 réels] ░░░░░ 100  ⚠   │
│ 93 trouvés → 93 téléchargés → 82 crops · 1 auto · 68 en review · 0 résolus    │
│ [▸ Reviewer 68]   ( Recropper — tenté, 0 récupérable à τ=0.55 )   filtres↗   │
│                     └ grisé : cohort_jobs.note dit « épuisé », plus zombie    │
└──────────────────────────────────────────────────────────────────────────────┘
```

Mapping barre → `cohort_jobs` :
- largeur = `n_done / n_total`.
- libellé = `kind` humanisé (`Scrape eBay` / `Recrop`) + `id[:6]` + ago(`started_at`).
- à `status='done'` AND `n_produced=0` : le bouton primaire correspondant passe en **secondaire grisé** avec `note` (« tenté, 0 récupérable à τ=0.55 ») — fini le bouton qui re-propose l'impossible.

---

## 5. Vocabulaire : ancien libellé → nouveau libellé + définition

| Ancien (cockpit actuel) | Nouveau | Définition affichée | Source d'état |
|---|---|---|---|
| « 677 en review » | **en review** (vivant) | crops qui attendent une décision humaine ou LLM | `current_state IN (queued,in_review)` |
| « 1 907 pending » | **non routés** (ou retirer du ruban) | listings pas encore téléchargés/routés — PAS une file review | `route_decision='pending'` (1907 confirmé) |
| « DL » | **téléchargés** | images rapatriées (download OK) | `download_status='success'` |
| « N review » (figé) | **en review** | idem, mais file vivante | `queued+in_review` (pas `route_decision`) |
| « crops » (ambigu) | **crops auto** | crops produits par l'autocrop | `COUNT(state ≠ orphaned)` |
| (recropper = crops ?) | **Recropper** | re-détecter des crops sur des raws qui n'en ont aucun (≠ « crops », ≠ « rescraper ») | `orphaned` / `n_zero_crops` |
| « Rescraper » | **Rescraper** (pastille quota) | chercher de NOUVELLES annonces eBay (consomme quota) | `cohort_jobs scrape` |
| « manuelle = 3 » | **à trancher (manuel) : N** | crops en lane manuelle réellement ouverts | `lane='manual' AND state IN(queued,in_review)` |
| « validés » (=manual) | **résolus (training)** | tranchés ET éligibles training | `state='resolved' AND training_eligible=1` (106, pas 145) |
| (invisible) | **jamais croppés** | raws téléchargés sans aucun crop | `orphaned` (544 globaux) |
| « jamais scrapé » (be-2007) | **0 attribué** | groupe scrapé N× mais 0 listing pour cette pièce | `cohort_jobs.total_attributed=0` |
| badge run-live global | (supprimé) | remplacé par barre dans la row | `cohort_jobs.status='running'` |

---

## 6. Maquettes ASCII — 3 rows d'états réels (données DB confirmées)

### 6.1 Row « jamais scrapé / 0 attribué » (be-2007 — B1, vérifié 0 source_images)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ be-2007-2eur-standard-albert-ii…  [0 attribué]      [1 réel*] ░░░░░ 100  ⚠     │
│ Aucun listing attribué — groupe BE scrapé 1× (run 8a29…, 29 listings sont      │
│ partis en review sur d'autres millésimes BE).                                  │
│ [▸ Rescraper (groupe BE)]                          filtres↗                    │
│   └ note honnête : « scrapé, 0 attribué » au lieu du faux « jamais scrapé »    │
└──────────────────────────────────────────────────────────────────────────────┘
*1 réel = avers Numista seul (n_numista_ref).
```

### 6.2 Row « en review » (fi-2016 — vérifié 13 résolus / 129 review / 9 rejetés)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ fi-2016-…georg-henrik-von-wright  [à reviewer]      [13 réels] ▓▓▓▓▓ 100  ✓    │
│ 251 trouvés → 251 téléchargés → 201 crops · 0 auto · 129 en review ·           │
│   13 résolus · 9 rejetés                                                       │
│ [▸ Reviewer 129]   ( Rescraper )                   filtres↗  crops↗            │
│   └ PRIMAIRE = trancher la file vivante (≠ ancien « 58 review » figé/faux)     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Row « complète » (pièce sous plancher mais review vidée → enrichir, ou prête)

```
┌─ pièce prête (assez de réels, review vidée) ─────────────────────────────────┐
│ at-2005-…austrian-state-treaty   [prêt]             [34 réels] ▓▓▓▓▓ 100  ✓    │
│ 326 trouvés → 321 téléchargés → 394 crops · 5 auto · 169 en review · 34 résolus│
│   · 16 rejetés                                                                  │
│ [▸ Reviewer 169]   ( Rescraper )                   filtres↗  crops↗            │
│   └ même si « prêt » côté seed, 169 crops restent en review → primaire=Reviewer│
└──────────────────────────────────────────────────────────────────────────────┘

┌─ pièce vraiment terminée (review==0, seed≥plancher) ─────────────────────────┐
│ xx-exemple-terminé               [prêt ✓]           [40 réels] ▓▓▓▓▓ 100  ✓    │
│ 200 trouvés → 200 téléchargés → 150 crops · 12 auto · 0 en review · 138 résolus│
│ (aucune action — prêt pour l'entraînement)         filtres↗  crops↗            │
│   └ AUCUN bouton plein : l'absence d'action est elle-même l'information        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6.4 Ruban C4 (lanes) refondu — corrige B3 (lots manuels masqués)

```
┌─ TRI LANES (étape 7) ─ où atterrissent les crops en review ──────────────────┐
│  ┌── Manuel ──┐  ┌─ Auto-accept ┐  ┌── CCProxy ──┐  ┌──── Lots ────┐          │
│  │  512       │  │   98         │  │  1 873      │  │  1 934       │          │
│  │ singles à  │  │ prêts à      │  │ cas ambigus │  │ multi-pièces │          │
│  │ trancher   │  │ valider      │  │ (LLM)       │  │ (flow lot)   │          │
│  │ + 0 lots   │  │              │  │             │  │ dont manuel:0│          │
│  └────────────┘  └──────────────┘  └─────────────┘  └──────────────┘          │
│  ↻ 70 rejetés à récupérer    ⏭ 30 skippés (reviennent dans la file)           │
└──────────────────────────────────────────────────────────────────────────────┘
```
> Chiffres `lane × status` vérifiés : manual{done:3,open:512}, auto_accept{done:54,open:98,skip:14}, ccproxy{done:158,open:1873,skip:1}. La carte Manuel affiche explicitement « + N lots » (transparence B3) et chaque carte n'affiche QUE l'open (file vivante), pas le done.

---

## 7. Mapping vers les fichiers front + découpe en chunks auditables

### 7.1 Quoi garder / quoi refondre

| Fichier | Garder | Refondre | Supprimer |
|---|---|---|---|
| `pages/CohortDetailPage.vue` | header cohort, trajectoire, table itérations, sensibilité | insérer la **frise flow 10 étapes** en tête (nouveau composant) | rien |
| `components/CohortDrawerEbay.vue` | `DrawerSection` wrapper, deep-links bench (`benchLink`), bloc Découverte, dédup, rescue | ruban (vocabulaire), `totals.review`→vivant, phrase funnel par coin, grammaire d'actions, badge pièce | badge run-live global (→ barre dans row), `never_scraped` seul, `n_review_single+lot` dans la phrase |
| `components/CohortDrawerCrop.vue` | cartes lanes, recover-strip, hint | cartes = file vivante uniquement, « + N lots » sur Manuel | « manuelle=3 » confus |
| `composables/useLabQueries.ts` | queries existantes | ajouter `useCohortJobsQuery` (poll table), retirer poll `/recrop-zero/status` mémoire | — |
| `types.ts` | tout | ajouter `CohortJob`, `current_state` enum ; déprécier `n_review_single/lot` dans la phrase | — |

> Côté back (hors périmètre édition ici, mais prérequis) : `_coin_tail` doit exposer la ventilation par `current_state` (lue depuis `image_state_current`) et `cohort_jobs`. Tant que le modèle d'état n'est pas câblé, le front peut **déjà** basculer sur les champs vivants existants (`n_open_review_single/lot`, `training_eligible=1`) — c'est le chunk 1.

### 7.2 Découpe en 6 chunks front (chacun auditable séparément, 30 min–3 h)

| Chunk | Contenu | Dépend de | Auditable par |
|---|---|---|---|
| **F1 — Vérité immédiate (sans back)** | Phrase funnel par coin → `n_open_review_single/lot` (vivant) ; « validés » → `training_eligible=1` ; renommer « pending »→« non routés », « DL »→« téléchargés », réordonner. Vocabulaire §5. | rien (champs déjà exposés) | comparer un chiffre du cockpit vs SQL `current_state` |
| **F2 — Grammaire d'actions** | Arbre §3.3 : une primaire pleine par row, secondaires en retrait, ton cohérent, pastille quota sur Rescraper. Badge pièce unique §3.2. | F1 | inspecter les 16 rows : exactement 0 ou 1 bouton plein chacune |
| **F3 — Frise flow 10 étapes** | Nouveau composant `CohortFlowHeader.vue` dans `CohortDetailPage.vue`, statuts dérivés §1. | F1 | chaque étape ✓/◐/⚠ correspond au compteur SQL |
| **F4 — Ligne-exemple annotée** | Composant `CohortRowLegend.vue` (statique, callouts §2), ouvert par défaut, repliable. | F2 | revue visuelle : chaque ⃝ pointe le bon chiffre |
| **F5 — Jobs dans la row (cohort_jobs)** | `useCohortJobsQuery` + barre de progression in-row §4, suppression badge global, bouton recrop grisé sur `note`. | back `cohort_jobs` + `GET /jobs` | lancer un scrape → barre dans la bonne row, survit au refresh |
| **F6 — Lanes honnêtes (C4)** | Cartes = open seul, « + N lots » sur Manuel, recover-strip. | F1 | `lane × status` du cockpit == SQL |

**Ordre conseillé** : F1 → F2 → F4 (légende dépend de la grammaire stabilisée) → F3 (frise) → F6 (lanes) → F5 (jobs, dépend du back). F1+F2+F6 sont livrables **sans toucher au back** (corrige déjà B3/B4 d'affichage). F5 attend `cohort_jobs` (corrige B2). B1 est traité honnêtement par le badge « 0 attribué » dès que `cohort_jobs.total_attributed` existe (sinon fallback `n_source_images=0 AND scrapable` = « jamais scrapé » strict).

### 7.3 Arbitrages front à trancher par le PO

1. **Frise = composant séparé** (`CohortFlowHeader.vue`) vs inline dans la page : je recommande séparé (testable, réutilisable iteration). 
2. **Ligne-exemple toujours visible** vs repliable mémorisée (localStorage) : je recommande repliable, ouverte au 1er chargement de chaque cohort.
3. **Ruban cohort-level** : le garder en plus de la frise, ou la frise le remplace ? Je recommande **frise remplace le ruban** (le ruban actuel est la principale source de chiffres cryptiques).
4. **`Rescraper` pour le cas « 0 attribué » (be-2007)** : rescraper le groupe risque de re-disperser vers les sœurs. Proposer plutôt « assigner manuellement depuis la file lot » comme action primaire ? À trancher avec l'audit A2 (les 29 listings NULL sont déjà en review et assignables).


---
