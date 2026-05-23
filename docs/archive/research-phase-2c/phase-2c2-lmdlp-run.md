# Phase 2C.2 — Run report scrape_lmdlp.py

> Premier run du scraper lamonnaiedelapiece.com après implémentation.
> Date : 2026-04-13.
> Doc parent : [`phase-2c-referential.md`](../phases/phase-2c-referential.md) §2C.2, [`data-referential-architecture.md`](./data-referential-architecture.md).

---

## TL;DR

760 produits 2€ commémoratives filtrés, 73% matchés automatiquement, 268 entrées canoniques enrichies. Les 27% en review (204 variantes / 128 thèmes uniques) sont 100% des cas FR↔EN qui nécessitent soit un dictionnaire de traduction soit le Stage 4 visuel (Phase 2B).

| Métrique | Valeur |
|---|---|
| Produits bruts récupérés | 835 |
| Produits filtrés (single 2€ commemo) | 760 |
| Match Stage 2 (structural unique) | 162 (21%) |
| Match Stage 3 (fuzzy slug) | 390 (51%) |
| Escalade Stage 5 (ambiguous) | 204 (27%) |
| Skip (missing country/year) | 4 |
| **Taux match auto** | **73%** |
| Entrées canoniques enrichies | 268 |
| Entrées avec mintage `Tirage` lmdlp | 162 |
| Lignes dans `matching_log.jsonl` | 760 |
| Items en `review_queue` (lmdlp) | 204 (sur 128 thèmes uniques) |

---

## 1. Fetch et filtrage

### API utilisée

`GET https://lamonnaiedelapiece.com/wp-json/wc/store/v1/products`
avec filtre serveur : `attributes[0][attribute]=pa_nominale-waarde&attributes[0][slug]=2-euro-fr`

Pagination : `per_page=100`, 9 pages, 835 produits totaux. Politesse : `time.sleep(0.3)` entre pages.

### Filtres locaux

| Critère | Rejetés |
|---|---|
| `is_purchasable=false` | 31 |
| Nom contient `coffret`/`série`/`set`/`blister`/`rouleau` | 28 |
| Type ≠ `commémorative` (ex: `monnaie normale`) | 12 |
| Catégorie blacklistée (`coffret`/`rouleau`/`liste`) | 4 |
| **Total filtrés** | **75** |

Reste : **760 produits** à matcher.

---

## 2. Pipeline de matching

### Stage 1 — Exact cross-ref

Skippé : lmdlp n'expose pas d'ID Numista ni de code JOUE. Aucune cross-ref native exploitable au moment du scrape (on pourrait en extraire des descriptions ultérieurement).

### Stage 2 — Structural key unique

Filtre `(country, year, face_value=2.0)` dans le référentiel. Si exactement 1 candidat → match avec confidence 0.95.

**162 matchs (21%)** — typiquement les pays qui n'émettent qu'une seule commémo dans l'année (Andorre, Vatican, Monaco, Pays-Bas, certains années DE/AT).

### Stage 3 — Fuzzy slug

2+ candidats → score hybride `slug_score(source, candidate)` :
```python
coverage = |src_tokens ∩ cand_tokens| / |src_tokens|
ratio = SequenceMatcher(source, candidate).ratio()
score = max(coverage, ratio * 0.7)
```

Token coverage capture les cas où le thème lmdlp partage les mots significatifs avec le slug canonique (`carlo-collodi-pinocchio` ↔ `pinocchio-200th-birthday-of-carlo-collodi` → coverage 1.0). SequenceMatcher rattrape les cas FR↔EN partiels (`francois-dassise` ↔ `francis-of-assisi` → ratio ~0.4).

Décision : `score >= 0.25 AND score >= 1.4 × runner_up_score` → match.

**390 matchs (51%)** — la majorité des cas où FR contient le proper noun de la pièce.

### Stage 4 — Visual

Désactivé en attendant le modèle ArcFace de Phase 2B. Les escalades vont directement à Stage 5.

### Stage 5 — Review humaine

Tous les ambiguïtés non résolues → `ml/datasets/review_queue.json`.

**204 escalades (27%)** sur 128 thèmes uniques (les variantes UNC/BU/BE proof partagent le même thème).

---

## 3. Anatomie des escalades

100% des 204 escalades sont du type `ambiguous_fuzzy` : Stage 2 a renvoyé 2+ candidats et Stage 3 n'a pas tranché. Aucune escalade `no_candidate` (= le bootstrap couvre tous les pays/années que lmdlp vend).

Cause systématique : **traduction FR → EN** sans recouvrement de mots ni partage de substrings suffisant. Échantillon :

| lmdlp (FR) | Candidats (EN) | Verdict humain trivial |
|---|---|---|
| `chien-pharaon` | `the-pharaohs-hound-native-species-series` ou `maltese-walled-cities-valetta` | premier |
| `breme-maison-du-climat` | `museum-of-climatic-zones-in-bremerhaven-bremen` ou `konrad-adenauer` | premier |
| `mazoji-lietuva` | `lithuania-minor` ou `defense-of-lithuania` | premier (Mažoji = Minor) |
| `torche-olympique` | `summer-olympics-in-paris-2024` ou `hercules-...-notre-dames` | premier |
| `francois-dassise` | `800th-anniversary-of-the-death-of-francis-of-assisi` ou `pinocchio-...` | premier |

Ces cas sont **triviaux pour un humain** mais hors portée d'un slug-matcher sans dictionnaire bilingue.

---

## 4. Options évaluées pour réduire le 27%

| Option | Gain estimé | Coût | Décision |
|---|---|---|---|
| Mini-dico FR→EN (40 termes coin-domain) | -15% | maintenance perpetuelle, brittle | **non** |
| Inclure `description` HTML lmdlp dans le score | -2-5% | descriptions vides 80% du temps | **non** |
| Stage 4 visual (ArcFace, Phase 2B) | -25% | dépend Phase 2B | **oui (futur)** |
| Review CLI (Phase 2C.5) sur 128 thèmes uniques | -100% | ~30 min humain | **oui (Phase 2C.5)** |
| Service de traduction LLM offline | -15% | dep externe, coût | **non** |

**Décision retenue** : accepter 73% comme baseline. Le doc d'architecture le permet explicitement (« On accepte un taux d'escalade non nul, surtout avant que Stage 4 (visual) ne soit activé »). Phase 2C.5 (review CLI) résoudra les 128 thèmes uniques manuellement, et Stage 4 prendra le relais quand ArcFace sera prêt.

---

## 5. Schema d'enrichissement

Pour chaque entrée matchée :

```json
{
  "eurio_id": "fr-2024-2eur-summer-olympics-in-paris-2024",
  "cross_refs": {
    "wikipedia_url": "...",
    "lmdlp_skus": ["fr2024jorgrunc", "fr2024jorgrpr", "fr2024jorgrcc", ...],
    "lmdlp_url": "https://lamonnaiedelapiece.com/fr/product/...-grise-unc/"
  },
  "observations": {
    "wikipedia": { ... },
    "lmdlp_variants": [
      {
        "sku": "fr2024jorgrunc",
        "name": "2 euros France 2024 – Torche Olympique grise UNC",
        "url": "https://...",
        "price_eur": 4.50,
        "quality": "UNC",
        "in_stock": true,
        "image_url": "https://...",
        "sampled_at": "2026-04-13T..."
      },
      { "sku": "fr2024jorgrpr", "quality": "BE Polissage inversé", "price_eur": 140.0, ... }
    ],
    "lmdlp_mintage": {
      "value": 5000000,
      "source": "lmdlp",
      "fetched_at": "2026-04-13"
    }
  },
  "provenance": {
    "sources_used": ["wikipedia_commemo", "lmdlp"],
    "last_updated": "2026-04-13"
  }
}
```

Note : `lmdlp_variants` est une **liste** parce qu'un même `eurio_id` est typiquement vendu en plusieurs qualités (UNC, BU FDC, BE proof, Coincard). Le scraper groupe automatiquement par `eurio_id` matché et insère toutes les variantes.

`lmdlp_mintage` est **additif** — il ne remplace jamais une valeur Wikipedia déjà présente. Il vit dans son propre slot pour ne pas confondre les sources.

---

## 6. Idempotence

Le script peut être re-exécuté sans corruption :
- Snapshot daté : un fichier par jour, jamais écrasé
- Le référentiel est lu, modifié, ré-écrit (les enrichissements remplacent les anciennes valeurs lmdlp pour le même `eurio_id`)
- `matching_log.jsonl` est append-only (chaque run ajoute ses 760 lignes datées)
- `review_queue.json` : remplacement par source via `replace_review_queue_for_source("lmdlp", ...)` — les items des autres sources sont préservés

---

## 7. Limitations connues à documenter

1. **27% en review** — dictionnaire FR↔EN nécessaire ou Stage 4 (Phase 2B)
2. **Pas d'extraction de cross-ref Numista** depuis description HTML — on a essayé, descriptions trop souvent vides
3. **Quality strings non-normalisés** — `UNC`, `BU FDC`, `BE Polissage inversé`, `BU FDC Coincard`, `BE Proof colorisé`, etc. Une normalisation type → enum sera nécessaire pour le scoring de prix dans Phase 3
4. **Mintage `Tirage` non distingué par variante** — on prend la première valeur trouvée, qui peut être celle de la variante BE Proof (5000) plutôt que UNC (5M). À revoir.
5. **Aucun joint issue (`eu-*`) matché en pratique** — lmdlp catégorise les communes par pays national, donc Stage 2 trouve une candidate nationale d'abord. Le code support `candidates_for(... + joint_for_member)` mais en pratique aucune émission commune ne tombe en stock chez lmdlp en avril 2026 (les 5 émissions communes datent de 2007-2022, stocks épuisés).

---

## 8. Sortie observable

```
ml/datasets/sources/lmdlp_2026-04-13.json   # 835 produits raw, ~3 MB
ml/datasets/eurio_referential.json          # 2938 entrées dont 268 enrichies lmdlp
ml/datasets/matching_log.jsonl              # 760 lignes datées
ml/datasets/review_queue.json               # 204 items source=lmdlp
```

---

## 9. Prochaine étape

Phase 2C.3 — `scrape_monnaiedeparis.py` : prix d'émission officiels français via JSON-LD du sitemap. Devrait beaucoup mieux matcher car :
- Les noms français sont les noms officiels (le slug Wikipedia FR est plus proche)
- Pas de variantes qualité aussi sauvages que lmdlp
- Cross-validation possible avec lmdlp pour les pièces françaises (déjà 31 enrichies par lmdlp)
