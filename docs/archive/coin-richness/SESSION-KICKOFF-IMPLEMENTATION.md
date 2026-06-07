# Kickoff — Session implémentation Coin Richness

> **Document destiné à une nouvelle session Claude Code** (ou à Raphaël lui-même
> en reprise de fil). Lis-le **en entier**, puis lis l'ordre de lecture §3 avant
> de toucher du code.
>
> Date de rédaction : **2026-05-25**. Auteur : session brainstorm Coin Richness.
>
> ⚠️ **Statut 2026-05-25 fin de session 2** : P.1 + P.2 + P.3a + P.3b + P.4
> livrés sur branche `coin-richness/p3-schema` (non encore commité au moment
> de la dernière édition de ce doc). Voir `ROADMAP-DB.md` §0 pour le progress
> log complet. Le présent doc **reste valide pour le cadrage** ; pour la
> prochaine session implémentation, lire d'abord `SESSION-KICKOFF-P5-P6.md`.

---

## 1. TL;DR

La session précédente (2026-05-25) a été une **session de cadrage en
profondeur** sur le chantier `coin-richness` — refonte du référentiel
pièces Eurio pour le rapprocher de la richesse de 2euros.org (cote
temporelle, mintage atelier × qualité, designer, JOUE, indice de rareté).

**Rien n'a été implémenté.** Tout le travail de cette session est en doc :
- 1 ROADMAP canonique (`ROADMAP-DB.md`)
- 3 chantiers deep-dive (`chantier-A-cote.md`, `chantier-C-mintage.md`, `chantier-D-metadata.md`)
- 1 kickoff produit (`kickoff.md`)
- 1 kickoff implémentation (ce fichier)

**La prochaine session implémente.** Mais **avant**, lis tout (≈ 30 min).
La quantité de décisions implicites est trop importante pour aller au code
direct.

---

## 2. La décision-clé à ne PAS rater

Cette session a acté **deux changements de doctrine** qui touchent à
l'architecture entière du projet — pas juste à coin-richness :

### 🔴 Doctrine 1 — SQLite-only

`eurio.db` est **LA source de vérité unique** côté dev local. Stop la
pratique passée de doubler les écritures dans Supabase pour que l'admin
Vue y lise directement. Cf. mémoire [[feedback-sqlite-only-doctrine]].

**Conséquences immédiates** :
- Toute nouvelle migration référentielle → `ml/state/schema.sql`, **jamais**
  `supabase/migrations/`.
- L'admin Vue doit être recâblé : lectures via API Python ml/ (FastAPI),
  plus de SDK Supabase pour le référentiel.
- Tables qui étaient migrées uniquement dans Supabase (referential-v2 :
  `coin_variants`, `coin_mint_releases`, `coin_source_refs`,
  `mint_release_prices`) sont **à rapatrier dans `eurio.db`**.
- Supabase devient **cible app Android uniquement**. Sync sortant manuel
  futur (cf. §"Sync Supabase" plus bas).

### 🔴 Doctrine 2 — Provenance first-class, pas de fallback silencieux

Chaque fact en DB **porte sa source** via FK vers `source_registry`. Si
deux sources divergent (BCE 29/01/2010 vs Numista 01/02/2010), on garde
les **deux lignes**, jamais une seule "valeur consensus" qui efface l'origine.

**Conséquences** :
- Pattern **Identity + Observations** partout :
  - `coins`, `coin_variants`, `coin_mint_releases` = **identity pure**
  - `coin_observations`, `mint_release_observations` = **facts avec source**
- Pas d'enum `confidence` per-fact (jugée flotttante). La confiance est
  **dérivée** : `COUNT(DISTINCT source) GROUP BY fact` = agreement_count.
- Multi-source same value = **2 lignes systématiquement** (devient un signal
  positif d'agreement).

---

## 3. Ordre de lecture recommandé

Lis dans cet ordre **avant de toucher du code** :

1. **`kickoff.md`** (5 min) — le pourquoi produit, l'inspiration 2euros.org,
   le mapping de richesse à atteindre
2. **`ROADMAP-DB.md`** (15 min) — **LE document opérationnel canonique**.
   Schéma cible, phases P/V/F, cohorte de validation, décisions, wipe scope
3. **`chantier-C-mintage.md`** (10 min) — pattern Identity+Observations en
   détail, schéma `mints` + `coin_mint_releases` + `mint_release_observations`
4. **`chantier-D-metadata.md`** (5 min) — designer, JOUE, edge, release_date
   (révisé pour observations multi-source)
5. **`chantier-A-cote.md`** (5 min) — cote eBay weekly snapshot-only, bloqué
   par discovery (parallèle, pas urgent)
6. **`docs/archive/numista-clean-refetch-kickoff.md`** (référence historique
   du refetch — à intégrer dans P.7)

**Mémoires à consulter** :
- `feedback_sqlite_only_doctrine.md` — Doctrine 1
- `project_coin_richness.md` — index général
- `feedback_architecture_eurio_db_vs_supabase.md` — durcie par Doctrine 1
- `project_referential_v2_design.md` — modèle TYPE / VARIANT / MINT_RELEASE
- `project_trust_model_referential.md` — provenance par source

---

## 4. État de la DB actuelle (snapshot 2026-05-25)

| Table | Rows | À faire au reset |
|---|---|---|
| `referential_catalog` | 688 | **Wipe** (sera re-scrapé) |
| `coins` | 2782 | **Wipe** (toutes denoms) |
| `design_groups` | 18 | **Wipe** |
| `coin_cross_refs` | 3233 | **Wipe** |
| `coin_observations` | 3192 | **Wipe** (legacy_import wikipedia/lmdlp/bce — repartira propre) |
| `coin_canonical_images` | 1022 | **Wipe** |
| `coin_aliases` | 563 | **Wipe** |
| `coin_names_i18n` | 3936 | **Wipe** |
| `coin_market_quotes` | 42 | **Wipe** (eBay 20-22 mai, 3j historique perdus = accepté) |
| `coin_national_variants` | 0 | déjà vide |
| `eurio_id_migrations` | 3 | **Préserver** (patrimoine rename/split/merge) |
| Toute l'infra training / cohorts / image_assets / source_runs / review_queue | ... | **Préserver** intégralement |

Sur 13.4k lignes référentielles : tout part. Sur l'infra d'enrichissement
terrain (eBay, images, training) : rien ne bouge.

---

## 5. Schéma cible — ce qui doit exister en eurio.db post-prep

### 5.1 — Tables NOUVELLES à créer (P.3)

| Table | Rôle |
|---|---|
| `source_registry` | Catalogue des sources : `numista_api`, `bce_official`, `2euros_org`, `bundesbank`, `mdp`, `lmdlp`, `wikipedia`, `ebay_browse`, `manual`, `eurio_derived`. `kind ∈ {official, reference, community, manual, derived}` |
| `mints` | Ateliers normalisés (slug PK : `de-berlin-a`, `fr-pessac`, `it-roma-r`, ...) |
| `coin_variants` | Niveau VARIANT (classic, coloured, hologram, ...). Rapatrié Supabase V2 |
| `coin_mint_releases` | Niveau MINT_RELEASE : (parent_type, year, mint_id, issue_type). Identity pure |
| `coin_source_refs` | Multi-source refs polymorphe (rapatrié Supabase V2) |
| `mint_release_prices` | Prix × grade × source × mint_release (rapatrié Supabase V2) |
| `mint_release_observations` | Facts atelier-level avec source (mintage, released_on, frequency, ...) |
| `coin_credits` | Graveur avers + graveur revers (Luycx stocké 524 fois OK) avec `source` en PK |
| `coin_edge_variants` | Tranche A / B (DE 2007-2008) |

### 5.2 — Tables existantes à MODIFIER (drop + recreate dans P.6, sous garde-fou)

SQLite n'a pas `ALTER TABLE ADD CONSTRAINT`. Le drop+recreate des 6 tables
source-aware ne peut pas vivre dans `_bootstrap` (tournerait à chaque
démarrage = perte de données). Donc : **intégré au script wipe P.6**, sous
garde-fou interactif, atomique avec le wipe des données.

| Table | Modification |
|---|---|
| `coin_observations` | drop+recreate avec `source_ref TEXT` + FK source |
| `coin_market_quotes` | drop+recreate avec `source_ref TEXT` + FK source |
| `referential_catalog` | drop+recreate avec FK source + audit `country_name` normalisé à l'ingestion |
| `coin_canonical_images` | drop+recreate avec FK source |
| `coin_aliases` | drop+recreate avec FK source |
| `coin_names_i18n` | drop+recreate avec FK source |
| `coins` | Marquer `raw_payload_json` deprecated (à dropper post-wipe) |

**Conséquence** : aucune row ne peut être écrite avec un `source` qui n'est pas seedé en `source_registry`. Le chunk **P.3b** (nouveau) patche les producers (`ml/sources/ebay/`, `ml/sources/bce/`, `ml/scripts/refetch_numista_*`, bootstrap scripts) pour utiliser le vocabulaire registry (`ebay_browse`, `numista_api`, `mdp`, ...) avant le premier insert post-P.3.

---

## 6. Pipeline de validation — 3 niveaux de slice

```
PREP (P.1-P.9)
   │
   ▼
BACKUP + TEST RESTAURATION (non négociable)
   │
   ▼
WIPE (avec garde-fou interactif)
   │
   ▼
BENCH SINGLE-NID 10069 (Bremen) — B.1-B.5
   │  → Numista API, Numista HTML scrape, 2euros.org, BCE
   │  → Sortie : matrice champ × source dans `bench-single-NID-10069.md`
   ▼
COHORTE 19 (mix-zone-17 + Bremen + Bleuet + Treaty of Rome) — V.1-V.4
   │  → Refetch Numista + BCE + eBay sur les 18
   │  → Tour admin VISUEL par Raphaël (non négociable)
   ▼
GO / NO-GO
   │
   ▼
SCALE 524 (out-of-scope cette session) — F.*
```

**3 niveaux** (et non 2 comme initialement écrit) parce que Bremen seul nous
permet de **comprendre le format Numista vs 2euros.org** avant de généraliser
le scraper.

**Pas de rollback automatique en cas d'échec.** On discute avant.

---

## 7. La cohorte de validation — 19 coins (clés NID)

**Décision 2026-05-25 (P.1 finding)** : la cohorte est **clé NID Numista**, pas
eurio_id. Pourquoi : Numista renomme régulièrement ses titres ; les slugs
eurio_id sont recomputés à chaque refetch via `numista_eurio_id.py`. Stocker
des eurio_ids "promis" en amont du refetch les rendrait fragiles. Les NIDs
sont stables.

`mix-zone-17` (16 NIDs du cohort_id `bdc640b9f9c6`) + 3 ajouts ciblés :
- **NID 10069** (Bremen Bundesländer) — cas-fil-rouge 5 ateliers × 3 issue_types
- **NID 134283** (Bleuet de France ; Coloured) — valide la chaîne `coin_variants`
- **NID 2162** (Treaty of Rome 2007 DE) — valide `design_groups` joint-issue
  **et** stresse mint-releases DE multi-ateliers

Liste complète et descriptive dans `ROADMAP-DB.md` §6. Liste machine-readable :
`ml/state/cohort_validation_19.txt` (1 NID/ligne, commentaires `#` autorisés).

**Le tour admin V.4** inspecte par NID + label descriptif. Les eurio_ids
canoniques produits par le refetch sont une **sortie** de V.1, pas une
entrée. Tout rename eurio_id détecté en V.4 est tracé via `eurio_id_migrations(kind='rename')`.

---

## 8. Les 3 premiers chunks à attaquer

Ordre **strict**, dépendances réelles :

### P.1 — Audit + golden tests `eurio_id_from_numista_payload()`

- Fichier canonique : `ml/referential/numista_eurio_id.py`
- Doublons à supprimer (après tests) :
  - `ml/referential/audit_apply_common.py:303` (`eurio_id_from_catalog`)
  - `ml/referential/apply_3f_standards.py:104` (`standard_slug`)
- Golden cases à couvrir dans `tests/referential/test_eurio_id.py` :
  - **LV-2018** Zemgale vs Baltic States (2 nids même tuple)
  - **BE-2017** Gand vs Liège
  - **FR-2010** Appel du 18 juin vs Speech of June 18th 1940 (même pièce, 2 libellés)
  - **DE-2009** Saarland (avait été matché à EMU joint-issue par V1)
  - **NL-2015** EU Flag (joint-issue)
  - **FR-2018** Bleuet (2 colored distincts → variant)
  - **DE-2010** Bremen city-hall (cas-fil-rouge bench)
- Si la pure function donne le bon slug pour les 7 cas → ✅

### P.2 — Audit + tests `country_to_iso2()`

- Fichier canonique : `ml/referential/eurio_referential.py:210`
- Cas à tester :
  - `"Germany"` / `"Germany, Federal Republic of"` / `"Deutschland"` → `"DE"`
  - `"European Union"` → `"eu"`
  - `"Andorra"`, `"Monaco"`, `"San Marino"`, `"Vatican City"` → `AD`, `MC`, `SM`, `VA`
  - Bulgarie (joined eurozone 2026-01-01) → `BG`

### P.3 — Migration `ml/state/schema.sql`

- Ajout des 8 nouvelles tables (cf. §5.1)
- Ajout `source_ref` + FK `source` sur `coin_observations` et `coin_market_quotes`
- **Pas** de DROP `coins.raw_payload_json` (différé post-wipe pour éviter
  casse temporaire)
- Bootstrap idempotent via `state/store.py::_bootstrap` (`_ensure_column`
  pour les ALTER)
- Test : relancer le store sur une DB existante = noop, sur une DB clean =
  toutes les tables créées

Total ~5h. Après quoi P.4 (seed source_registry) + P.5 (backup test) + P.6
(wipe script) sont des chunks ≤ 1h chacun.

---

## 9. Ce qu'il NE FAUT PAS faire dans cette session implémentation

- ❌ **Lancer le refetch Numista** sur > 1 pièce (le bench B.1-B.2 c'est 1
  pièce avec 3 calls API max)
- ❌ **Exécuter le wipe** avant d'avoir validé la restauration du backup
  (P.5 non négociable)
- ❌ **Toucher à `supabase/migrations/`** — toute nouvelle table va dans
  `ml/state/schema.sql`
- ❌ **Modifier les pure functions** sans avoir d'abord écrit les tests
  golden (P.1 est test-first)
- ❌ **Pousser dans `coin_observations` sans `source`** (la FK le bloquera
  de toute façon post-P.3)
- ❌ **Faire un sync sortant vers Supabase** (out-of-scope, sera traité
  séparément)
- ❌ **Implémenter Chantier A (cote weekly)** — bloqué par discovery, non
  prioritaire

---

## 10. Sync Supabase — note pour le futur

Quand Android sera prêt :
- SQLite admin = **vue d'ensemble** pour comprendre le domaine euro +
  entraîner le modèle. Beaucoup de données (inscriptions multilingues,
  sales archive, frequency par variant, séries, observations brutes
  multi-source) **ne seront pas nécessaires dans Supabase**.
- Un **script de sync explicite** sera écrit pour push uniquement ce dont
  Android a besoin. **Pas de miroir 1:1**.
- Schéma Supabase = subset filtré du schéma SQLite, à figer quand le besoin
  produit Android sera précis.

---

## 11. Questions tranchées (2026-05-25)

1. **Joint-issue dans la cohorte** → ✅ **on ajoute**. Choix :
   `de-2007-2eur-treaty-of-rome` (stresse à la fois la chaîne `design_groups`
   ET la dimension multi-ateliers DE — double valeur dans la même slot).
   **Cohorte = 19 coins** (16 mix-zone-17 + Bremen + Bleuet + Treaty of Rome).
2. **Tests golden — fixtures source** → ✅ **payloads Numista réels**
   stockés en `tests/fixtures/numista/<nid>.json`. Capture une seule fois,
   committés. Plus de valeur de régression que les synthétiques.
3. **`refetch_numista_2eur.py`** → ✅ **fichier liste**.
   `--eurio-ids-file <path>` (un eurio_id par ligne, commentaires `#` autorisés).
   Le fichier de la cohorte vivra en `ml/state/cohort_validation_19.txt`,
   versionné.
4. **Endpoint admin minimum pour V.4** → 🟡 **décidé au moment de V.4**,
   selon ce qu'il faudra voir pour trancher GO/NO-GO sur les 18 coins.
   Hypothèse de départ : page détail seulement. Si le tour visuel exige de
   voir le mintage en table ou la cote en chart pour juger, on étend à ce
   moment. Pas de pré-engagement.
5. **Test restauration backup (P.5)** → 🟡 **default proposé** :
   counts sur toutes les tables wipées (égalité stricte avec pré-wipe) +
   1 sample query métier (ex : "page coin détail pour `de-2010-2eur-bremen-presidency`
   renvoie bien ses observations et son canonical_image"). À durcir si on
   doute. Recommandation : commencer minimal, escalader si une anomalie
   est détectée.

---

## 12. Glossaire rapide

- **Type** = pièce canonique (eurio_id, design, country, year, denom). 1 ligne `coins`.
- **Variant** = finition graphique d'un Type (classic / coloured / hologram / ...). 0..N par Type.
- **Mint Release** = émission d'un Type par (atelier, année, format=BU/BE/CIRC). 0..N par Type.
- **Specimen** = la pièce physique dans le coffre de l'utilisateur (Phase 5+).
- **Observation** = fact attribué à une source. Pattern provenance first-class.
- **Provenance** = la source. FK `source_registry(id)`.
- **2euros.org** = source d'**enrichissement** (≠ référentiel — n'ajoute pas
  de pièce nouvelle, enrichit ce que Numista/BCE ont identifié).

---

## 13. Mantras de session

- **Backup testé avant tout acte destructif** (P.5 non négociable).
- **3 niveaux de slice** : 1 pièce → 19 → 524. Pas de scale sans validation visuelle.
- **Pas de rollback auto** : si la cohorte échoue, on discute avant de remonter.
- **SQLite first, Supabase later**.
- **Provenance first-class, multi-source = multi-row.**

---

## 14. Chantier différé — Source SDK

Conception différée **post-cohorte 19**. Voir `docs/sources-refacto/sdk-kickoff.md` (doc vivante).

Idée : protocol Python `ReferentialSourceAdapter` + runner partagé qui injecte la `source` depuis `source_registry`, applique l'idempotence via les UNIQUE canoniques, et expose une couche `EurioIdResolver` réutilisée par toutes les sources (au lieu de réinventer le matcher à chaque fois). Ordre de portage prévu : BCE → Numista → 2euros.org → Bundesbank → eBay.

**À capturer pendant la cohorte** (cf. sdk-kickoff.md §6-7) : nouveaux `observation_type`, heuristiques de matching, cas de divergence multi-source, payloads résistants à la modélisation. Ces findings nourriront la conception du SDK sans qu'on ait à re-deviner après coup.

---

## 15. État final attendu à la fin de la session implémentation

À la fin de la session "implémentation" qui démarre depuis ce kickoff :

- ✅ P.1-P.9 terminés (prep complète, ~14-15h)
- ✅ Backup testé, restauration vérifiée
- ✅ Wipe exécuté (DB référentielle vidée)
- ✅ Bench single-NID 10069 réalisé, matrice champ × source documentée
- ✅ Cohorte 19 refetchée + branchements BCE/eBay
- ✅ Tour admin visuel par Raphaël (GO/NO-GO décision)

**Ce qui reste pour une session ultérieure** :
- F.* — scale aux 524 coins
- Chantier A — cote eBay weekly (quand discovery sera prêt)
- Chantier B — rareté dérivée (quand A+C donneront du signal)
- Chantier E — UI admin riche au-delà du minimum V.4
- Sync sortant SQLite → Supabase (quand Android aura un besoin précis)
