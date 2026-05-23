# Eurio — Roadmap J1→J7

> **À quoi sert ce doc** : reprendre une session froide en 5 min. Photo de la trajectoire vers le premier modèle ArcFace utile et son déploiement Android, dans le bon ordre, avec les dépendances explicites.
>
> **Dernière mise à jour** : 2026-05-23
>
> **Pour l'historique des phases ML/data antérieures** : voir `docs/phases/` et `docs/archive/`.
> **Pour la doc app Android** : voir `docs/app-implem-phases/`.

---

## TL;DR

L'infrastructure data + scrape + matching est en place. Il reste à passer en cadence routine sur le scrape eBay, **accumuler des images** sur les 510/614 classes encore à vide, **entraîner** ArcFace sur la masse résultante (Numista canon augmenté + wild eBay+autres), et **bench** sur les cohortes capture physiques.

Le dashboard `/operations` est le tableau de bord qui orchestre la décision "OK je peux lancer le training".

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
- **Conditions** : 5 conditions standardisées (bright_plain, bright_textured, dim, oblique, partial_shadow) — voir `BenchProtocol.kt`.
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
| **Re-bench routing marketplaces** (i18n LLM livré → re-run benchmark pourrait inclure FR/IT/NL) | 🟠 | Memory `project_marketplace_routing_benchmark` mentionne déjà ce todo |
| **Seuil 30 fondé sur quel bench ?** (estimation, pas data) | 🟠 | Run un mini-training sur classes déjà bien dotées (BE 2012 à 279) avec 10/30/100 pour comparer R@1 |
| **`coin_canonical_images` vs `image_assets`** : différence concrète, ce que la pipeline ingest exactement | 🟠 | Spot-read `training-pipeline/sprint-1*` ou code `iteration_augmentations.py` |
| **Comptage captures cohort** dans dashboard Section 4 | ⚪ | Soit endpoint ML API local, soit table d'index `cohort_captures`. Chunk séparé après MVP. |
| **Enrichissement obverses Numista manquants** | ⚪ | Sourcer les classes sans canonical. Independent de J1-J7 mais nécessaire à J0/J5. |
| **Chart lib pour dashboard** | ⚪ | À choisir lors du build dashboard. Démarrer en tableaux + sparklines custom si pas de lib en place. |

---

## Prochains livrables (sans ordre forcé)

1. **Build du dashboard `/operations`** — spec prête dans `docs/operations/dashboard-j1.md` (~4 h).
2. **Re-bench routing marketplaces** avec i18n LLM activée (~2 h).
3. **Mini-benchmark seuil training** (10 vs 30 vs 100 sources / classe sur classes déjà riches).
4. **Spec ergonomie review** (rendre J2 plus rapide).

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

---

## Notes de lecture

- Les ✓ markers ne sont pas des dates de "tout terminé pour toujours" — beaucoup de jalons (J1, J2, J3) sont **en routine continue**, pas en mode "livré one-shot".
- L'eBay scrape (J1) est **piloté manuellement** par Raphaël. Ne pas proposer d'automatisation cron / scheduler. Le bottleneck est ailleurs (J2 review).
- Les phases Android (UX écrans coffre / sets / profile) avancent **en parallèle** de J1-J7. Voir `docs/app-implem-phases/`.
