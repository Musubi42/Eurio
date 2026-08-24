# Backlog — le reste-à-faire des chantiers clos

> Établi le **2026-08-24**, en archivant 25 chantiers de `work-in-progress/`. Chacun
> était à 70-95 % ; ce fichier récupère ce qu'ils portaient encore, pour qu'aucun item
> ne parte à l'archive en silence.
>
> **Ce n'est pas une roadmap.** Rien ici n'est planifié ni priorisé par le PO. C'est
> l'inventaire de ce qu'on sait devoir faire un jour, avec l'endroit où lire le
> raisonnement.
>
> ⚠️ Chaque ligne date du 2026-08-24 et a été recoupée sur le code ce jour-là quand
> c'était possible. **Re-vérifier avant d'agir** — ici les pannes sont muettes (skill
> `eurio-verify`).

## 🔴 À traiter en premier

| # | Item | Détail | Source |
|---|---|---|---|
| B1 | **Un `.env` en clair traîne à la racine** | 733 octets, daté du 13 avril, gitignoré, **contenant `SUPABASE_SERVICE_ROLE_KEY`, `EBAY_CLIENT_SECRET` et une clé Numista**. Vérifié le 2026-08-24 : **aucun code ne le lit** (`load_dotenv` absent du dépôt). C'est le dernier store de secrets en double que [ADR-015](./adr/015-secrets-sops-age.md) devait supprimer. `rm .env` — geste PO, pas agent | `operations/secrets-followup.md` · [ADR-015](./adr/015-secrets-sops-age.md) |
| B2 | **Confirmer la révocation des clés fuitées** | [ADR-005](./adr/005-remaster-historique-git.md) affirme « clés révoquées par le PO » ; `operations/secrets-followup.md` (juillet) laisse les cases eBay PROD et Supabase `service_role` **décochées**. Les deux ne peuvent pas être vrais. Trancher, puis corriger le doc perdant | `operations/secrets-followup.md` |
| B3 | **46 findings de robustesse non traités** | Audit multi-agents du 2026-07-04 : 58 findings confirmés (4 critical, 21 high, 33 medium), 12 corrigés, **46 cadrés en 9 fiches auto-portées `F01`…`F09`, prêtes à dispatcher** | [`work-in-progress/hardening-2026-07/`](./work-in-progress/hardening-2026-07/) |

## Données et stockage

| # | Item | Détail | Source |
|---|---|---|---|
| D1 | **Le chemin d'ÉCRITURE des canoniques pousse encore vers Supabase** | `ml/referential/coin_image_storage.py` porte toujours `BUCKET_NAME = "coin-images"` (vérifié 2026-08-24). La lecture est migrée vers MinIO + CDN depuis juin ; les **nouveaux** canoniques atterrissent donc hors du bucket et tombent sur le fallback FS. Cible : clé `{eurio_id}/{role}_{src}.webp` dans `numista-canonical` | `archive/harmonisation-images/` |
| D2 | **546 `source_images` legacy sur chemins FS absolus** | BCE 475 + JO 71 → backfill ciblé vers `enrichment-raws` | `archive/harmonisation-images/` |
| D3 | **`ml/state/training.db` fantôme** | Existe encore sur disque, plus aucun écrivain identifié. À supprimer après vérification | `archive/data-harmonization/` |
| D4 | **Chunk 5 — migration d'identité** | Le seul chunk non livré du design canonique verrouillé : driver de migration (journal `eurio_id_migrations` → propagation vers `image_assets`/cohortes/bench), re-pin du bench gold, replay des ~28 entrées BE 2017, re-jugement de 17 gold 2017, i18n de 147 pièces générées | `archive/data-harmonization/architecture.md` |
| D5 | **Bucket MinIO `eurio-db`** | Legacy, remplacé par `db_routes.py`. Plus aucune référence dans `ml/` au 2026-08-24 — **le retrait est peut-être déjà faisable**, à confirmer côté VPS avant de supprimer le bucket | [`architecture/README.md`](./architecture/README.md) |

## Modèle, entraînement, scan

| # | Item | Détail | Source |
|---|---|---|---|
| M1 | **Le premier bench 50 sessions sur device** | Tout le tooling est livré et la parité Kotlin↔Python est verrouillée par test (≤1e-3). Ce qui manque est de la **manip device** : 50 sessions au protocole guidé, `recordFramesEnabled` on, ~25 min d'annotation, rapport dans `results/` | `archive/best-frame-capture/` |
| M2 | **User-harvest in-app** (phase 4 du harvest) | L'utilisateur scanne → confirme ou corrige → on récupère **une photo unique, label sûr** pour le training. Le seul vrai manque de la vision harvest ; gaté sur l'app Android | `archive/training-pipeline/` |
| M3 | **Parité crop scan Android ↔ crop d'entraînement** | Le crop eBay a été corrigé (`detect_bbox_refine`, ~92 %) ; le crop du scan Android ne l'a pas suivi. C'est un **drift train↔inference**, pas une finition | `archive/crop-quality-overhaul/` |
| M4 | **Outillage de review manuelle pour la traîne** | Les ~8 % que l'algo rate n'ont pas d'écran pour être repris à la main | `archive/crop-quality-overhaul/` |
| M5 | **Rollout `design_group` aux autres pays** | Le pilote BE est livré (chunks 1-5). Reste le chunk 6, le gate parseur derive-then-diff, la validation vision LLM par pays | `archive/design-groups-standards/` |
| M6 | **Gros run PC ArcFace 16 classes** | Jamais lancé. Et `05-ebay-standards` : les standards ne sont pas scrapables (`v_ebay_freshness_groups` filtre `is_commemorative=1`) | `archive/lab-streamline/` |
| M7 | **`coin_confusion_map` vers `eurio.db`** | Migration différée | `archive/lab-streamline/` |

## Sources et référentiel

| # | Item | Détail | Source |
|---|---|---|---|
| S1 | **Cutover V2 eBay multi-marketplace** | Fil resté ouvert à la clôture du chantier sources | `archive/sources-refacto/ebay-multi-marketplace/` |
| S2 | **`ReferentialSourceAdapter` (sdk-kickoff)** | Différé post-cohorte 19 | `archive/sources-refacto/` |
| S3 | **DINO × texte combiné** | Chunk 9 du chantier sources, jamais joué | `archive/sources-refacto/` |

## Outillage et qualité

| # | Item | Détail | Source |
|---|---|---|---|
| Q1 | **Suite de tests AI-first** | Cadrage solide (catégories A-F, dashboard, 7 questions à trancher), **0 % démarré depuis avril**. Le doc note que la review auto-validation du 2026-05-05 a saigné ~70 % de faux positifs faute de tests vérifiables. Gros levier, jamais pris | `archive/handoffs-2026/ai-first-test-suite.md` |
| Q2 | **Refacto de `ml/`** | God-node `state/store.py` (2705 lignes, 176 arêtes au graphe), un seul process FastAPI, ~106 scripts. Cadrage écrit en juin 2026, **jamais engagé**. Sa décision « jobs détachés » est passée dans le code depuis, par ailleurs | `archive/refacto-ml/` |
| Q3 | **Parité proto ↔ Android : les flows manquants** | 16 flows Maestro pour ~26 scènes. Manquent onboarding (×5), coin-detail, vault-catalog-country, profile-unlock. **Les screenshots Android datent du 2026-04-17** — l'app a beaucoup changé, il faut re-runner avant de conclure quoi que ce soit d'une capture | `archive/parity/` |
| Q4 | **Pont Maestro ↔ Playwright** | Rejouer les *steps* yaml comme assertions Playwright, pas seulement en screenshot. C'est la vraie partie différée du chantier parité | `archive/parity/` |
| Q5 | **Recette d'un PAT réel bout en bout** (F4) | Génération + collage + appel authentifié, jamais joué en vrai | `archive/auth-redesign/PAT-WORKFLOW.md` |
| Q6 | **Chemins post-rename `eurio_id`** | Vérifier que `ml/datasets/` colle au layout actuel, et confirmer le freeze auto de `cohort.status` vs `CohortDetailPage.vue` | `archive/cohort-capture-flow/` |

## Ce qui est explicitement gelé — ne pas reprendre en l'état

| Item | Pourquoi |
|---|---|
| **S7 — auto-rejet de crop sur seuils** (`crop-forensics`) | Ses deux seuils dépendent de `bg_uniformity` (S4) et `inner_feature_score` (S5/S6), **tous réfutés sur les bench**. Implémenter l'auto-reject sur des signaux morts = faux positifs garantis. S7 attend un **nouveau signal discriminant** avant d'avoir un sens |
| **Découpage du monorepo** | [ADR-007](./adr/007-pas-de-split-eurio-avant-artefacts.md) : il faut d'abord publier tokens et catalogue |
| **Remaster de l'historique git** | [ADR-005](./adr/005-remaster-historique-git.md), 🟡 proposée, non exécutée. Conditionne la position de [ADR-015](./adr/015-secrets-sops-age.md) sur l'historique fuité |
