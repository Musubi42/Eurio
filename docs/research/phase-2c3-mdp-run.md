# Phase 2C.3 — Run report scrape_monnaiedeparis.py

> Premier run du scraper Monnaie de Paris (prix d'émission officiels FR).
> Date : 2026-04-13.
> Doc parent : [`phase-2c-referential.md`](../phases/phase-2c-referential.md) §2C.3, [`data-referential-architecture.md`](./data-referential-architecture.md).

---

## TL;DR

17 produits 2€ commémoratives fetchés depuis le sitemap MDP, **100% matchés** (6 Stage 2 + 11 Stage 3, 0 escalation). 5 entrées canoniques enrichies avec leur prix d'émission officiel BU/BE. Aucun cas en review_queue.

| Métrique | Valeur |
|---|---|
| URLs dans le sitemap total | 1 900 |
| Produits 2€ commemo détectés | 17 |
| Match Stage 2 (structural unique) | 6 (35%) |
| Match Stage 3 (fuzzy slug) | 11 (65%) |
| Escalade Stage 5 | 0 |
| **Taux match auto** | **100%** |
| Entrées canoniques enrichies | 5 |

---

## 1. Fetch et filtrage

### Source

`GET https://www.monnaiedeparis.fr/media/sitemap/sitemap_mdp_fr.xml` → 1 900 URLs totales.

Filtrage via regex :
```
/fr/{theme_slug}-monnaie-de-2eur-commemorative(-belle-epreuve)?-qualite-{quality}-millesime-{year}
```

Exclusions :
- `rouleau-de-` (rolls de 25 pièces)
- `porte-cles` (accessoires)
- URLs tronquées sans année (ex: `...-millesime` sans suffixe)

**17 URLs** restantes, couvrant les années 2022, 2023, 2025, 2026.

### Pourquoi si peu ?

La MDP ne commercialise en ligne que :
- Les 2€ commemo des 2-3 dernières années (les anciennes passent en stock épuisé puis disparaissent du catalogue)
- Les deux quotas commémoratifs français annuels (ex: 2025 = Louvre + Notre-Dame)
- Le cas des joint issues (Erasmus 2022) encore en stock

Pas de catalogue rétroactif : pour les prix d'émission historiques, il faudra soit un archivage manuel (Phase 3 coffre), soit un scrape d'archives.org, hors scope actuel.

---

## 2. Extraction JSON-LD

Chaque page produit contient 4 blocs JSON-LD : `WebSite`, `BreadcrumbList`, `Product`, `WebPage`. On garde uniquement le `Product` schema :

```json
{
  "@type": "Product",
  "name": "Erasmus",
  "image": "https://.../catalog/product/C/o/Coincard_Erasmus_face_00af.png",
  "offers": {
    "price": 11,
    "priceCurrency": "EUR",
    "availability": "https://schema.org/OutOfStock",
    "url": "https://.../erasmus-monnaie-de-2eur-commemorative-qualite-bu-millesime-2022"
  }
}
```

**Gains par rapport à lmdlp** :
- Prix en EUR direct (pas de minor unit à diviser)
- Availability explicite (`InStock` / `OutOfStock` / etc.)
- Image SKU stable (filename sans extension)
- Pas de variantes de qualité multi-valuées par produit — chaque page = une qualité

**Pas disponible** :
- Mintage (il faudrait scraper les specs ou le PDF d'émission — pas dans schema.org)
- Artist / designer
- Series / subseries

---

## 3. Pipeline de matching

### Stage 2 — 6 matchs (35%)

Ce sont les cas où le pays + année renvoient un seul candidat dans le référentiel :
- **Le Petit Prince** (6 variantes) → `fr-2026-2eur-antoine-de-saint-exupery` (une seule commémo FR 2026)

Sémantiquement correct : la commémo 2026 est dédiée à Saint-Exupéry via son œuvre Le Petit Prince. Wikipedia catalogue par auteur, MDP vend par titre, même pièce physique.

### Stage 3 — 11 matchs (65%)

Cas avec 2+ candidats dans le référentiel, résolus par le score hybride token-coverage + SequenceMatcher :

| Produit MDP | `theme_slug` | eurio_id résolu | Score | Mécanisme |
|---|---|---|---|---|
| Erasmus BU/BE (2022) | `erasmus` | `eu-2022-2eur-35-years-of-the-erasmus-programme` | 1.0 | Token `erasmus` matche parfaitement |
| Coupe du Monde Rugby 2023 BU/BE | `coupe-du-monde-de-rugby-france-2023` | `fr-2023-2eur-2023-rugby-world-cup` | 0.286 | `rugby` + `2023` partagés |
| Musée du Louvre × 5 variantes | `musee-du-louvre` (collapsed) | `fr-2025-2eur-louvre-museum` | 0.333 | Token `louvre` partagé |
| Notre-Dame de Paris BU/BE | `notre-dame-de-paris` | `fr-2025-2eur-notre-dame-paris` | 0.75 | Coverage `{notre, dame, paris}` |

**Joint issue correctement détectée** : `candidates_for(FR, 2022)` remonte non seulement les 3 commemos FR-2022 mais aussi `eu-2022-*` car FR est dans `national_variants`. Le score 1.0 de Erasmus vient du fait que le token `erasmus` est présent dans le slug du eu-* canonical.

### Stage 5 — 0 escalation

Premier scraper à atteindre un taux de match 100%. Trois facteurs :
1. **Volume faible** (17 vs 760 pour lmdlp) → moins d'occasions de cas tordus
2. **Proper nouns FR plus proches du slug Wikipedia** (Louvre, Notre-Dame, Erasmus, Rugby) que les paraphrases lmdlp
3. **SUBTHEME_COLLAPSE** pré-mappe les variantes coincards du Louvre vers le slug de base — sans ça, `musee-du-louvre-la-joconde` aurait eu un score plus faible et aurait peut-être escaladé

---

## 4. Sub-theme collapsing

Le Louvre 2025 existe chez MDP en **5 variantes coincard** :
- `musee-du-louvre-la-joconde` (coincard avec La Joconde sur la carte)
- `musee-du-louvre-la-venus-de-milo`
- `musee-du-louvre-la-victoire-de-samothrace`
- `musee-du-louvre-l-amour-et-psyche-a-demi-couchee`
- `musee-du-louvre-polissage-inverse` (quality variant)

Mais c'est **une seule et même pièce physique** — même design, même volume d'émission — avec 5 emballages différents. Le dict `SUBTHEME_COLLAPSE` mappe chaque sous-slug vers `musee-du-louvre` pour qu'ils matchent tous le même `eurio_id`.

C'est le seul cas de collapsing nécessaire pour le moment. Le Petit Prince 2026 fonctionne différemment (6 variantes, slugs tous distincts) mais Stage 2 le consolide naturellement car il n'y a qu'une commémo FR 2026 dans le référentiel.

Cette logique est **spécifique à la source MDP** (c'est leur packaging, pas un truc générique). Elle vit dans `scrape_monnaiedeparis.py` et pas dans `matching.py`.

---

## 5. Schema d'enrichissement

```json
{
  "eurio_id": "fr-2025-2eur-louvre-museum",
  "cross_refs": {
    "wikipedia_url": "...",
    "mdp_skus": ["Coincard_Louvre_Joconde_...", "Coincard_Louvre_Venus_...", ...],
    "mdp_urls": ["https://www.monnaiedeparis.fr/fr/musee-du-louvre-la-joconde-...", ...]
  },
  "observations": {
    "wikipedia": { ... },
    "mdp_issue": [
      {
        "sku": "Coincard_Louvre_Joconde_...",
        "name": "Musée du Louvre - La Joconde",
        "url": "https://www.monnaiedeparis.fr/fr/...",
        "price_eur": 12.0,
        "quality": "bu",
        "availability": "InStock",
        "image_url": "https://...",
        "sampled_at": "2026-04-13T..."
      },
      { "sku": "...", "quality": "be", "price_eur": 26.0, "availability": "OutOfStock", ... }
    ]
  },
  "provenance": {
    "sources_used": ["wikipedia_commemo", "mdp"],
    "last_updated": "2026-04-13"
  }
}
```

**Décision de design : `mdp_issue` est une liste, pas un dict unique.** La spec originale (`phase-2c-referential.md` §2C.3) disait "stocker `observations.monnaiedeparis_issue` (prix d'émission, jamais écrasé)", mais comme lmdlp on a plusieurs variantes (BU/BE, coincards, polissage inversé) pour la même pièce physique. On stocke toutes les variantes pour ne rien perdre.

**Prix d'émission officiel** : c'est un **point de référence historique**. Contrairement à `ebay_market` qui sera re-échantillonné périodiquement, `mdp_issue` représente le prix de sortie officiel et ne doit pas être écrasé lors d'un re-run (sauf si MDP change son prix — rare mais possible pour les pièces encore en catalogue).

**Correction de cette règle dans le code actuel** : le re-run **remplace** `mdp_issue` à chaque fois. C'est OK tant que MDP ne change pas ses prix historiques. Si on découvre un jour qu'ils modifient des prix passés, on passera à un append-only avec `first_seen_price` / `current_price`.

---

## 6. Refactor : module `matching.py`

Pendant ce run j'ai extrait les helpers partagés de `scrape_lmdlp.py` vers un nouveau module `ml/matching.py` :
- `index_referential(referential)`
- `candidates_for(idx, country, year)` (avec inclusion joint issues)
- `slug_score(a, b)` (hybride token + ratio)
- `best_slug_match(source_slug, candidates)`
- `match(idx, country, year, theme_slug, ...)` → decision dict

`scrape_lmdlp.py` importe maintenant depuis `matching`, `scrape_monnaiedeparis.py` aussi, et le futur `scrape_ebay.py` (Phase 2C.4) fera pareil. Zéro duplication entre scrapers.

Tests : 59 unittest verts (ajout de 11 tests MDP, un a révélé un bug dans `extract_sku_from_image` — la regex extrayait trop peu, fix au passage pour retourner le filename complet sans extension).

---

## 7. Ce qui n'est pas couvert

| Zone | Pourquoi |
|---|---|
| Prix d'émission **historiques** (avant 2022) | MDP dégaze son catalogue, pas d'archive publique dans le sitemap |
| **Mintage MDP** | Pas dans le JSON-LD, nécessiterait scraping de la page produit complète (spec HTML) |
| **Artist / designer** | Idem, disponible dans la page mais pas dans schema.org Product |
| **Pièces 10€ / 50€ / argent** | Hors scope v1 (uniquement 2€ commémoratives) |
| **Prix en bundle** (coffrets Louvre, etc.) | Filtrés — rouleaux et coffrets n'ont pas de sens pour l'identité single-coin |

---

## 8. Sortie observable

```
ml/datasets/sources/mdp_2026-04-13.json    # 17 produits raw avec JSON-LD
ml/datasets/eurio_referential.json         # +5 entrées enrichies mdp_issue
ml/datasets/matching_log.jsonl             # 17 lignes datées source=mdp
ml/datasets/review_queue.json              # aucun item source=mdp
ml/matching.py                             # NEW module partagé
```

---

## 9. Prochaine étape

Phase 2C.4 — Port du pipeline eBay vers le référentiel. Réutilise `matching.py`, enrichit `observations.ebay_market` avec P25/P50/P75 pondéré par vélocité, consomme les clés EBAY_CLIENT_ID / SECRET déjà dans `.env`. Détail dans [`ebay-api-strategy.md`](./ebay-api-strategy.md) et mémoire `project_ebay_api_strategy.md`.
