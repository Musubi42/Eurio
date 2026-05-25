# Findings — Numista API (live data)

> Capturés au fil des sessions P.7+ (refetch SQLite-target) et benchs B.1+
> (validation cohorte). Source de vérité pour la conception du transform
> layer (P.7c) et l'agrégation B.5 (matrice champ × source).
>
> Date d'ouverture : 2026-05-26 (session P.7b — smoke Bremen NID 10069).

---

## 1. Cas-fil-rouge — Bremen NID 10069 (B.1 partiel)

### 1.1 Endpoints utilisés

```
GET /v3/types/10069                        → 1 call
GET /v3/types/10069/issues                 → 1 call → renvoie 15 issues
GET /v3/types/10069/issues/{iid}/prices    → 15 calls (1/issue)
Total                                      = 17 calls
```

### 1.2 Grille issues — 5 ateliers × 3 issue_types confirmée

L'hypothèse du kickoff §10 ("grille 5 ateliers × 3 issue_types") est
**confirmée par la donnée live**. Bremen 2010 = 15 issues :

| Atelier | CIRC          | BU set    | Proof  |
|---------|---------------|-----------|--------|
| A       | 6 000 000     | 98 800    | 95 900 |
| D       | 6 300 000     | 91 800    | 95 900 |
| F       | 7 200 000     | 91 800    | 95 900 |
| G       | 4 200 000     | 91 800    | 95 900 |
| J       | 6 300 000     | 91 800    | 95 900 |

**Total CIRC** : 30 M.
**Total BU + Proof** : ~940 k (≈3 % du CIRC).

### 1.3 Champs Numista par issue

```jsonc
// Issue 53447 (Bremen 2010 A circulation) — payload réel
{
  "id": 53447,
  "is_dated": true,
  "year": 2010,
  "gregorian_year": 2010,
  "mint_letter": "A",
  "mintage": 6000000
  // pas de "comment" → CIRC
}

// Issue 133445 (Bremen 2010 A BU set)
{
  "id": 133445,
  "year": 2010,
  "gregorian_year": 2010,
  "mint_letter": "A",
  "mintage": 98800,
  "comment": "BU set"
}

// Issue 99014 (Bremen 2010 A Proof)
{
  "id": 99014,
  "year": 2010,
  "gregorian_year": 2010,
  "mint_letter": "A",
  "mintage": 95900,
  "comment": "Proof"
}
```

### 1.4 Hierarchy issue_type ← `comment`

Le champ `comment` est **présent et déterministe** pour distinguer
issue_type. Mapping vers le CHECK constraint de `coin_mint_releases` :

| Numista `comment`           | Eurio `issue_type` |
|-----------------------------|--------------------|
| (absent / null / "")        | `CIRC`             |
| `"BU set"`                  | `BU`               |
| `"Proof"`                   | `PROOF`            |
| `"BE"` (peut apparaître FR) | `BE` (=PROOF FR)   |
| `"Coincard"`                | `COIN_CARD`        |

→ La fonction `_detect_issue_type()` du legacy script
(`ml/referential/refetch_numista_2eur.py`) gère déjà ces cas. **À
reprendre tel quel en P.7c**, juste re-localisée + couvrir par tests.

---

## 2. Endpoint `/prices` — structure des grades

Tous les `/issues/{iid}/prices` retournés ont **systématiquement** la
même structure : 7 grades dans cet ordre, `currency: EUR`.

```json
{
  "currency": "EUR",
  "prices": [
    {"grade": "g",   "price": 2},
    {"grade": "vg",  "price": 2},
    {"grade": "f",   "price": 2},
    {"grade": "vf",  "price": 2},
    {"grade": "xf",  "price": 2.07568},
    {"grade": "au",  "price": 2.07568},
    {"grade": "unc", "price": 3.11}
  ]
}
```

### 2.1 Mapping Numista (7) → Eurio (3 grades)

Cohérent avec `reference_numista_prices.md` et le legacy script :

| Eurio grade | Numista grades   | Stratégie d'agrégation                  |
|-------------|------------------|-----------------------------------------|
| `UNC`       | `unc`            | direct                                  |
| `TTB`       | `au`, `xf`       | max (AU ≥ XF en théorie, parfois égaux) |
| `TB`        | `vf`, `f`, `vg`  | max (VF est le seuil "lisible")         |
| —           | `g`              | ignoré (trop bas pour le marché Eurio)  |

### 2.2 Décision architecture — DOUBLE écriture P.7c

Stocker à **deux niveaux** (confirmé brainstorm 2026-05-26) :

1. **`mint_release_prices`** — granularité fine, 1 row par
   `(mint_release_id, source='numista_api', grade_raw, fetched_at)`.
   Stocke les 7 grades bruts (sauf `g` ignoré → 6 rows/issue) + le
   `grade_eurio` mappé. Conserve la richesse pour audit + future agrégation.
2. **`coin_market_quotes`** — Type-level agrégé, 1 row par
   `(eurio_id, source='numista_api', condition_normalized, period_start)`.
   Calcul P.7c : pour chaque grade Eurio (UNC/TTB/TB), prendre le **max**
   sur toutes les mint_releases du Type (toutes ateliers/issue_types
   confondus). `sample_size = N_issues × N_grades_in_bucket`.

### 2.3 Caveats prix Numista

- Prix `2.00` flat sur les bas grades (G/VG/F/VF) pour Bremen circulation
  = valeur faciale = pas de marché secondaire détecté par Numista. À
  considérer comme bruit, pas comme signal.
- `xf` et `au` peuvent être strictement égaux (cas Bremen 2.07568) — pas
  toujours strictement supérieur. Le max joue correctement.
- Les prix sont en EUR (param `currency=EUR`), conversion gérée par
  Numista. Stocker `currency='EUR'` brut.

### 2.4 **BU et Proof exposent uniquement le grade `unc`** (finding 2026-05-26)

Confirmé en P.7c.2 sur le cache Bremen complet : seules les issues CIRC
exposent les 7 grades. Les issues BU et Proof retournent **1 seul prix**
(`unc`).

Distribution réelle Bremen (15 issues, 30 calls /prices au total) :

| Issue type | Grades exposés                         | # rows /prices/issue |
|------------|----------------------------------------|----------------------|
| CIRC       | `g`, `vg`, `f`, `vf`, `xf`, `au`, `unc` | 7                    |
| BU set     | `unc`                                  | 1                    |
| Proof      | `unc`                                  | 1                    |

**Conséquences agrégation Type-level** (`coin_market_quotes`) :
- UNC bucket : N_circ + N_bu + N_proof prix (= N_issues total)
- TTB bucket : N_circ × 2 grades (au + xf)
- TB bucket  : N_circ × 3 grades (vf + f + vg)

Bremen exemple : UNC=15, TTB=10, TB=15.

**Cette asymétrie est logique** — BU et Proof sont des pièces neuves
sans gradation TTB/TB applicable. Ne pas tenter de "compléter" leurs
prix par interpolation.

---

## 3. Endpoint `/types/{nid}` — payload metadata

À explorer in extenso dans `bench-single-NID-10069.md` (B.1 complet).
Champs déjà identifiés présents (cf. legacy script transform layer) :

- `id`, `title`, `category`, `issuer`, `face_value`, `currency`
- `obverse.picture`, `obverse.picture_copyright`, `obverse.picture_license_name`
- `reverse.picture`, `reverse.picture_copyright`, `reverse.picture_license_name`
- `min_year`, `max_year`, `composition`, `weight`, `diameter`, `thickness`,
  `shape`, `orientation`, `edge` (TEXT description)
- `designers` (array) — pour `coin_credits`
- `numista_design_group` (parfois) — pour joint-issue detection

À documenter complètement en B.1.

---

## 4. Comportements opérationnels

### 4.1 Rate limiting

Pas de 429 observé sur 17 calls Bremen avec délai 0.4s. Le legacy
`KeyManager.call()` gère la rotation 429 automatiquement (slot suivant).

### 4.2 Cache disque P.7b

Layout : `ml/state/numista_cache/{nid}/{type,issues,prices_{iid}}.json`.
Idempotence : 2e run même NID = 0 API call, 17 cache hits. Permet de
développer P.7c (transform) sur les payloads cachés sans cramer le quota.

`--refresh-cache` force un re-fetch (utile si Numista renomme un titre).

### 4.3 Issues sans prices

Observé sur d'autres NIDs (legacy stat `prices_404`) : certaines issues
peuvent retourner 404 sur `/prices`. À traiter comme "pas de cote
disponible", pas comme erreur fatale. Le Fetcher P.7b log la 404 et
continue.

---

## 5. Findings P.7d — Bleuet (variant) + Treaty of Rome (joint-issue)

### 5.1 — NID 134283 Bleuet de France 2018 Coloured — VARIANT

Live fetch 2026-05-26 (3 calls : 1 type + 1 issues + 1 prices ; en fait
2 prices car 2 issues).

**Structure issues** (différente de Bremen) :
- **2 issues seulement** : 1 BU + 1 Proof. **Pas de CIRC.** Logique :
  les pièces coloured sont des collector items, jamais mises en circulation.
- 1 atelier seulement, `mint_letter = None` (Pessac, pas de lettre).
- Prices : 1 grade `unc` par issue (cohérent avec finding §2.4).

**Slug** : `eurio_id_from_numista_payload()` retourne
``fr-2018-2eur-bleuet-de-france`` (le **parent** classique, pas le variant
lui-même). `is_variant=True`, `variant_finish='coloured'`. Une row
``coin_variants`` capture le finish.

**Bug capturé P.7d** : l'attribut du dataclass est ``slug.variant_finish``,
pas ``slug.finish`` — bug initial dans ``coin_variant_row()``. Fix appliqué.

### 5.2 — NID 2162 Treaty of Rome 2007 DE — JOINT-ISSUE + MULTI-MINT

Live fetch 2026-05-26 (17 calls : 1 + 1 + 15 prices).

**Structure issues** (Bremen-like) :
- **15 issues** : 5 ateliers (A/D/F/G/J) × 3 issue_types (CIRC/BU/Proof).
- Confirme que la grille DE multi-ateliers s'applique aussi aux
  commémorations non-Bundesländer.

**Joint-issue** :
- `slug.is_joint_issue=True`, `slug.design_group_id='eu-rome-2007'`.
- ``design_groups`` row créée avec designation = "Treaty of Rome".
- ``coins.design_group_id`` lié.
- ⚠️ Le payload Numista n'expose **pas** ``numista_design_group``
  (vérifié : `numista_design_group=None`). C'est la **pure function**
  Eurio qui détecte le joint-issue depuis le titre ("Treaty of Rome").
  Les autres NIDs des autres pays devront produire le même
  `design_group_id` pour pointer vers la même row — testé via le slug.

### 5.3 — À documenter au fil des fetchs cohorte restants (V.1)

- [ ] **Standard circulation** : NID 64 (AT 2002 standard) — combien
      d'issues sur 25 ans d'émission ? Échelle des prix.
- [ ] **Designer Luycx** : confirmer que `engravers` array contient
      Luycx sur les reverse standards.
- [ ] **JOUE** : un coin commémo (ex: BE 2011 NID 19734) expose-t-il un
      lien JOUE dans le payload ?
- [ ] **Image license** : `picture_copyright` + `picture_license_name`
      — quelle license sur les commémos vs standards ?

---

## 6. Liens

- `docs/coin-richness/ROADMAP-DB.md` §10 — bench B.1 plan
- `docs/coin-richness/chantier-C-mintage.md` — analyse mintage croisée
- `docs/coin-richness/kickoff.md` — vision produit
- `ml/scripts/refetch_numista_2eur.py` — orchestrateur SQLite-target
- `ml/referential/refetch_numista_2eur.py` — legacy Supabase (DEPRECATED P.9)
- `ml/state/numista_cache/10069/` — payloads Bremen cachés (gitignored)
