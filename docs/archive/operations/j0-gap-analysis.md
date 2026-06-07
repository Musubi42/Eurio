# J0 gap analysis — 72 classes à 0 canonical image

> **Contexte** : le dashboard `/operations` (livré 2026-05-24) révèle que 72 / 553
> classes commémoratives 2 € n'ont **aucune image canonique** (`coin_canonical_images`
> vide). Ces classes sont bloquées pour le training (J5) tant que ce trou n'est
> pas comblé. Ce doc est la recherche racine pour décider du chunk suivant.

> **Date** : 2026-05-24 · **Auteur** : session Claude / Raphaël

---

## TL;DR

Le trou J0 est dû à **deux causes structurelles distinctes**, pas à un seul bug.
Comprendre la décomposition est nécessaire avant de coder le fix, sinon on
résout 14 cas en ignorant les 58 autres.

| Cause | n classes | Nature | Mitigeable ? |
|---|---|---|---|
| **Per-coin Numista detail jamais fetché** | **58** | Pipeline incomplète : la *catalog list* ne contient pas les image URLs ; il faut un appel par coin. | ✅ Oui — appel API Numista quota ≤ 60. |
| **BCE n'a pas d'image officielle pour ces coins** | **14** | Lacune réelle de la source officielle (gaps Numista catalog + BCE matching échoué). | ⚠️ Requiert source alternative (Wikipedia, scraping page Numista HTML, ou skip). |

**Décision proposée** : couvrir les 58 en priorité via un script
`enrich_missing_payloads.py` qui appelle l'endpoint per-coin Numista pour
chaque `numista_id` à `raw_payload_json` vide. Les 14 sont traités dans un
deuxième chunk (recherche dédiée Wikipedia / numista-html).

---

## Pipeline actuelle reconstituée

```
┌──────────────────────┐   ┌──────────────────────────┐
│ Numista catalog list │──▶│  referential_catalog     │  (raw_json sans images)
└──────────────────────┘   └─────────────┬────────────┘
                                         │
                              scripts/generate_missing_coins.py
                                         │
                                         ▼
                           ┌──────────────────────────┐
                           │  coins (eurio_id, …)     │
                           │  raw_payload_json = ""   │  ◀── 58 classes ici
                           └──────────────────────────┘

┌──────────────────────┐
│ BCE comm_{year}.html │──▶  eurio_referential.json  ──▶  (sync vers coins.raw_payload_json
└──────────────────────┘     (4.2 MB, daté 2026-04-28)      ne s'est pas refait depuis le
        │                                                    bootstrap initial)
        │
        └─── matching_log.jsonl (decisions par stage 1-5)
```

Quand `migrate_canonical_schema.py` (chunk 1b) extrait les images depuis
`raw_payload_json` vers `coin_canonical_images`, il ne peut rien faire pour
les 58 rows à payload vide.

---

## Cause #1 : 58 classes — pipeline per-coin Numista incomplète

### Symptômes observés

- `coins.raw_payload_json IS NULL OR = ''` pour 148 / 614 coins commémoratifs
- Parmi les 72 zero-canon classes, **58 sont dans ce cas**
- Toutes ont un `numista_id` valide et `ref_source='numista'`
- Aucune n'est dans `eurio_referential.json` (slugs nouveaux non back-portés)

### Vérification

```sql
SELECT json_extract(raw_json, '$.obverse_image_url') FROM referential_catalog
 WHERE source='numista' AND source_native_id IN ('132936','102697','8108');
-- → all NULL
```

Confirmé : la table `referential_catalog` est alimentée par l'endpoint
**catalog list** Numista qui retourne seulement les champs identité, jamais
les image URLs (cf. clés du raw_json : `numista_id, name, country, year,
face_value, type, diameter_mm, weight_g, composition,
obverse_description, reverse_description`).

### Distribution annuelle

| Année | n | Année | n |
|---|---|---|---|
| 2008 | 2 | 2018 | 5 |
| 2009 | 3 | 2019 | 2 |
| 2012 | 1 | 2020 | 3 |
| 2014 | 4 | 2021 | 6 |
| 2015 | 7 | 2022 | 9 |
| 2017 | 3 | 2023 | 4 |
| | | 2024 | 4 |
| | | 2025 | 5 |

Étalé sur toute la décennie — pas un effet "nouveaux coins manquants".
C'est l'absence d'un step de pipeline, pas un retard de scrape.

### Fix proposé — Chunk `enrich-missing-payloads`

1. **Script** : `ml/scripts/enrich_missing_payloads.py`
   - Itère sur `coins` où `raw_payload_json IS NULL OR raw_payload_json = ''`
   - Appel Numista per-coin : `GET https://api.numista.com/api/v3/types/{numista_id}`
     (auth `Numista-API-Key` header, lang `en`)
   - Écrit la réponse complète dans `coins.raw_payload_json`
2. **Migration** : re-run `scripts/migrate_canonical_schema.py` qui extrait
   `images.obverse / images.reverse` depuis le payload vers `coin_canonical_images`
3. **Coût quota** : 148 calls API (24 % d'un cycle mensuel ≈ 2000) — acceptable
4. **Idempotent** : déjà-fait ⇒ skip via filtre `WHERE raw_payload_json IS NULL`

**Done quand** : dashboard `/operations` montre `n_red` baisser et histogram
`bucket=0` passer de 72 à ~14.

### Hypothèse alternative à vérifier (rapide)

L'endpoint per-coin Numista pourrait être **incomplet** pour certains coins
(API renvoie `images: []`). Sur la prod, l'endpoint est documenté comme
fournissant `obverse.picture` / `reverse.picture`. Sample-tester sur 3 IDs
(132936 helmut-schmidt, 102697 rodin, 8108 louis-braille) avant d'écrire le
script complet.

---

## Cause #2 : 14 classes — BCE n'a pas d'image, Numista non plus

### Symptômes

- 14 classes ont `raw_payload_json` rempli mais `identity.images` est vide ou `null`
- Toutes apparaissent dans `eurio_referential.json` côté ref mais sans images
- Sur le journal `matching_log.jsonl`, leur stage de matching BCE est `5` (no match)
  ou bien BCE n'a simplement pas affiché ce coin sur sa page annuelle

Exemples : `it-2009-2eur-louis-braille`, `mt-2017-2eur-hagar-qim`,
`gr-2013-2eur-2400th-anniversary-of-the-founding-of-the-platonic-academy`.

### Sources alternatives candidates

| Source | Pros | Cons |
|---|---|---|
| **Numista page HTML** (scrape direct la page coin) | Numista héberge tj 1 photo userland | Pas dans l'API gratuite, scrape WAF (cf. probe 2026-05-19) |
| **Wikipedia commémo pages par pays** | Photos officielles 2008+ | Couverture incomplète, format hétéro |
| **eBay top result** (un seul listing reviewé manuellement) | Disponible tout de suite, photos réelles | Pas "canonical" — image variable |
| **Skip ces 14 classes** | Pas de travail | Training v2 a 14 classes en moins, biais |

Décision : **deferred au chunk suivant** une fois les 58 résolus. Revisiter
quand le dashboard montre que ces 14 sont les dernières zero-canon.

---

## Effort & dépendances

| Chunk | Effort | Bloque | Bloqué par |
|---|---|---|---|
| Sample-test Numista per-coin (3 IDs) | 10 min | — | Quota Numista OK |
| `enrich_missing_payloads.py` + run | 1 h | — | sample-test ✓ |
| Re-run `migrate_canonical_schema.py` | 5 min | — | enrich ✓ |
| **Total fix 58 classes** | **~1 h 15** | training v2 less biased | — |
| Recherche sources pour 14 restantes | 1-2 h | — | fix 58 ✓ + dashboard confirmation |

---

## Risques

- **Quota Numista** : 148 calls = 7 % du mois. Si on cumule avec d'autres
  enrichissements, surveiller `api_call_log` sur la fenêtre.
- **Schéma payload incohérent** : la réponse per-coin Numista a peut-être
  une structure différente du référentiel JSON. À vérifier au sample-test.
- **Slug drift** : 58 eurio_ids DB ≠ 553 eurio_ids referential JSON. Le fix
  ici **n'unifie pas** les slugs — il enrichit les rows DB existantes par
  leur numista_id. La réconciliation slug est un chantier séparé (probablement
  jamais nécessaire si on garde DB comme source de vérité).

---

## Liens

- Spec dashboard : `docs/operations/dashboard-j1.md`
- Roadmap globale : `docs/roadmap.md`
- Harmonisation : `docs/data-harmonization/`
- Memory clé : `project_data_referential`, `project_data_harmonization`
- Code : `ml/scripts/generate_missing_coins.py`, `ml/scripts/migrate_canonical_schema.py`,
  `ml/referential/scrape_bce_images.py`
