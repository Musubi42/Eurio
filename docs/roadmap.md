# Eurio — Roadmap J1→J7

> **À quoi sert ce doc** : reprendre une session froide en 5 min. Photo de la trajectoire vers le premier modèle ArcFace utile et son déploiement Android, dans le bon ordre, avec les dépendances explicites.
>
> **Dernière mise à jour** : 2026-05-28 (re-séquencement crop / découplage scrape↔crop)
>
> **Pour l'historique des phases ML/data antérieures** : voir `docs/phases/` et `docs/archive/`.
> **Pour la doc app Android** : voir `docs/app-implem-phases/`.

---

## TL;DR

L'infrastructure data + scrape + matching est en place. Il reste à passer en cadence routine sur le scrape eBay, **accumuler des images** sur les 510/614 classes encore à vide, **entraîner** ArcFace sur la masse résultante (Numista canon augmenté + wild eBay+autres), et **bench** sur les cohortes capture physiques.

Le dashboard `/operations` est le tableau de bord qui orchestre la décision "OK je peux lancer le training".

---

## Snapshot quantitatif (2026-05-25, post-livraison Référentiel A/B/C)

**Catalogue & classes**
- 614 commémo 2 € en catalogue, 553 classes distinctes (après design_group merge)
- **0 classes à payload vide** (148 enrichies via Numista per-coin, livré 2026-05-24)
- **14 classes à 0 image** (Numista n'a pas non plus d'images) — cible du chunk BCE dédié
- 600/614 ont une image canonique locale (98 %)

**Training readiness vs seuil 30** (inchangé — l'enrichissement Numista ajoute des canonicals mais pas du wild)
| Tier | n | % |
|---|---|---|
| ✅ ≥ 30 sources | 30 | 5 % |
| ⚠️ 5-29 | 13 | 2 % |
| 🔴 < 5 | 510 | **92 %** |

**Référentiel — état post-Discover live 2026-05-25**
- **6 nouvelles pièces 2026** découvertes via Numista oracle (CY/HR/EE/IE/DE/LT)
- 459 zombies Supabase supprimés
- Images locales : 1185 rows en `coin_canonical_images`, 100 % avec `local_path`
- Push Supabase aligné : 2782 coins, 0 zombie, 2370 fichiers Storage à jour

**Joint issues — 20 variants nationaux manquants détectés** :
- Treaty of Rome 2007 (PT), EMU 2009 (5), Euro cash 2012 (3), EU flag 2015 (4), Erasmus 2022 (7)

**Scrape eBay (7 derniers jours)** — inchangé
- 44 passes (22 DE + 22 ES), 2 920 items kept, recall 72-76 %
- 528 classes sans wild, scrape convergent sur les stars

**Cohortes bench** — inchangé
- 3 frozen / 2 draft. `green-v1` à 1 membre. `mix-zone-17` à 16.

### Lecture stratégique

1. **Référentiel data quality est à un palier solide** (Chunks A/B/C livrés 2026-05-24/25). On a maintenant : images locales canoniques (Chunk A), page `/referential` avec Heal + Discover + Push (Chunks B/C), joint issues tracés, sync Supabase idempotent.
2. **Trust model acté** : confiance par provenance tracée (cf. memory `project_trust_model_referential`). Aucune source n'est "totale" ; on agrège.
3. Le bottleneck training reste la **couverture wild eBay** des 510 rouges. Pas changé.
4. Le seuil 30 reste à valider via mini-bench. Pas changé.
5. Nouveau chantier majeur identifié : **Source BCE complète** (orchestrator dans `/sources` + crop + multi-source UI + review divergences). Session dédiée — gros morceau.

---

## Acquis solides (les "pipes" sont construits)

| Brique | État | Référence |
|---|---|---|
| Référentiel V2 (coins / variants / mint_releases / source_refs) | Live Supabase + eurio.db canonique | `docs/research/referential-v2*.md` |
| Harmonisation eurio.db ↔ Supabase, sync descendant | Chunks 0-4 livrés | `docs/data-harmonization/` |
| i18n 614 commémo 2 € × 6 langs + 563 alias | Live, synchro Supabase | commit `9b5a7db` |
| Theme-matcher recall 100 %, auto-attrib ~89 % | Stable | memory `project_theme_matcher_recall` |
| Découverte eBay par groupe (denom × pays × année) | 6 chunks livrés, routing DE+ES acté | memory `project_discovery_groupee` |
| Listing detection pipeline (YOLO+Hough+polish) | Livré 2026-05-04 | memory `project_listing_detection_pipeline` |
| Scan normalisé Android | Phases 0-4 livrées | `docs/scan-normalization/README.md` |
| Cohort capture flow (admin pilote, app Android `cohortTest`) | Live | `docs/admin/cohort-capture-flow/`, memory `project_cohort_capture_flow` |
| Admin coin details : section "Localisation" i18n + alias | Live | commit `9b5a7db` |
| Cascade-sync MinIO write-through | Chunks 1-4 livrés | `docs/harmonisation-images/` |
| Stockage local images canoniques `ml/canonical_images/` | Livré 2026-05-24 (Chunk A) | `ml/referential/canonical_image_local.py` |
| Dashboard `/operations` (pulse + readiness + diversité + cohorts) | Livré 2026-05-24 | `docs/operations/dashboard-j1.md` |
| Page `/referential` (Heal + Discover + Push + Joint issues) | Livrée 2026-05-25 (Chunks B/C) | `ml/api/referential_routes.py` |
| Trust model par provenance tracée | Acté 2026-05-25 | memory `project_trust_model_referential` |

---

## Trajectoire J1 → J7

```
J0 (catalogue Numista + canonicals obverse/reverse)
  │
  └─► J1 ──────────────────► J2 ──┐
      (scrape eBay routine)       │
                                  ├─► J3 ──► J4 ──► J5 ──► J6 ──► J7
                                  │
      Futures sources scrap ──────┘

J0 : Acquis (déjà fait, en grande partie)
J1 : Scrape eBay intensif (manuel, user-piloté)
J2 : Review humaine systématique des listings flaggés
J3 : Image capture qualité depuis listings reviewés → MinIO
J4 : Quota training-ready atteint par classe (instrumentation dashboard)
J5 : Training ArcFace v2 sur (Numista augmenté ∪ wild scrap)
J6 : Bench sur cohortes capture physiques (hold-out)
J7 : Déploiement Android du nouveau modèle (LiteRT)
```

### Détail par jalon

#### J0 — Référentiel + canonicals Numista (acquis)

- **Définition** : 614 commémo 2 € catalogués + 977 `coin_canonical_images` (obverse / reverse).
- **État** : ~100 % du catalogue, ~half des canonical images.
- **Reste** : enrichir les obverses manquants (classes sans canonical). Tâche d'enrichissement catalogue, séparée du scrape eBay.
- **Done quand** : couverture canonical proche de 100 % pour toutes les commémo 2 €.

#### J1 — Scrape eBay intensif

- **Définition** : passes eBay régulières sur les 385 groupes (denom × pays × année), routage DE+ES uniforme (décision benchmark 2026-05-21).
- **Cadence** : **manuelle, pilotée par Raphaël** quand quota + temps de review sont dispo. ~770 calls API par passage complet, 15 % du quota dev Browse API.
- **Sortie attendue** : `source_images` qui grossit + couverture wild qui monte sur les 510 classes encore à zéro.
- **Dépend de** : J0 (catalog complet), i18n ✅, theme-matcher ✅, listing detection ✅.
- **Done quand** : ne se "termine" pas. Métrique de pilotage = pulse 7j dans le dashboard `/operations`.

#### J2 — Review humaine systématique

- **Définition** : reviewer les listings auto-attribués flagged (~11 % du recall actuel) + ceux où le theme-matcher hésite.
- **Outils existants** : `/review`, `/coins/needs-review` côté admin.
- **Goulot** : humain (Raphaël). ~500 listings / passe eBay, pas faisable en un jour.
- **Dépend de** : J1 alimente la queue.
- **Done quand** : ne se termine pas non plus. Métrique = backlog visible dans `/operations` Section 3.

#### J3 — Image capture qualité depuis listings

- **Définition** : les listings reviewés OK ont leurs images promues en `image_assets` via la pipeline existante (YOLO+Hough+polish, déjà câblé).
- **Pipeline** : `source_images` → crops détectés → `image_assets` → MinIO write-through.
- **Dépend de** : J2 (un listing pas reviewé ne passe pas en `image_assets`).
- **Done quand** : se mesure indirectement par croissance de `image_assets` par classe.

> **Note 2026-05-28 — pourquoi J3 reste bloqué (bonne raison, pas l'ancienne)** :
> L'ancienne justification ("sinon on entasse du crop sous-optimal dans MinIO") est **fausse** :
> les raws bruts sont conservés en permanence (MinIO `enrichment-raws`, séparé de
> `enrichment-crops`), et `ml/scripts/recrop_ebay_orphans.py` re-croppe depuis les raws **sans
> re-scraper**. On ne perd donc rien d'irrécupérable — le format crop est re-dérivable à volonté.
>
> **La vraie raison du blocage** : tant que le format crop n'est pas tranché par l'ablation
> (qui attend les 340 captures device, prévues 2026-05-29), tout training / mini-bench / vérif de
> seuil lancé maintenant tournerait sur un crop provisoire et serait **invalidé** dès que l'ablation
> change le format → on referait tout. On ne brûle pas du GPU/CPU sur un bench jetable.
>
> **Corollaire opérationnel (crop = on-demand)** : le crop Hough/YOLO est CPU-intensif. On ne le
> déclenche pas en masse tant que le format n'est pas figé. Le scrape doit pouvoir tourner
> **download-only** (raws en base + MinIO) et **différer le crop**. Voir livrable #13 ci-dessous —
> l'orchestrateur enchaîne actuellement `detect` (crop) juste après `download` sans option de skip,
> à corriger. Voir [Chantier ablation format crop](#chantier-en-cours--ablation-format-crop-2026-05-25).

#### J4 — Quota training-ready atteint

- **Définition** : assez d'images sources / classe pour entraîner ArcFace en confiance.
- **Seuil acté** : **30 sources / classe** (≈ 2 canonical Numista + 28 wild ; avec augmentation ×10 → 300 samples training).
- **Tiers** : 🔴 < 5, ⚠️ 5-29, ✅ ≥ 30.
- **Instrumentation** : dashboard `/operations` Section 2 (cf. `docs/operations/dashboard-j1.md`).
- **Dépend de** : J3 alimente les images.
- **Done quand** : un nombre suffisant de classes en zone verte ≥ 30. Le seuil "nombre suffisant" reste à arbitrer (50 % ? 80 % ?).

#### J5 — Training ArcFace v2

- **Définition** : entraîner le modèle sur (Numista canonical augmenté) + (wild eBay scrap) fusionnés.
- **Pipeline** : `training-pipeline/` (déjà câblé, Sprint 1 vert).
- **Compute** : GPU 1080 Ti perso.
- **Dépend de** : J4 (sinon training non significatif).
- **Done quand** : run terminé, `model_classes` populées, métriques training internes correctes.

#### J6 — Bench sur cohortes capture

- **Définition** : évaluer le modèle entraîné sur les captures physiques cohort (hold-out par construction).
- **Pipeline** : `evaluate_*.py` sur les `ml/datasets/<numista_id>/captures/` (transférées par `adb pull` depuis le device, app build variant `cohortTest`).
- **Conditions** : 5 conditions standardisées (bright_plain, bright_textured, dim, oblique, glare_specular) — voir `BenchProtocol.kt`.
- **Dépend de** : J5 (modèle à évaluer) + cohorte capturée suffisamment.
- **Done quand** : metric R@1 publiée, écart avec R@1 studio acceptable.

#### J7 — Déploiement Android

- **Définition** : exporter le modèle en LiteRT (.tflite), packager dans l'APK Eurio, pré-calculer `coin_embeddings.npy`.
- **Dépend de** : J6 verdict positif (sinon on retourne en J4/J5).
- **Done quand** : nouvelle version Android shippable, scan fonctionnel.

---

## Dépendances et bottlenecks

| Bottleneck | Pourquoi | Mitigation |
|---|---|---|
| **Review humaine (J2)** | 500 listings / passe eBay, capacité limitée | Ergonomie review (raccourcis clavier, bulk actions) — pas de spec dédiée encore |
| **Couverture wild (J3→J4)** | 510/614 classes à 0 wild images | Plusieurs passes eBay successives, sur plusieurs semaines |
| **Compute training (J5)** | GPU 1080 Ti ≠ cloud, durée d'un run | Calibrer le scope d'entraînement |
| **Cohorte capture suffisante (J6)** | Captures à la main, conditions variées | Cohorte minimum définie (à valider — cf. suspens) |

---

## Suspens ouverts (à arbitrer)

| Suspens | Sévérité | Où le trancher |
|---|---|---|
| **Source BCE complète** (orchestrator + crop + multi-source UI + review divergences) | 🔴 | Session dédiée, voir item #5 ci-dessus. Discussion archi déjà actée 2026-05-25. |
| **`confidence_level` dérivé de `coin_observations`** : vue SQL ou colonne backfilled ? | 🟠 | Décider au moment d'implémenter le badge UI sur `/coins`. |
| **Seuil 30 fondé sur quel bench ?** (estimation, pas data) | 🟠 | Run un mini-training sur classes déjà bien dotées (BE 2012 à 279) avec 10/30/100 pour comparer R@1 |
| **Re-bench routing marketplaces** (i18n LLM livré → re-run benchmark pourrait inclure FR/IT/NL) | 🟠 | Memory `project_marketplace_routing_benchmark` mentionne déjà ce todo |
| **Joint issues — 20 variants manquants** (PT Rome 2007, etc.) | 🟠 | À résoudre via Discover ciblé par numista_id ou ajout manuel via UI Référentiel. |
| **JOUE série C comme backstop d'autorité** | 🟢 | Mentionné dans le trust model, à explorer seulement si Numista+BCE laissent passer une pièce. |
| **`coin_canonical_images` vs `image_assets`** : différence concrète, ce que la pipeline ingest exactement | 🟢 | Spot-read `training-pipeline/sprint-1*` ou code `iteration_augmentations.py` |
| **Comptage captures cohort** dans dashboard Section 4 | ⚪ | Soit endpoint ML API local, soit table d'index `cohort_captures`. Chunk séparé après MVP. |

---

## Chantier en cours — ablation format crop (2026-05-25)

Découvert pendant J3 : les crops eBay actuels sont sous-optimaux (12 % d'undercrop
bimétal sur échantillon 2 € commémo, cf. `docs/operations/crop-bimetal-undercrop.md`).
La discussion a remonté à une **question de fond** : quel format de crop est optimal
pour entraîner ArcFace sur pièces, on-device ? La littérature est silencieuse
sur l'ablation margin/edge (cf. memory `reference_crop_format_research`).

**Décision** : ablation interne, hold-out = device captures (cohorte `mix-zone-17`,
16 coins frozen) plutôt que crops eBay (biaisés par le bug Hough en amont).

### Plan en 4 steps

| Step | Statut | Sortie |
|---|---|---|
| **1 — Audit hold-out** | ✅ livré 2026-05-25 | Constat : 0 cohort capture en DB, ~500 photos cible nécessaires (sensibilité 5 pp R@1) |
| **2 — `CropConfig` paramétrable** | ✅ livré 2026-05-25 | Dataclass `(margin_frac, edge_mode, output_size)` dans `ml/scan/normalize_snap.py`, defaults legacy bit-identiques (zero régression Kotlin parity). 14 tests verts. |
| **2b — App cohortTest extension** | ✅ livré 2026-05-25 | `CaptureProtocol.Mode.{LEGACY, ABLATION}` via directive `# mode=ablation` en première ligne du CSV. 5 conditions BenchProtocol × 4 photos / step + auto-advance. 9 tests Kotlin verts. |
| **3 — Sweep ablation** | ⏳ en attente captures | Sweep margin {2,5,10,15}% × edge {hard, feathered, none} à res 224 fixe. Mesure R@1/R@5 par combo sur le hold-out capture. ~12 runs × 5h GPU 1080 Ti. |
| **4 — Cutover format gagnant** | ⏳ après 3 | Mirror du format gagnant dans `SnapNormalizer.kt` Kotlin, re-crop tous les `enrichment-raws`, re-train modèle prod, deploy LiteRT. |

### Données d'entrée

- **Training data** : eBay scrapings (existants en MinIO, hétérogènes, volume OK).
- **Test data** : device captures cohort `mix-zone-17`, conditions standardisées
  (`bright_plain, bright_textured, dim, oblique, glare_specular` × 4 photos).
- **Cible** : 17 coins × 5 conditions × 4 photos = **340 photos** obverse-only,
  ~1h30 capture humaine.

### Pour reprendre

```bash
# Push CSV (la directive #mode=ablation déclenche les 5 cond × 4 photos)
go-task -t app-android/Taskfile.yml push-capture-csv CSV=ml/state/cohort_csvs/mix-zone-17.csv

# Build + install
go-task android:install

# Shoot via debugMode + captureMode dans DebugBar. UI guide : "PIÈCE 3/17 · oblique · PHOTO 2/4"
# Quand fini : go-task -t app-android/Taskfile.yml pull-debug
```

Memories pertinentes : `project_crop_format_ablation`, `reference_crop_format_research`.

> **Échéance captures 2026-05-29** : les ~340 captures device de la cohorte `mix-zone-17`
> (5 conditions × 4 photos × 17 coins) sont prévues demain. Une fois faites + pull-debug, on lance
> le sweep ablation (Step 3) puis le cutover (Step 4). **Tout ce qui dépend du crop / du training
> reste gelé jusqu'à cette échéance.** Si une session démarre avant que les captures soient là, la
> bonne réponse est : *fais les captures d'abord*.

---

## Prochains livrables

### Référentiel / data quality (en cours)

1. ~~Build du dashboard `/operations`~~ — **livré 2026-05-24**.
2. ~~Combler J0 — Numista per-coin enrichment (58 classes)~~ — **livré 2026-05-24**.
3. ~~Storage local `ml/canonical_images/` + endpoints `/referential/canonical/*`~~ — **livré 2026-05-24 (Chunk A)**.
4. ~~Page `/referential` Heal/Discover/Push + Joint issues~~ — **livrée 2026-05-25 (Chunks B/C)**.
5. **Session dédiée Source BCE — gros chunk** (acté 2026-05-25, à faire en session séparée) :
   - BCE comme Source orchestrée dans `/sources` (runs, status, cadence, idempotence)
   - Cropping intelligent des images BCE (réutilise Hough circle du pipeline scan)
   - Affichage multi-source dans `/coins/:id` (Numista + BCE + eBay side-by-side)
   - Workflow review éditorial pour les divergences BCE↔Numista (slug, theme, date…)
   - Objectif image : combler les 14 zero-canon résiduels (it-2009-louis-braille, etc.) avec source officielle BCE
   - Voir trust model en memory `project_trust_model_referential`
6. **Implémenter `confidence_level` sur les coins** (dérivé de `coin_observations`, badge UI sur `/coins`). Issue du trust model.
7. **Joint issues — combler les 20 variants manquants** (PT/DE/IT/LU/SK/etc.) via Discover ciblé ou ajout manuel.

### Infra scrape / crop (débloque le travail nocturne sans device)

13. **Découpler scrape ↔ crop** — l'orchestrateur (`ml/sources/_base/orchestrator.py`) lance `detect`
    (crop Hough/YOLO) automatiquement après `download`, sans option de skip. Ajouter un mode
    **download-only** (s'arrête après download, raws persistés, `pipeline_state='downloaded'`) + un
    déclencheur crop séparé (CLI/endpoint "crop-only" sur les items `downloaded`, idempotent). But :
    pouvoir scraper en masse sans surchauffer le CPU, et différer le crop jusqu'à ce que le format
    soit figé. Touche : `orchestrator.py`, `cli.py`, `ml/api/sources_routes.py`, front `/sources`.
    **Pré-requis avant tout gros scrape.**

### Training pipeline (GELÉ jusqu'aux captures 2026-05-29)

8. **Sweep ablation format crop** (Steps 3 + 4 du chantier ci-dessus) — démarre dès que les 340
   captures device sont là. **Bloque tout le reste du training.**
9. **Mini-benchmark seuil training** (10 vs 30 vs 100 sources / classe) — **à faire APRÈS le cutover
   crop**, sinon le bench est invalidé par un changement de format. Ne pas lancer avant.
10. **Spec scrape sweep coverage-first** (prioriser 510 rouges plutôt que stars).
11. **Re-bench routing marketplaces** avec i18n LLM activée (~2 h).
12. **Spec ergonomie review** (rendre J2 plus rapide).

---

## Liens canoniques

- **Roadmap stratégique 3 leviers** : `docs/features/README.md`
- **Architecture globale** : `docs/ARCHITECTURE.md`
- **Plan harmonisation data** : `docs/data-harmonization/plan.md`, `architecture.md`
- **Pipeline training** : `docs/training-pipeline/`
- **Détection scan (ML)** : `docs/research/detection-pipeline-unified.md`
- **Cohort capture flow** : `docs/admin/cohort-capture-flow/`
- **Dashboard spec** : `docs/operations/dashboard-j1.md`
- **App Android par phases** : `docs/app-implem-phases/README.md`
- **Analyse J0 + référentiel** : `docs/operations/j0-gap-analysis.md`
- **Trust model référentiel** : memory `project_trust_model_referential`
- **Architecture stockage** : memory `feedback_architecture_eurio_db_vs_supabase`

---

## Notes de lecture

- Les ✓ markers ne sont pas des dates de "tout terminé pour toujours" — beaucoup de jalons (J1, J2, J3) sont **en routine continue**, pas en mode "livré one-shot".
- L'eBay scrape (J1) est **piloté manuellement** par Raphaël. Ne pas proposer d'automatisation cron / scheduler. Le bottleneck est ailleurs (J2 review).
- Les phases Android (UX écrans coffre / sets / profile) avancent **en parallèle** de J1-J7. Voir `docs/app-implem-phases/`.
