# Chunk — LLM batch translation DE/IT/ES/NL (PC)

> Brief auto-suffisant pour produire les ~2312 rows
> `coin_names_i18n` en `source='llm_v1'` `confidence='assisted'` (ou
> `uncertain` en cas de doute).
> Tourne sur le **PC** (clé API Anthropic via direnv).
>
> Lire d'abord `i18n-strategy.md` pour le contexte général, et
> exécuter `i18n-scrape-numista.md` avant (besoin du titre EN canon
> comme input).
>
> Verrouillé 2026-05-19.

## Objectif

Pour chacun des ~578 coins (`face_value=2.0 ∧ numista_id≠NULL`),
produire un titre dans **DE, IT, ES, NL** via Claude Opus 4.7, en
partant du titre EN canon (scrape Numista) comme source de vérité.

= **578 × 4 = 2312 traductions**, ~200 appels LLM (batch ~12 coins,
1 langue/appel), coût estimé **$5-10**.

## Pourquoi LLM et pas autre chose

Voir `i18n-strategy.md` §"Pourquoi pas Numista en multi-langue" et
§"Pourquoi pas les ateliers de mintage nationaux". TL;DR : Numista
non-canon hors FR/EN, ateliers nationaux trop lourds pour V1, LLM
=  20 % effort / 80 % qualité acceptable avec marquage de provenance.

## Anti-hallucination — règles strictes

### 1. Batch size petit

**10-15 coins par appel**, 1 langue par appel.

Trop grand (50+) → le modèle perd en précision sur les derniers items
et peut mélanger les contextes.
Trop petit (1-3) → coût/temps élevé pour peu de gain.

### 2. Prompt structuré avec contexte minimal

```
Tu traduis des titres de pièces de monnaie euro en {LANG_TARGET_NAME}
({LANG_TARGET_CODE}).

Règles strictes :
1. Le titre source est en anglais (référence Numista canonique).
2. Pour les standards (pas de thème commémoratif), traduire
   littéralement la dénomination (ex: "2 Euros" → "2 Euro" en DE).
3. Pour les commémos qui référencent un événement historique, un
   personnage célèbre, ou un lieu nommé avec une forme consacrée
   dans la langue cible, utiliser cette forme consacrée
   (ex: "Kneeling to Warsaw" → "Kniefall von Warschau" en DE).
4. Pour les commémos thématiques sans nom consacré (ex: "European
   Cultural Heritage"), traduire littéralement de manière naturelle.
5. Conserver les noms propres tels quels s'ils ne sont pas traduits
   dans la langue cible (ex: "Grace Kelly" reste "Grace Kelly" en DE).
6. Si tu n'es PAS sûr de la traduction consacrée ou si le contexte
   est insuffisant, retourner exactement la chaîne "UNCERTAIN".
7. NE JAMAIS inventer un nom officiel qui n'existe pas — préfère
   "UNCERTAIN" à une hallucination.

Format de sortie : JSON strict, 1 objet par coin.
[{"eurio_id": "...", "title": "..."}, ...]
```

Puis input :

```
Coins à traduire (langue cible : {LANG_TARGET_NAME}) :

[
  {
    "eurio_id": "de-2020-2eur-50-years-since-the-kniefall-von-warschau",
    "country_code": "DE",
    "country_name": "Germany",
    "year": 2020,
    "face_value": 2.0,
    "is_commemorative": true,
    "theme_en": "50 years since the Kniefall von Warschau",
    "title_en_canonical": "2 Euros Kneeling to Warsaw"
  },
  ...
]
```

### 3. Validation auto post-LLM

Avant insertion DB, valider chaque output :

| Check | Action si KO |
|---|---|
| Output est JSON parseable | retry appel |
| `len(output) == batch_size` | retry appel |
| Tous les `eurio_id` retournés correspondent à l'input | retry appel |
| `title != "UNCERTAIN"` | si `UNCERTAIN`, marquer `confidence='uncertain'`, persister quand même |
| `len(title) ∈ [5, 200]` | si OOB → `confidence='uncertain'` |
| Charset cohérent avec la langue (heuristique : pas trop de latin pour EL/BG/RU) | si fail → `confidence='uncertain'` |
| Pas de fragment EN repérable (ex: "Euros" en DE → suspicious car DE = "Euro") | si fail → `confidence='uncertain'` |

Pour V1 (4 langues toutes latin), le check charset est trivial.

### 4. Re-runs déterministes

Stocker la version du prompt (`prompt_v1`, `prompt_v2`, ...) dans la
table pour traçabilité. Si on rejoue avec un prompt amélioré, on peut
filtrer les rows à régénérer.

Ajout possible à la table (V1.1 si nécessaire) :

```sql
ALTER TABLE coin_names_i18n ADD COLUMN prompt_version TEXT;
```

Pas critique pour V1, on peut s'en passer si le prompt reste stable.

## Script `translate_coin_names_llm.py`

Emplacement : `ml/scripts/translate_coin_names_llm.py`.

```python
"""LLM batch translation of coin titles via Claude Opus 4.7.

Run on PC (Anthropic API key via direnv).

Usage:
    python -m scripts.translate_coin_names_llm
    python -m scripts.translate_coin_names_llm --lang de
    python -m scripts.translate_coin_names_llm --lang de,it,es,nl
    python -m scripts.translate_coin_names_llm --batch-size 12
    python -m scripts.translate_coin_names_llm --only-eurio <id1>,<id2>
    python -m scripts.translate_coin_names_llm --refresh    # re-run même si déjà LLM
    python -m scripts.translate_coin_names_llm --dry-run    # log appels, pas d'écriture
"""
```

### Comportement

- **Précondition** : table `coin_names_i18n` peuplée pour FR + EN
  (scrape Numista déjà exécuté). Sinon : abort avec message clair.
- **Sélection coins** :
  ```sql
  SELECT c.eurio_id, c.country, c.country_name, c.year, c.face_value,
         c.is_commemorative, c.theme, n.title AS title_en
  FROM coins c
  JOIN coin_names_i18n n ON n.eurio_id = c.eurio_id AND n.lang = 'en'
  WHERE c.face_value = 2.0
    AND c.numista_id IS NOT NULL
  ```
- **Filtre** par langue + skip-if-present (default) ou refresh
- **Batching** : `chunks(coins, size=batch_size)` puis 1 appel par
  chunk × 1 langue
- **Modèle** : `claude-opus-4-7[1m]` (ID exact via Anthropic SDK)
- **Throttle** : Pas critique (Anthropic API limite côté serveur).
  Loop séquentiel suffit pour V1.
- **Persistence** : `INSERT OR REPLACE INTO coin_names_i18n`. Commit
  par batch.
- **Retries** : 3× sur erreur API + 1× sur validation auto échouée.

### Pseudo-code

```python
import anthropic

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY via env

LANGS = {
    'de': 'allemand (Deutsch)',
    'it': 'italien (Italiano)',
    'es': 'espagnol (Español)',
    'nl': 'néerlandais (Nederlands)',
}

PROMPT_VERSION = 'v1'

def translate_batch(coins_batch, lang_code, lang_name):
    user_msg = build_user_message(coins_batch, lang_name)
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    output_json = parse_strict_json(response.content[0].text)
    validate_output(output_json, coins_batch)
    return output_json
```

## Validation post-run

### Métrique globale

```sql
SELECT lang, source, confidence, count(*) 
FROM coin_names_i18n 
GROUP BY lang, source, confidence;
```

Attendu V1 :

| lang | source | confidence | count attendu |
|---|---|---|---|
| fr | numista | canon | ~570 |
| en | numista | canon | ~570 |
| de | llm_v1 | assisted | ~520 |
| de | llm_v1 | uncertain | ~50 |
| it | llm_v1 | assisted | ~520 |
| it | llm_v1 | uncertain | ~50 |
| ... |  |  |  |

**Critère** : taux d'`uncertain` ≤ 10 % par langue.

### Spot-check humain (30 coins)

5 coins × 4 langues LLM + 5 coins × 2 langues Numista = 30 checks.

Sélection coins pour spot-check (diversifiée) :

1. Un standard simple (`fr-1999-2eur-standard`) — vérifier "2 Euros"
   localisé
2. Une commémo avec nom historique (`de-2020-Kniefall`) — vérifier
   forme consacrée
3. Une commémo avec proper noun (`mc-2007-Grace-Kelly`) — vérifier
   non-traduction
4. Une commémo Andorre (`ad-2025-Bartgeier`) — vérifier translit
5. Un cas Saint-Marin / Vatican — vérifier couverture langues exotiques

Vérification manuelle : ouvrir le titre, juger si "ça passe" en
contexte natif. Marquer les fails dans un fichier
`spot-check-i18n-v1.md` pour iteration.

### Iteration si fails

Si > 5 % spot-check échouent :

1. Identifier le pattern d'erreur (proper nouns ? terme numismatique ?)
2. Renforcer le prompt (`v2`)
3. Re-run sur l'échantillon échoué avec `--refresh --only-eurio <ids>`
4. Spot-check à nouveau

## Coût estimé

| Variable | Valeur |
|---|---|
| Coins | ~578 |
| Langues V1 | 4 (DE, IT, ES, NL) |
| Batch size | 12 |
| Appels LLM | 578 / 12 × 4 = ~195 |
| Tokens input par appel (estim.) | ~1500 (prompt + 12 coins context) |
| Tokens output par appel (estim.) | ~400 (12 traductions) |
| Total input | ~290k tokens |
| Total output | ~80k tokens |
| Tarif Opus 4.7 | $15/M input, $75/M output (à vérifier au moment du run) |
| **Coût total** | **~$10** |

Possibilité d'optimisation : passer à Sonnet 4.6 pour les batchs
trivials (standards) et garder Opus pour les commémos. Pas critique
en V1 vu le coût total raisonnable.

## Anti-objectifs V1

- ❌ Pas de traduction des 11 langues mid-tier (V1.5)
- ❌ Pas de prompt fine-tuning avancé (system prompt simple suffit)
- ❌ Pas de comparaison multi-modèles (Opus seul, on évalue après)
- ❌ Pas de Web search par le LLM (claude doit produire en standalone
  pour reproductibilité et coût)
- ❌ Pas d'écriture vers Supabase (sync = chantier séparé)

## Définition de "done"

- [ ] Précondition validée : `coin_names_i18n` rempli FR+EN
- [ ] Script `translate_coin_names_llm.py` livré + tests
- [ ] Task `ml:translate-coin-names-llm` dans `Taskfile.yml`
- [ ] Run terminé pour DE+IT+ES+NL, taux `uncertain` ≤ 10 % par langue
- [ ] Spot-check 30 coins ≥ 90 % OK
- [ ] Fichier `spot-check-i18n-v1.md` rempli (traces des fails et
  iterations)
- [ ] `progress.md` à jour

## Tests

`ml/tests/test_translate_coin_names_llm.py` :

- Mock client Anthropic, vérifier construction du prompt (1 batch ⇒
  1 appel, format JSON OK)
- Validation auto : JSON malformé → retry, `UNCERTAIN` → persisté avec
  `confidence='uncertain'`, len mismatch → retry
- Test idempotence : skip-if-present, refresh override
- Test filtre `--lang de` : ne touche que `lang='de'`

Pas de test e2e contre vraie API en CI (coût + clé).

## Future work (hors V1)

- V1.5 : ajouter 11 langues mid-tier (réutilisation script, juste
  étendre `LANGS`)
- V2 : remplacer progressivement `llm_v1` par `manual` via review
  admin (prérequis : admin coin details i18n câblé)
- V2+ : sourcer les ateliers de mintage nationaux pour les pays
  Eurozone, remplacer les LLM par du canon vrai
