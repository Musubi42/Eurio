# Référentiel de données Eurio — architecture

> Document d'architecture du référentiel canonique des pièces et de la pipeline de matching multi-sources.
> Date : 2026-04-13. État : architecture figée, implémentation en Phase 2C.

---

## 1. Problème à résoudre

Eurio agrège de la donnée de plusieurs sources externes hétérogènes : BCE/JOUE, lamonnaiedelapiece.com, eBay, Monnaie de Paris, Numista, et potentiellement d'autres. Chaque source identifie les pièces à sa manière (SKU propriétaire, ID Numista, nom libre, image, etc.).

Pour que l'application fonctionne correctement, il faut répondre à trois questions :

1. **Identité canonique** — quelle est *la* pièce dont on parle, indépendamment de la source ?
2. **Entity resolution** — comment savoir qu'un produit sur la source X et un produit sur la source Y désignent la même pièce ?
3. **Résilience** — si une source disparaît (décommission d'API, fermeture, ToS), comment Eurio continue de fonctionner ?

Ce document décrit l'architecture qui répond à ces trois questions, et qui sera implémentée en **Phase 2C — Référentiel de données**.

---

## 2. Principes directeurs

1. **Le référentiel est indépendant de toute source externe.** Aucune source ne peut invalider le référentiel en disparaissant. Les sources enrichissent, elles ne créent pas.
2. **Les IDs canoniques Eurio sont reconstructibles** depuis les attributs structurels d'une pièce. Pas besoin de consulter une base pour deviner l'ID d'une pièce qu'on connaît.
3. **Identité immuable, observations mutables.** Les faits structurels d'une pièce (pays, année, valeur faciale, design) ne changent jamais. Les observations (prix, disponibilité, cross-refs) évoluent en continu.
4. **Snapshots sources immuables.** Chaque scraper écrit un fichier daté qu'on ne modifie plus. Le référentiel final est un merge reconstructible depuis les snapshots.
5. **Pas d'auto-variante.** Si le système ne peut pas trancher entre deux pièces candidates, il ne crée jamais de `v2` automatiquement. Il met la décision en file d'attente humaine.
6. **Audit trail complet.** Chaque décision de matching est loggée avec la méthode et la confidence.

---

## 3. Format de l'ID canonique Eurio

### 3.1 Structure

```
{country_iso2}-{year}-{face_value_code}-{design_slug}
```

- **`country_iso2`** : code pays ISO 3166-1 alpha-2 en minuscules (`fr`, `de`, `hr`, `va`, `mc`, `sm`, `ad`)
- **`year`** : année d'émission (4 chiffres)
- **`face_value_code`** : code compact de la valeur faciale :
  - `1c`, `2c`, `5c`, `10c`, `20c`, `50c` pour les centimes
  - `1eur`, `2eur` pour les euros
- **`design_slug`** : slug kebab-case du thème commémoratif. Pour les pièces de circulation standard : `standard`

### 3.2 Exemples

```
hr-2025-2eur-amphitheatre-pula            (Croatie 2025 commémorative Pula)
de-2006-2eur-schleswig-holstein           (Allemagne 2006 commémorative)
de-2022-2eur-erasmus                      (Allemagne 2022, Erasmus)
de-2022-2eur-traite-elysee                (Allemagne 2022, Traité de l'Élysée — distinct de Erasmus)
fr-2012-2eur-10ans-euro                   (France 2012, 10 ans de l'euro)
fr-2020-2eur-standard                     (France 2020, pièce de circulation standard)
va-2005-2eur-annee-eucharistie            (Vatican 2005)
eu-2015-2eur-drapeau-europeen-30-ans      (Émission commune 2015)
```

### 3.3 Règle de disambiguation

Si deux pièces distinctes produisent le même ID après slugification (collision vraie), la seconde prend un suffixe `-v2`, la troisième `-v3`, etc. Ce suffixe **n'est jamais assigné automatiquement** par un scraper : il est décidé lors d'une résolution manuelle dans la `review_queue`.

### 3.4 Cas des émissions communes — Option A (une entrée canonique)

Les émissions communes zone euro (où tous les pays émettent le même design) sont identifiées par le pseudo-pays `eu` :
```
eu-2022-2eur-erasmus                      (35 ans Erasmus, 19 pays)
eu-2015-2eur-drapeau-europeen             (30 ans drapeau européen, 19 pays)
eu-2012-2eur-10ans-euro                   (10 ans euro fiduciaire, 17 pays)
eu-2009-2eur-uem-10ans                    (10 ans UEM, 16 pays)
eu-2007-2eur-traite-rome                  (50 ans Traité de Rome, 13 pays)
```

Chaque pays a sa propre variante physique avec des poinçons nationaux différents, mais le design obverse est identique. Pour Eurio on considère que c'est **une seule pièce canonique unique** enrichie de N pays participants.

**Modélisation** : `identity.national_variants = ["AT", "BE", "DE", ...]` dans l'entrée canonique. Les volumes par pays, quand ils sont connus, vont dans `observations.mintage.by_country`. Ce choix (Option A, figé en 2026-04-13) privilégie la compacité et la cohérence sémantique sur la granularité. Si un jour on a besoin de stocker des observations prix par variante nationale, on migrera vers un modèle parent/enfants.

**Liste exhaustive et définitive** (avril 2026, vérifié) : 5 émissions communes au total. Aucune programmée pour 2025 ou 2026.

---

## 4. Schema du référentiel

Chaque entrée a **4 couches** distinctes :

### 4.1 Identity (immuable)

Les faits structurels qui définissent la pièce. Une fois écrits, jamais modifiés par un scraper.

```json
{
  "eurio_id": "hr-2025-2eur-amphitheatre-pula",
  "identity": {
    "country": "HR",
    "country_name": "Croatie",
    "year": 2025,
    "face_value": 2.0,
    "currency": "EUR",
    "is_commemorative": true,
    "theme": "Amphithéâtre de Pula",
    "design_description": "Vue de l'amphithéâtre romain de Pula, 1er siècle",
    "national_variants": null,
    "joue_reference": "C/2025/XXX"
  }
}
```

### 4.2 Cross-refs (additif par source)

Chaque scraper ajoute son propre ID natif sans toucher ceux des autres.

```json
{
  "cross_refs": {
    "numista_id": null,
    "joue_code": "C/2025/XXX",
    "lmdlp_sku": "hr2025amphitheatre",
    "lmdlp_url": "https://lamonnaiedelapiece.com/fr/product/...",
    "monnaiedeparis_sku": null,
    "ebay_leaf_category": "32650",
    "km_code": null
  }
}
```

### 4.3 Observations (namespacé par source)

Données mutables, chaque source a son propre slot, elles ne se marchent jamais dessus.

```json
{
  "observations": {
    "lmdlp_current": {
      "price": 28.99,
      "currency": "EUR",
      "quality": "UNC",
      "packaging": "coincard",
      "in_stock": true,
      "sampled_at": "2026-04-13T12:34:56Z"
    },
    "monnaiedeparis_issue": null,
    "ebay_market": {
      "p25": null,
      "p50": null,
      "p75": null,
      "samples_count": 0,
      "sampled_at": null
    },
    "mintage": {
      "total": 190000,
      "by_mint": {},
      "source": "lmdlp",
      "fetched_at": "2026-04-13"
    }
  }
}
```

### 4.4 Images (multi-source)

```json
{
  "images": [
    {
      "url": "https://lamonnaiedelapiece.com/.../croatia-2025-pula.jpg",
      "source": "lmdlp",
      "role": "obverse",
      "fetched_at": "2026-04-13"
    }
  ]
}
```

### 4.5 Provenance (audit)

```json
{
  "provenance": {
    "first_seen": "2026-04-13",
    "last_updated": "2026-04-13",
    "sources_used": ["joue", "lmdlp"],
    "needs_review": false,
    "review_reason": null
  }
}
```

---

## 5. Pipeline de matching multi-stage

Quand un scraper trouve un produit sur une source externe, il doit trouver à quel `eurio_id` ce produit correspond. Le matching se fait en 5 stages avec confidence décroissante.

### Stage 1 — Exact cross-ref (confidence 1.00)

La source liste directement un identifiant externe qu'on connaît déjà (Numista ID, code JOUE, code Krause KM). Match direct, zéro ambiguïté.

```
source.numista_id == referentiel[*].cross_refs.numista_id
→ match trouvé, confidence 1.00
```

### Stage 2 — Structural key unique (confidence 0.95)

`country + year + face_value` identifient une unique pièce dans le référentiel. Happens quand un pays n'a qu'une commémorative dans l'année, ou qu'on cherche une pièce de circulation.

```
candidates = referentiel.filter(
  country=HR, year=2025, face_value=2.0
)
if len(candidates) == 1:
  → match, confidence 0.95
```

### Stage 3 — Structural + fuzzy design slug (confidence 0.80-0.95)

`country + year + face_value` renvoie 2 candidats (les deux commémos annuelles autorisées par pays). On désambiguïse par fuzzy matching du design slug.

```
candidates = referentiel.filter(country=DE, year=2022, face_value=2.0)
# → [de-2022-2eur-erasmus, de-2022-2eur-traite-elysee]

source_slug = slugify(source.title)  # "erasmus-programme-35th-anniversary"
scores = [
  levenshtein_ratio(source_slug, candidate.design_slug)
  for candidate in candidates
]

if max(scores) > 0.8 and unique_max:
  → match au meilleur score, confidence = max(scores)
else:
  → escalade au stage 4
```

### Stage 4 — Visual similarity (confidence 0.70-0.90)

Stage 4 utilise **le modèle d'embedding Eurio** (MobileNetV3 + ArcFace, entraîné en Phase 1/2B pour la reconnaissance scan). C'est le même modèle qui sert à identifier les pièces utilisateur.

```
source_image = download(source.image_url)
candidate_images = [download(c.images[0].url) for c in candidates]

source_embedding = model.embed(source_image)
candidate_embeddings = [model.embed(img) for img in candidate_images]

similarities = cosine_similarity(source_embedding, candidate_embeddings)

if max(similarities) > 0.85 and unique_max:
  → match, confidence = max(similarities)
else:
  → escalade au stage 5
```

**Important** : Stage 4 est **désactivé** tant que le modèle d'embedding n'est pas entraîné et déployé. Tant qu'on est en Phase 1/2B, la pipeline s'arrête à Stage 3 et escalade directement à Stage 5.

### Stage 5 — Review humaine

Aucun stage précédent n'a tranché. L'entrée est envoyée dans `review_queue` avec :
- Le produit source brut
- Les candidats possibles
- Les scores des stages précédents
- La raison de l'escalade

Un humain tranche via un script CLI interactif ou une page admin. La décision est écrite dans `matching_decisions` et propagée au référentiel.

---

## 6. Bootstrap depuis le JOUE / BCE

Avant même le premier scraper, on bootstrape le référentiel depuis la source canonique officielle : la **liste des 2€ commémoratives publiée au JOUE** (Journal Officiel de l'Union Européenne).

### 6.1 Ce qu'on récupère

Toutes les 2€ commémoratives depuis 2004 (premier millésime) jusqu'à l'année courante. Environ **450-500 entrées** en avril 2026. Chaque entrée contient :
- Pays émetteur
- Année
- Thème
- Volume d'émission autorisé
- Date d'émission approuvée
- Code de référence JOUE (`C/YYYY/NNN`)

### 6.2 Pipeline de bootstrap

```
1. Fetch la page BCE listant toutes les 2€ commémoratives
   (source : ecb.europa.eu/euro/coins/comm/html/index.en.html + JOUE)

2. Parser la liste pour extraire : country, year, theme, volume, joue_code

3. Pour chaque entrée :
   - Compute eurio_id canonique
   - Créer l'entrée référentiel avec identity + joue_reference
   - cross_refs.joue_code = JOUE code
   - Provenance : first_seen = today, sources_used = ['joue']

4. Ajouter les pièces de circulation standard (1c à 2€ × 21 pays × millésimes disponibles)
   - Source : pages BCE "National sides" + Wikipedia
   - Format : {country}-{year}-{face}-standard
   - Bootstrap manuel ou script CSV

5. Écrire ml/datasets/eurio_referential.json (première version)
```

Après ce bootstrap, le référentiel contient toutes les pièces canoniques. Les scrapers ne créent plus d'entrées, ils ne font qu'enrichir `cross_refs` et `observations`.

### 6.3 Émissions communes

Les 3-4 émissions communes (2007 Traité de Rome, 2009 UEM, 2012 10 ans de l'euro, 2015 drapeau, 2022 20 ans euro fiduciaire) sont cataloguées comme **entrées `eu-*`** uniques, avec `national_variants` listant les pays participants.

---

## 7. Organisation des fichiers

### 7.1 Layout dev-time (pendant itération du schema)

```
ml/datasets/
├── coin_catalog.json                   # existant, catalogue Numista — à migrer progressivement
├── eurio_referential.json              # source de vérité canonique
├── sources/
│   ├── joue_bootstrap_2026-04-13.json       # snapshot bootstrap initial
│   ├── lmdlp_2026-04-13.json                # snapshot lamonnaiedelapiece
│   ├── ebay_2026-04-13.json                 # snapshot eBay
│   ├── monnaiedeparis_2026-04-13.json       # snapshot Monnaie de Paris
│   └── numista_2026-04-13.json              # snapshot Numista (pour cross-ref)
├── matching_log.jsonl                   # append-only, une ligne par décision
└── review_queue.json                    # entrées en attente humain
```

### 7.2 Layout runtime (une fois schema stable → Supabase)

```
Tables Supabase :
- coins                : référentiel canonique
- source_observations  : time-series des observations par source
- matching_decisions   : audit trail des décisions
- review_queue         : entrées en attente
```

Un script `ml/sync_to_supabase.py` pousse le JSON vers les tables. L'app Kotlin lit depuis Supabase, jamais depuis le JSON.

### 7.3 Schema SQL cible

```sql
create table coins (
  eurio_id          text primary key,
  country           char(2) not null,
  year              int not null,
  face_value        numeric not null,
  is_commemorative  boolean not null default false,
  theme             text,
  design_description text,
  joue_reference    text,
  national_variants jsonb,
  needs_review      boolean not null default false,
  review_reason     text,
  first_seen        date not null,
  last_updated      timestamptz not null default now()
);

create index idx_coins_country_year on coins(country, year);
create index idx_coins_needs_review on coins(needs_review) where needs_review = true;

create table source_observations (
  id              bigserial primary key,
  eurio_id        text not null references coins(eurio_id) on delete cascade,
  source          text not null,            -- 'lmdlp', 'ebay', 'mdp', 'numista', 'joue'
  source_native_id text,                    -- sku / id côté source
  price           numeric,
  currency        char(3),
  quality         text,                     -- 'BU', 'BE', 'UNC', 'circulated', ...
  packaging       text,                     -- 'coincard', 'blister', 'bulk', 'roll'
  in_stock        boolean,
  url             text,
  image_url       text,
  raw_payload     jsonb,                    -- archive complète au cas où
  sampled_at      timestamptz not null,
  unique(source, source_native_id, sampled_at)
);

create index idx_obs_eurio_id on source_observations(eurio_id);
create index idx_obs_source_time on source_observations(source, sampled_at desc);

create table matching_decisions (
  id              bigserial primary key,
  source          text not null,
  source_native_id text not null,
  eurio_id        text not null references coins(eurio_id),
  method          text not null,           -- 'stage1_crossref', 'stage2_struct', ...
  confidence      numeric not null,
  human_reviewed  boolean not null default false,
  reviewer_notes  text,
  decided_at      timestamptz not null default now()
);

create table review_queue (
  id              bigserial primary key,
  source          text not null,
  source_native_id text not null,
  raw_payload     jsonb not null,
  candidates      jsonb,                    -- liste de eurio_id possibles
  reason          text not null,
  created_at      timestamptz not null default now(),
  resolved        boolean not null default false,
  resolution      jsonb                     -- ce qui a été fait
);
```

---

## 8. Résilience

### 8.1 Si une source disparaît

Le référentiel reste intact. Les `cross_refs.{source}` et `observations.{source}` deviennent obsolètes, mais les autres sources continuent de fournir de la data. L'identité de chaque pièce reste garantie par le bootstrap JOUE initial.

### 8.2 Si Numista ferme l'API

Aucun impact sur l'identité du référentiel. Seul le cross-ref Numista devient figé. On perd une source mais on garde tout le reste.

### 8.3 Si le format d'une source change

Le scraper correspondant cesse de parser correctement, log des erreurs. On fixe le parser. Les snapshots précédents restent exploitables (ils sont immuables). Aucune autre source n'est affectée.

### 8.4 Si on veut changer de backend

Le référentiel est en JSON git. On peut partir vers n'importe quelle stack (Postgres, SQLite, DynamoDB) en écrivant un nouveau script de sync. Les données ne sont jamais prisonnières d'une techno.

---

## 9. Limitations connues

- **Scope initial = 2€ commémoratives et circulation euro.** Les médailles, jetons, pièces d'investissement or/argent, monnaies anciennes sont hors scope.
- **L'entity resolution n'est pas parfaite.** Les cas limites tombent en review humaine. On accepte un taux d'escalade non nul, surtout avant que Stage 4 (visual) ne soit activé.
- **Le JOUE ne contient que les commémoratives approuvées officiellement.** Les pièces de circulation standard doivent être bootstrapées depuis une autre source BCE ou manuelle.
- **Stage 4 (visual) dépend du modèle ArcFace de Phase 2B.** Avant cela, on fonctionne en 3 stages + review humaine, avec un taux d'escalade plus élevé.

---

## 10. Liens croisés

- **Phase d'implémentation** : [`docs/phases/phase-2c-referential.md`](../phases/phase-2c-referential.md)
- **Pipeline de prix eBay** : [`docs/research/ebay-api-strategy.md`](./ebay-api-strategy.md)
- **Cartographie écosystème euro** : [`docs/research/euro-ecosystem-map.md`](./euro-ecosystem-map.md)
- **Phase catalogue ML** : [`docs/phases/phase-2b-arcface-catalog.md`](../phases/phase-2b-arcface-catalog.md) — le modèle d'embedding entraîné ici sert aussi au Stage 4 du matching
- **Phase coffre** : [`docs/phases/phase-3-coffre.md`](../phases/phase-3-coffre.md) — dépend du référentiel pour les prix
