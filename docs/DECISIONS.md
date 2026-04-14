# Eurio — Journal des décisions

> **Point unique** pour retrouver ce qui a été tranché, quand, et où se trouve le détail.
>
> Ce fichier est un **index**, pas un document de conception. Il liste les décisions majeures du projet et pointe vers la source autoritaire pour le détail complet. Quand une décision change, l'ancienne est marquée ⚪️ *superseded* avec un lien vers la nouvelle.
>
> **Dernière mise à jour** : 2026-04-14

---

## Où vit quelle information

| Type | Source | Quand mettre à jour |
|---|---|---|
| **ADRs techniques** | [`docs/adr/`](./adr/) | Un fichier numéroté `00X-*.md` par décision majeure. Format : Contexte / Décision / Conséquences. |
| **Décisions design prototype** | [`docs/design/prototype/_shared/DECISIONS.md`](./design/prototype/_shared/DECISIONS.md) | Liste numérotée §1→§N, format Contexte / Alternatives / Choix / Raison. Étendue au fil des phases. |
| **Architecture transverse (offline/auth/data/debug)** | [`docs/design/_shared/`](./design/_shared/) | Un fichier par thème. Contient décisions + questions ouvertes thématiques. |
| **Décisions par vue** | `docs/design/{vue}/README.md` | Tableau "Décision / Contexte" spécifique à une vue. |
| **ADRs ML historiques** | Mémoire Claude `project_phase1_decisions.md` | Expérimentations ML, pivots (triplet → ArcFace). |
| **Questions ouvertes prototype** | [`docs/design/prototype/OPEN-QUESTIONS.md`](./design/prototype/OPEN-QUESTIONS.md) | Priorisées P0/P1/P2, relues par milestone. |
| **Changelog prototype** | [`docs/design/prototype/CHANGELOG.md`](./design/prototype/CHANGELOG.md) | Log technique des changements du proto. |
| **État du projet** | [`docs/roadmap.md`](./roadmap.md) | Photo instantanée fait/en-cours/à-faire. |
| **Vue d'ensemble archi** | [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) | Overview 15 min, mise à jour par milestone. |
| **Mémoire Claude persistante** | `~/.claude/projects/-Users-musubi42-Documents-Musubi42-Eurio/memory/MEMORY.md` | Préférences, contraintes, rappels cross-session. |

---

## Statuts

- 🟢 **Actif** — en vigueur
- 🟡 **Expérimental** — à valider avec données réelles (souvent gated par Phase 2B ML)
- ⚪️ **Superseded** — remplacée, gardée pour l'historique
- 🔴 **À re-trancher** — questionnée, décision à reprendre
- 🔵 **Ouverte** — non tranchée, voir OPEN-QUESTIONS

---

## Produit — scope et vision

| Statut | Décision | Date | Source |
|---|---|---|---|
| 🟢 | Scope v1 beta : Onboarding + Scan + Coffre + Profil (Explorer reporté, Marketplace teasée) | 2026-04-13 | [`design/README.md`](./design/README.md) |
| 🟢 | Fiche pièce = **une seule vue paramétrée** par contexte (`scan` / `owned` / `reference`) | 2026-04-13 | [`design/coin-detail/README.md`](./design/coin-detail/README.md) |
| 🟢 | Onboarding 3 écrans max + skippable dès l'écran 1, aucun compte requis | 2026-04-13 | [`design/onboarding/README.md`](./design/onboarding/README.md) |
| 🟢 | Pièce hero onboarding = 2€ iconique **immuable** (pas la commémo du moment) | 2026-04-14 | Conversation 2026-04-14 |
| 🟢 | Scan = killer feature style Yuka/QR : continu, zéro bouton capture, zéro guide bloquant | 2026-04-13 | [`design/scan/README.md`](./design/scan/README.md) |
| 🟢 | Gamification organique, 4 niveaux (Découvreur → Passionné → Expert → Maître), **pas de régression** | 2026-04-13 | [`design/profile/level-progression.md`](./design/profile/level-progression.md) |
| 🟢 | Sets v1 : séries par pays (1ct→2€), émissions communes, commémos par pays, millésime, Grand chase, Coffre d'or | 2026-04-13 | [`design/profile/achievements-engine.md`](./design/profile/achievements-engine.md) |
| 🟢 | Bottom nav v1 : Scan central · Coffre · Profil · **Marketplace grisée** (teasée pour anticipation produit) | 2026-04-13 | Conversation 2026-04-13 |
| 🔵 | Valeur globale du coffre fluctue dans le temps (sparkline) → implémenté en proto, à valider pour l'impl | 2026-04-14 | `design/prototype/scenes/vault-home.{html,js}` |

---

## Auth & offline-first

| Statut | Décision | Date | Source |
|---|---|---|---|
| 🟢 | **Auth silencieuse/différée**. Zéro compte en v1. Core loop 100% local. Upgrade compte seulement quand une feature l'exige (marketplace, partage). | 2026-04-13 | [`design/_shared/auth-strategy.md`](./design/_shared/auth-strategy.md) |
| 🟢 | Pattern Duolingo : auth proposée uniquement **après 3 pièces ajoutées** ou 48h d'usage, skippable sans pénalité | 2026-04-13 | [`design/_shared/auth-strategy.md`](./design/_shared/auth-strategy.md) |
| 🟢 | Credential Manager Android (Google Sign-in + passkeys) + Supabase anonymous → link identity en v2 | 2026-04-13 | [`design/_shared/auth-strategy.md`](./design/_shared/auth-strategy.md) |
| 🟢 | **Offline-first total** : APK seed du référentiel (~16 MB) + delta fetch Supabase opt-in, jamais live Numista | 2026-04-13 | [`design/_shared/offline-first.md`](./design/_shared/offline-first.md) |
| 🟢 | Stockage local : **Room SQLite** typé avec migrations versionnées (pas JSON-in-assets) | 2026-04-13 | [`design/_shared/data-contracts.md`](./design/_shared/data-contracts.md) |
| 🟢 | Sync cloud du coffre = opt-in v2 uniquement. v1 = tout local avec UUID généré. | 2026-04-13 | [`design/_shared/auth-strategy.md`](./design/_shared/auth-strategy.md) |

---

## ML & Scan

| Statut | Décision | Date | Source |
|---|---|---|---|
| ⚪️ | ~Triplet loss ArcFace pour scan~ → échec sur POC initial | Phase 1 | Mémoire `project_phase1_decisions.md` |
| 🟢 | Pivot : **Classification bridge** (MobileNetV3 fine-tuné) puis **ArcFace metric learning** 500+ classes | Phase 2A/2B | Mémoire `project_phase1_decisions.md` |
| 🟢 | Runtime Android = **LiteRT** (ex-TFLite) | Phase 0 | [`adr/001-litert-over-tflite.md`](./adr/001-litert-over-tflite.md) |
| 🟢 | Scan 100% on-device par défaut, aucune photo n'est uploadée pour un scan qui réussit localement | 2026-04-13 | [`design/scan/README.md`](./design/scan/README.md) |
| 🟡 | **Stratégie mise à jour modèle ML** : Option B (delta embeddings via Supabase) à privilégier, Option C (hybride avec fallback serveur) si généralisation ArcFace casse | 2026-04-13 | [`design/_shared/offline-first.md`](./design/_shared/offline-first.md) |
| 🔵 | Remote scan fallback synchrone (Option A) : à trancher après Phase 2B avec métriques réelles | 2026-04-13 | [`design/scan/remote-fallback.md`](./design/scan/remote-fallback.md) |
| 🟢 | Dev/debug pattern = **build variant natif + hidden dev menu** (7-tap sur badge version, pastille rouge quand debug on) | 2026-04-14 | [`design/_shared/dev-debug-strategy.md`](./design/_shared/dev-debug-strategy.md) |
| 🟢 | Overlay scan debug = 5 layers (bbox YOLO + top-5 matches + latences + context runtime + histogramme convergence) en monospace | 2026-04-14 | [`design/scan/debug-overlay.md`](./design/scan/debug-overlay.md) |
| 🟢 | Dumps debug dans `externalFilesDir` (accessible USB sans root), rotation 200 MB **ET** 90 jours | 2026-04-14 | [`design/scan/debug-overlay.md`](./design/scan/debug-overlay.md) |
| 🔴 | ~YOLOv8n pour détection de pièce~ : faux positifs massifs sur dataset réel, à retravailler ou abandonner | Phase 1B | [`roadmap.md`](./roadmap.md) |

---

## Data & référentiel

| Statut | Décision | Date | Source |
|---|---|---|---|
| ⚪️ | ~`coins.id = UUID`, Numista IDs comme PK~ → legacy schema abandonné le 2026-04-13 | < 2026-04-13 | [`design/_shared/data-contracts.md`](./design/_shared/data-contracts.md) |
| 🟢 | **`eurio_id` canonique** reconstructible (`{country}-{year}-{face}-{slug}`) comme PK de la table `coins` | 2026-04-13 | [`research/data-referential-architecture.md`](./research/data-referential-architecture.md) |
| 🟢 | Référentiel = **source of truth**, Numista = simple enrichissement. Aucune source ne peut créer une entrée canonique | 2026-04-13 | [`research/data-referential-architecture.md`](./research/data-referential-architecture.md) |
| 🟢 | Schema canonique = 6 tables Supabase (`coins`, `source_observations`, `matching_decisions`, `review_queue`, `coin_embeddings`, `user_collections`) | 2026-04-13 | [`research/phase-2c7-supabase-sync-run.md`](./research/phase-2c7-supabase-sync-run.md) |
| 🟢 | **Matching pipeline 5 stages** : cross-ref → structural unique → structural+fuzzy → numeric → visual (ArcFace, gated sur Phase 2B) | 2026-04-13 | [`research/data-referential-architecture.md`](./research/data-referential-architecture.md) |
| 🟢 | Pas d'auto-création de variantes : collisions vont dans `review_queue`, jamais `-v2` auto | 2026-04-13 | [`research/data-referential-architecture.md`](./research/data-referential-architecture.md) |
| 🟢 | Bootstrap merge pattern préserve `images`, `design_description`, `sources_used` sur re-run | 2026-04-13 | [`phases/phase-2c-referential.md`](./phases/phase-2c-referential.md) |
| 🟢 | Émissions communes zone euro = **une seule entrée canonique** (`eu-*`) avec `national_variants` listé (Option A figée) | 2026-04-13 | [`research/data-referential-architecture.md`](./research/data-referential-architecture.md) |
| 🟢 | Photos Numista fetchées via **scrape one-shot côté `ml/`** → upload Supabase Storage → app fetch CDN. Jamais d'appel live Numista (rate limit 2000/mois épuisé en avril 2026) | 2026-04-13 | [`design/_shared/offline-first.md`](./design/_shared/offline-first.md) |
| 🟢 | eBay Finding API morte depuis 2025-02-05 → Browse API + velocity weighting (`ebay_client.py`) | 2026-04-13 | [`research/phase-2c4-ebay-run.md`](./research/phase-2c4-ebay-run.md) |
| 🟢 | Bulgarie dans la zone euro depuis 2026-01-01 → **21 pays** euro à partir de 2026 | 2026-01-01 | Mémoire `reference_eurozone_21.md` |
| 🟢 | Schema Room local = **miroir aplati** du schema Supabase (JSONB → colonnes typées), sync par points (bootstrap / delta fetch / prix eBay / user collection) | 2026-04-13 | [`design/_shared/data-contracts.md`](./design/_shared/data-contracts.md) |

---

## Design system

| Statut | Décision | Date | Source |
|---|---|---|---|
| 🟢 | **Fraunces italic** = display serif officiel (numismatique / museum) | 2026-04-14 | [`design/prototype/_shared/DECISIONS.md`](./design/prototype/_shared/DECISIONS.md) §1 |
| 🟢 | **Inter Tight** = typo UI, **JetBrains Mono** = mono (tabular nums, technique, debug) | 2026-04-13 | [`design/prototype/_shared/DECISIONS.md`](./design/prototype/_shared/DECISIONS.md) |
| 🟢 | Palette primary = **indigo deep `#1A1B4B`** (`--indigo-700`) évoquant drapeau européen | 2026-04-14 | [`design/prototype/_shared/tokens.css`](./design/prototype/_shared/tokens.css) |
| 🟢 | Accent = **or brossé `#C8A864`** (`--gold`), **parcimonieux** (réservé aux "moments" : set complete, médaille, P50 médiane, delta positif) | 2026-04-13 | [`design/prototype/_shared/DECISIONS.md`](./design/prototype/_shared/DECISIONS.md) |
| 🟢 | Surface warm `#FAFAF8` / paper `#F4F1E8` (pas blanc SaaS) — feel musée | 2026-04-14 | Convergence des 5 agents Phase 2 initiaux |
| 🟢 | Radius 12px default / 8px petits / 24px sheets+cards / 999px pills | 2026-04-14 | [`design/prototype/_shared/tokens.css`](./design/prototype/_shared/tokens.css) |
| 🟢 | Spacing scale 4/8/12/16/24/32/48 | 2026-04-14 | [`design/prototype/_shared/tokens.css`](./design/prototype/_shared/tokens.css) |
| 🟢 | `font-variant-numeric: tabular-nums` partout pour les valeurs monétaires | 2026-04-14 | Convergence Phase 2 |
| 🟢 | ~Instrument Serif dans l'agent scan~ → banni en Phase 3 | 2026-04-14 | [`design/prototype/_shared/DECISIONS.md`](./design/prototype/_shared/DECISIONS.md) |
| 🟢 | Esthétique cible = **"cabinet du collectionneur" / museum card** (grain overlay, hairlines, numérotation section cartel) — jamais gamification kitsch américaine | 2026-04-13 | [`design/onboarding/mockups/DESIGN-NOTES.md`](./design/onboarding/mockups/DESIGN-NOTES.md) + convergence |

---

## Prototype navigable (HTML/CSS/JS)

| Statut | Décision | Date | Source |
|---|---|---|---|
| 🟢 | Niveau 3 : prototype navigable complet (shell + router + state + vraie data JSON), servable `python3 -m http.server` + ngrok-friendly | 2026-04-14 | [`design/prototype/README.md`](./design/prototype/README.md) |
| 🟢 | **Vanilla** : pas de framework, pas de build, pas de npm, pas de TypeScript — HTML + CSS + ES modules | 2026-04-14 | [`design/prototype/_shared/DECISIONS.md`](./design/prototype/_shared/DECISIONS.md) |
| 🟢 | Router **hash-based** (`#/path`), pas history API (http.server ne peut pas rewrite) | 2026-04-14 | [`design/prototype/_shared/DECISIONS.md`](./design/prototype/_shared/DECISIONS.md) |
| 🟢 | Scenes = **fragments HTML** injectés dans `#view`, sidecar optionnel `scenes/xxx.js` exporte `mount({params, query, state, data, navigate})` | 2026-04-14 | [`design/prototype/_shared/router.js`](./design/prototype/_shared/router.js) |
| 🟢 | Vraies données = fetch `ml/datasets/eurio_referential.json` (2938 coins) une fois, en mémoire. **Pas d'images réelles**, SVG placeholders paramétrés par métadonnées | 2026-04-14 | [`design/prototype/_shared/data.js`](./design/prototype/_shared/data.js) |
| 🟢 | Persistence = localStorage sous clé unique `eurio.proto.v1`, reset via `#/debug/reset` | 2026-04-14 | [`design/prototype/_shared/state.js`](./design/prototype/_shared/state.js) |
| 🟢 | Collection seed **vide** au premier run (pas de fake data) → vraie expérience first-run. Seed démo via `#/debug/seed-demo` ou bouton settings | 2026-04-14 | [`design/prototype/_shared/state.js`](./design/prototype/_shared/state.js) |
| 🟢 | Responsive : device frame 390×844 sur desktop, plein viewport ≤ 500px | 2026-04-14 | [`design/prototype/_shared/shell.css`](./design/prototype/_shared/shell.css) |
| 🟢 | Chrome contract = `data-chrome="light|dark|none"` porté par le route config, géré par `shell.css`. `none` cache statusbar/nav/home/badge pour les scenes full-bleed (onboarding, unlock). | Phase 3 | [`design/prototype/CHANGELOG.md`](./design/prototype/CHANGELOG.md) |
| 🟢 | **Tokens only dans les scenes** : zéro hex hardcodé, zéro `font-family` inline. Enforced via `grep` en acceptance test. | 2026-04-14 | [`design/prototype/_shared/DECISIONS.md`](./design/prototype/_shared/DECISIONS.md) |
| 🟢 | Dark mode reporté v2 : picker settings désactivé avec pill "Bientôt · v2" | Phase 3 | [`design/prototype/CHANGELOG.md`](./design/prototype/CHANGELOG.md) |
| 🟢 | Auto-unlock celebration : `addCoin()` → `checkSetCompletions()` → `pendingUnlock` → profile.js auto-navigate vers `/profile/unlock?setId=X` une seule fois | Phase 3 | [`design/prototype/_shared/state.js`](./design/prototype/_shared/state.js) |

---

## Infra & build

| Statut | Décision | Date | Source |
|---|---|---|---|
| 🟢 | **Toutes les deps passent par `flake.nix`** : pas de `brew install`, pas de `pip install` hors `ml/.venv/`. Package manquant → ajouter à flake.nix. | Phase 0 | [`adr/002-nix-devshell.md`](./adr/002-nix-devshell.md) + mémoire `feedback_nix_devshell.md` |
| 🟢 | Tests Python = **stdlib `unittest`** uniquement, pas pytest. Lancer `python ml/test_eurio_referential.py`. | 2026-04-13 | [`roadmap.md`](./roadmap.md) |
| 🟢 | Android Studio utilisé **uniquement** pour build release APK, debug natif, profiling. Dev quotidien via CLI Gradle. | Phase 0 | [`research/data-referential-architecture.md`](./research/data-referential-architecture.md) |
| 🟢 | Supabase project existe, RLS configurée (lecture publique coins, écriture owner-only user_collections), advisors verts | 2026-04-13 | [`research/phase-2c7-supabase-sync-run.md`](./research/phase-2c7-supabase-sync-run.md) |
| 🟢 | **Zéro infra live coûteuse** : préférence forte pour serverless / static / zero-ops. VPS évité. | Ongoing | Mémoire `project_eurio_stack.md` |
| 🟢 | Coin catalog : utiliser `coin_catalog.json` pour les Numista IDs, **jamais deviner** | Ongoing | Mémoire `feedback_coin_catalog.md` |
| 🟢 | Pas de technical debt : construire proprement dès le POC, pas de shortcut qui crée de la dette | Ongoing | Mémoire `feedback_no_debt.md` |

---

## Comment utiliser ce fichier

- **Chercher une décision** → `Cmd+F` sur ce fichier. Les catégories sont stables.
- **Prendre une nouvelle décision** → ajouter une ligne dans la bonne catégorie avec statut 🟢, date, description courte, lien vers la source détaillée. Si la décision remplace une précédente, marquer l'ancienne ⚪️ avec un renvoi.
- **Questionner une décision existante** → passer en 🔴, ajouter une note dans [`design/prototype/OPEN-QUESTIONS.md`](./design/prototype/OPEN-QUESTIONS.md) si c'est lié au proto, ou créer une ADR dans `docs/adr/` si c'est technique et mérite un débat formel.
- **Consolider un thème** → créer un doc dans `docs/design/_shared/` ou un ADR, puis pointer dessus depuis ici.

**Principe** : ce fichier **indexe** mais ne **duplique pas**. Si une décision a un doc détaillé, on pointe dessus. Si c'est une décision one-liner, on la garde ici.

---

## Voir aussi

- [`docs/roadmap.md`](./roadmap.md) — photo instantanée fait / en cours / à faire
- [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) — overview 15 min de l'archi complète
- [`docs/adr/`](./adr/) — ADRs techniques numérotées
- [`docs/design/prototype/OPEN-QUESTIONS.md`](./design/prototype/OPEN-QUESTIONS.md) — questions non tranchées
- [`docs/design/prototype/CHANGELOG.md`](./design/prototype/CHANGELOG.md) — historique technique du proto
