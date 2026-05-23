# Handoff — i18n pour les 147 commémoratives générées au Chunk 2b

> Doc à **feed-er dans une session multi-agent dédiée** pour combler l'i18n
> (titres localisés + aliases) des 147 commémoratives 2 € créées à
> l'harmonisation Chunk 2b. Sans ça, le theme-matcher est aveugle à ces
> pièces sur les marketplaces non-anglophones (DE, IT, ES, NL, FR).

## Pourquoi ce trou existe

Au Chunk 2b (cf. `plan.md`), 148 commémoratives manquantes ont été créées
depuis `referential_catalog` (le scrape Numista). Le pipeline d'i18n
(`bootstrap_coin_names_i18n.py`, `llm_coin_aliases.py`…) avait été tourné
sur l'ancien périmètre (≈ 466 commémo) → les 148 nouvelles n'ont reçu **ni
titres localisés, ni aliases**. Une seule (`…-of-the-university-of-ghent`)
a été dépannée à la main au cas BE 2017 (voir
`scripts/patch_be2017_ghent_i18n.py`). **147 restent à faire.**

Conséquence concrète, observée dans le studio bench : pour ces pièces, le
theme-matcher n'a aucun token DE/IT/ES/NL à mettre en face d'une annonce
eBay → toutes les attributions partent vers la pièce-sœur la plus
i18n-riche → mauvaises décisions.

## Identifier les 147

```sql
SELECT eurio_id, country, year, theme, numista_id
FROM coins
WHERE is_commemorative = 1
  AND face_value = 2.0
  AND ref_source = 'numista'
  AND eurio_id NOT IN (
    SELECT DISTINCT eurio_id FROM coin_names_i18n
  );
```

Ou plus court : pièces commémo 2 € *sans aucune ligne* `coin_names_i18n`.
Devrait rendre exactement 147 (au moment de l'écriture).

## Stratégie i18n du repo (à respecter)

Documentée dans `docs/sources-refacto/ebay-multi-marketplace/i18n-strategy.md`,
résumé :

- **FR + EN** : scrapés depuis Numista (page localisée). `source='numista'`,
  `confidence='canon'`.
- **DE + IT + ES + NL** : générés par LLM (les fiches Numista n'existent
  pas dans ces langues). `source='llm_v1'`, `confidence='assisted'`,
  `model='claude-opus-4-7'` (ou supérieur).
- **Aliases** (`coin_aliases`) : surface forms additionnelles (acronymes,
  surnoms), minées via `scripts/llm_coin_aliases.py`. `source='llm'`,
  `confidence='high'`.

La table `coin_names_i18n` a la PK `(eurio_id, lang)` et les colonnes
`title`, `source`, `confidence`, `model`, `fetched_at` (cf.
`ml/state/schema.sql:698-710`). **Format des titres** : miroite la
convention Numista du repo (regarde un coin déjà localisé pour le ton —
ex. `be-2017-2eur-200-years-of-the-university-of-liege`).

## Outillage existant à réutiliser (ne pas refaire)

| Script | Rôle |
|---|---|
| `scripts/bootstrap_coin_names_i18n.py` | scrape Numista FR/EN, insère canon |
| `scripts/export_i18n_worklist.py` | exporte une worklist JSON à donner au LLM |
| `scripts/import_i18n_results.py` | réimporte les résultats LLM dans `coin_names_i18n` |
| `scripts/import_llm_translations.py` | variante / fichiers `i18n_llm_part*.jsonl` |
| `scripts/llm_coin_aliases.py` | mine les aliases via LLM ancré |
| `scripts/mine_coin_aliases.py` | alternative non-LLM |
| `scripts/probe_i18n_recall.py` | probe QA — vérifie que le matcher capte |
| `scripts/probe_i18n_tokens.py` | probe tokens |

Tous accessibles via go-task (cf. `ml/Taskfile.yml`).

## Pitfall identifié — QA stricte sur les aliases

Découvert au Chunk 2b (cf. `patch_be2017_ghent_i18n.py`) : les 4 aliases
attachés à la pièce 2017 BE étaient **`gent` / `ghent` / `gand` / `gante`** —
toutes les variantes du nom de **Ghent**. Or la pièce était (après audit)
celle de **Liège**. Les aliases avaient été générés contre l'ancien slug
`…-ghent-university` et n'ont pas suivi le rename.

**Implication pour cette session** : si un coin a un `eurio_id_migrations`
entry (`SELECT * FROM eurio_id_migrations`), ses aliases doivent être
re-évalués — pas simplement re-pointés. Pour les 147 nouvelles, c'est un
non-sujet (pas de rename, ce sont des créations), mais à garder en tête
pour le QA général.

## Acceptance criteria

À la sortie de la session :

1. `SELECT count(*) FROM coins WHERE is_commemorative=1 AND face_value=2.0
   AND eurio_id NOT IN (SELECT DISTINCT eurio_id FROM coin_names_i18n)` →
   **0**.
2. Chaque pièce a 6 lignes i18n (`fr/en/de/es/it/nl`).
3. `source`/`confidence` corrects (canon pour FR/EN scrapés, assisted pour
   les 4 LLM).
4. `scripts/probe_i18n_recall.py` passe (recall ≥ seuil acté du projet).
5. Aliases minés via `llm_coin_aliases.py` pour les pièces où les tokens
   i18n ne suffisent pas (à juger via probe).
6. Sync vers Supabase : `go-task ml:sync-supabase` après pour propager
   à l'app.

## Contexte projet pour démarrer

À lire (ordre conseillé, ~15 min) :

1. `docs/data-harmonization/architecture.md` — pourquoi `eurio.db` est
   canonique, ce que change le Chunk 2.
2. `docs/sources-refacto/ebay-multi-marketplace/i18n-strategy.md` — la
   stratégie i18n actée du repo.
3. `docs/sources-refacto/ebay-multi-marketplace/i18n-llm-translation.md` —
   prompt LLM, format de sortie.
4. Le schéma `coin_names_i18n` + `coin_aliases` dans `ml/state/schema.sql`
   (lignes ~698-735).

**Quotas Numista** : ~2000 req/mois free. 147 coins × 2 langs (FR/EN) = 294
appels — large marge. Scrape éventuellement via TOR (cf. `i18n-probe.md`
findings : WAF kick à 7 req sur certaines pages — espacer).

## Commit attendu en sortie

Branche dédiée (ex. `i18n-147-coins`), un commit par étape (scrape /
import LLM / aliases / probe), puis sync Supabase, puis merge vers `main`.
Aucun changement de schéma attendu — pure population de données existantes.
