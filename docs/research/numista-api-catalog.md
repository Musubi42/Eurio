# Numista API v3 — Stratégie catalogue 2€

> Recherche effectuée le 2026-04-10. Objectif : récupérer automatiquement tous les types de 2€ euro depuis Numista.

---

## 1. Endpoints utilisés

### Recherche de types

```
GET https://api.numista.com/api/v3/types
```

| Paramètre | Type | Description |
|---|---|---|
| `q` | string | Recherche texte (ex: `"2 euro"`) |
| `issuer` | string | Code pays (ex: `"france"`, `"germany"`) |
| `category` | string | `"coin"`, `"banknote"`, `"exonumia"` |
| `count` | integer | Résultats/page, **max 50** |
| `page` | integer | Numéro de page, commence à **1** |
| `lang` | string | Langue (ex: `"en"`) |

**Pas de filtre par dénomination.** Il faut chercher par texte `"2 euro"` puis filtrer par `face_value` dans les détails.

Auth : `Numista-API-Key: <key>`

### Détails d'un type

```
GET https://api.numista.com/api/v3/types/{id}
```

Retourne : titre, issuer, année, face_value, obverse/reverse (picture + description), poids, diamètre, composition, tranche.

---

## 2. Stratégie de fetch

### Approche retenue : par pays

```python
EUROZONE = [
    "france", "germany", "italy", "spain", "portugal",
    "netherlands", "belgium", "austria", "finland", "ireland",
    "greece", "luxembourg", "slovenia", "cyprus", "malta",
    "slovakia", "estonia", "latvia", "lithuania",
    "andorra", "monaco", "san-marino", "vatican-city",
]

for country in EUROZONE:
    page = 1
    while True:
        results = GET /types?q=2+euro&issuer={country}&category=coin&count=50&page={page}
        if not results: break
        for type in results:
            details = GET /types/{type.id}
            if details.face_value == 2.0:
                save_to_catalog(details)
        page += 1
```

### Pourquoi par pays (pas une recherche globale)

- Plus structuré, évite de rater des résultats
- Permet de reprendre si un pays échoue
- Meilleure traçabilité (combien de types par pays)

---

## 3. Volume attendu

| Catégorie | Estimation |
|---|---|
| Circulation (1 par pays) | ~23 types |
| Commémoratives | ~500+ types (en croissance chaque année) |
| **Total** | **~520-600 types** |

Pays les plus prolifiques : Allemagne, Italie, France (plusieurs commémoratives/an).

---

## 4. Rate limits

| Endpoint | Quota | Notes |
|---|---|---|
| Search (`/types?q=...`) | Pas de limite stricte | Usage "raisonnable" |
| Type details (`/types/{id}`) | Pas de limite stricte | ~200ms entre les calls |
| `searchByImage` | Payant (100€/mois) | **Non utilisé** |

**Recommandation** : 200ms de délai entre chaque appel. Pour ~600 types = ~2 min de fetch total.

---

## 5. Champs récupérés par type

```json
{
  "id": 226447,
  "title": "2 Euros (Kneeling to Warsaw)",
  "issuer": { "name": "Germany, Federal Republic of" },
  "min_year": 2020,
  "value": { "numeric_value": 2.0 },
  "weight": 8.5,
  "size": 25.75,
  "composition": { "text": "Bimetallic: nickel brass centre in copper-nickel ring" },
  "obverse": {
    "description": "In center former German Chancellor Willy Brandt...",
    "picture": "https://en.numista.com/catalogue/photos/..."
  },
  "reverse": {
    "description": "...",
    "picture": "https://en.numista.com/catalogue/photos/..."
  }
}
```

---

## 6. Rate limits — retour d'expérience (avril 2026)

### Quotas mesurés

| Ressource | Limite | Constaté |
|---|---|---|
| API calls/mois (plan gratuit) | ~2000 | 2060 calls → rate limited |
| `get_type` calls | Inclus dans le total | 1162 utilisés |
| `search_types` calls | Inclus dans le total | 898 utilisés |
| Image CDN (`en.numista.com`) | ~1 req/s | 429 à haute fréquence |

### Ce qu'on a récupéré avant le rate limit

- **445 coins** dans `coin_catalog.json` (métadonnées complètes)
- **~300 images** téléchargées (obverse + reverse)
- **~145 images** manquantes (CDN rate limited)

### Stratégie de reprise

Le script `import_numista.py` a 3 modes pour gérer les quotas :

```bash
# Mode 1: Import complet (utilise le quota API)
.venv/bin/python import_numista.py

# Mode 2: Re-télécharger les images manquantes (ZERO appel API)
# Utilise les URLs cachées dans coin_catalog.json
.venv/bin/python import_numista.py --retry-images

# Mode 3: Remplir les URLs manquantes dans le catalogue (utilise le quota)
# Pour les entrées importées avant qu'on cache les URLs
.venv/bin/python import_numista.py --backfill-urls
```

### Recommandations

- Attendre le reset mensuel (1er mai) pour `--backfill-urls` sur les ~145 entrées sans URL
- `--retry-images` est safe à lancer à tout moment (ne touche pas au quota API)
- Mettre `--retry-delay 2` ou `3` si le CDN rate-limite encore
- Budget API pour compléter : ~100 `get_type` (backfill) + ~20 `search` (nouvelles pages) = ~120 calls

---

## 7. Points d'attention

1. **Faux positifs** : `q=2+euro` retourne aussi "20 euro", "2 euro cent" → le script pré-filtre par titre + post-filtre par `face_value == 2` et `currency.name == "Euro"`
2. **Images** : les URLs Numista sont stables mais hébergées sur leur serveur → téléchargées localement dans `datasets/{numista_id}/obverse.jpg`
3. **Licences** : vérifier les conditions d'utilisation des images Numista (usage non-commercial OK, redistribution à vérifier)
4. **Pays non-eurozone émettant des 2€** : Andorre, Monaco, San Marino, Vatican → inclus automatiquement (recherche globale, pas par pays)
5. **URLs cachées** : depuis avril 2026, les image URLs sont stockées dans `coin_catalog.json` pour éviter de rappeler l'API lors des retries
