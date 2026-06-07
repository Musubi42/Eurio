# Stratégie i18n — alias multilingues coins euro

> Doc de stratégie pour la production d'alias multilingues sur les 578
> coins 2€ (commémos + standards). Remplace
> `i18n-bootstrap-kickoff.md` (verrouillé 2026-05-19, périmé par les
> findings du même jour, voir `i18n-probe.md`).
>
> Cette doc est l'**overview** ; les chunks exécutables vivent dans
> `i18n-scrape-numista.md` et `i18n-llm-translation.md`.
>
> Verrouillé 2026-05-19 après probe + discussion.

## TL;DR

Numista multilingue = Google Translate auto sous le capot, **pas
canon**. Seuls FR et EN ont du contenu humain. Pour produire des alias
fiables dans les autres langues officielles Eurozone, on utilise un
**LLM (Claude Opus 4.7)** avec prompt strict + marquage de source.

V1 cible **6 langues** : FR, EN, DE, IT, ES, NL — couvre les
marketplaces eBay actifs + ~95 % des utilisateurs Eurozone.

## Pourquoi pas Numista en multi-langue

Probe du 2026-05-19 sur `fr-1999-2eur-standard` (Numista 104) :

| Langue | h1 |
|---|---|
| **fr** | `2 euros 1re carte` ← traduit humain |
| **en** | `2 Euros 1st map` ← canon |
| de | `2 Euros 1st map` ← identique à EN |
| it | `2 Euros 1st map` ← identique à EN |
| es | `2 Euros 1st map` ← identique à EN |
| nl | `2 Euros 1st map` ← identique à EN |
| ru | `2 Euros 1st map` ← identique à EN |

Constat confirmé manuellement sur d'autres pages : les sous-domaines
non-FR/EN de Numista servent l'UI traduite mais conservent le titre
EN du coin. Les "traductions" visibles ailleurs sur la page (ex.
description) sont rendues par Google Translate widget — **pas une
référence pour produire des alias canoniques**.

Conséquence : scrape Numista limité à FR + EN.

## Pourquoi pas les ateliers de mintage nationaux

Chaque pays Eurozone a son atorité émettrice (BCE pour l'overview,
Monnaie de Paris pour FR, Bundesbank pour DE, etc.). Ce serait la
source **vraiment** canon, mais :

- 21 sources hétérogènes, formats web différents, beaucoup en HTML peu
  structuré
- Couverture incomplète sur les commémos étrangères (chaque atelier ne
  documente que ses propres pièces)
- Effort 10-100× supérieur à un LLM pour un gain marginal V1

**Statut** : noté comme **future work** (V2+). Quand on voudra des
alias vraiment canon (pas juste "assisted"), on construira ce
référentiel atelier par atelier. Pas dans le scope actuel.

## Décisions actées (2026-05-19)

| ID | Décision | Rationale |
|---|---|---|
| **D-i18n-1'** | Source FR + EN = scrape Numista | FR Numista = vraiment traduit par humains français. EN = langue canon. Volume 1156 fetches, faisable via TOR/VPS. |
| **D-i18n-2'** | Source DE, IT, ES, NL = LLM Claude Opus 4.7 | Numista non-canon. Atelier-par-pays trop lourd pour V1. LLM bonne qualité avec prompt strict. |
| **D-i18n-3** | Périmètre V1 = 6 langues (FR, EN, DE, IT, ES, NL) | Couvre marketplaces eBay (6) + 95 % users Eurozone. V1.5 ajoute mid-tier (PT, EL, FI, SV, BG, HR, ET, LV, LT, SK, SL). |
| **D-i18n-4** | Périmètre coins V1 = face_value = 2.0 ∧ numista_id ≠ NULL | ~578 coins. Aligné avec l'usage matcher eBay (commémos 2€). |
| **D-i18n-5** | Traçabilité obligatoire | Table `coin_names_i18n` gagne 2 colonnes : `source` (`numista` \| `llm_v1` \| `manual`) et `confidence` (`canon` \| `assisted` \| `uncertain`). |
| **D-i18n-6** | Bypass WAF Numista | TOR (10 circuits) + 1 req/30s par circuit, run sur VPS Hetzner. Voir `i18n-scrape-numista.md`. |
| **D-i18n-7** | Batch LLM = 10-15 coins/appel, 1 langue/appel | Anti-hallucination. Voir `i18n-llm-translation.md`. |
| **D-i18n-8** | Admin coin details i18n = chantier séparé | L'admin Vue n'a pas vue-i18n câblé. Cette doc produit la *data* ; l'*UI* est un chantier indépendant. |

## Schéma cible `coin_names_i18n`

```sql
-- ml/state/schema.sql §coin_names_i18n (extension)
CREATE TABLE coin_names_i18n (
  eurio_id    TEXT NOT NULL,
  lang        TEXT NOT NULL,
  title       TEXT NOT NULL,           -- texte localisé (h1 ou LLM output)
  source      TEXT NOT NULL,           -- 'numista' | 'llm_v1' | 'manual'
  confidence  TEXT NOT NULL,           -- 'canon' | 'assisted' | 'uncertain'
  model       TEXT,                    -- ex: 'claude-opus-4-7' pour llm_v1
  fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, lang)
  -- CHECK lang IN (...) : retiré, validation Python-side (cf. kickoff §I1-A alternative)
);
```

Sémantique :

- `source='numista'` + `confidence='canon'` : FR ou EN scrape Numista
- `source='llm_v1'` + `confidence='assisted'` : DE/IT/ES/NL via LLM
- `source='llm_v1'` + `confidence='uncertain'` : LLM a renvoyé
  `UNCERTAIN` ou validation auto a flaggé → on stocke quand même mais
  on n'affichera pas en app sans review
- `source='manual'` + `confidence='canon'` : édition humaine (admin
  futur ou correction explicite)

Règles d'usage par consommateur :

- **Matcher eBay (I2)** : utilise toutes les rows (toutes confidences).
  Le fuzzy matching tolère l'imprécision.
- **App user** (futur) : affiche uniquement `confidence='canon'`.
  Fallback sur EN sinon.
- **Admin coin details** (futur) : affiche tout avec badge `source` +
  `confidence`. Permet édition pour passer en `manual`/`canon`.

## Découpage exécution PC ⇄ VPS

| Étape | Machine | Doc d'exécution |
|---|---|---|
| Setup TOR + Hetzner | VPS Hetzner | `i18n-scrape-numista.md` §Setup |
| Scrape Numista FR+EN | **VPS** | `i18n-scrape-numista.md` |
| Import scrape → SQLite | VPS ou PC | `i18n-scrape-numista.md` §Import |
| LLM batch DE/IT/ES/NL | **PC** | `i18n-llm-translation.md` |
| Spot-check + audit | PC | `i18n-llm-translation.md` §Validation |
| Sync vers Supabase | Future session | hors scope I1 |

Justification : le VPS Hetzner a l'IP "diversifiable" via TOR, le PC a
la clé API Anthropic via direnv et permet review interactive.

## Volume estimé V1

| Métrique | Valeur |
|---|---|
| Coins ciblés | ~578 |
| Langues V1 | 6 (FR, EN, DE, IT, ES, NL) |
| Rows `coin_names_i18n` attendues | ~3470 (578 × 6, hors UNCERTAIN) |
| Fetches Numista (FR+EN) | 1156 |
| Temps scrape via TOR (10 circuits, 1 req/30s/circuit) | ~58 min |
| Appels LLM (DE+IT+ES+NL, batch 12) | ~200 |
| Coût LLM estimé (Opus 4.7) | ~$5-10 |
| Storage SQLite | ~1.5 MB |

## V1.5 — mid-tier (planifié, hors scope I1)

Ajout des 11 langues mid-tier : PT, EL, FI, SV, BG, HR, ET, LV, LT,
SK, SL. Réutilise la pipeline LLM du V1 (même prompt, juste 11 langues
en plus). Volume LLM : ×3 environ.

À déclencher quand le matcher eBay V1 est stable et qu'on veut ouvrir
sur les marketplaces secondaires (eBay.at, eBay.fi, etc.).

## V2 — long-tail + canonisation

- Long-tail : GA, MT, LB, CA (4 langues). LLM aura des performances
  dégradées (peu de training data). Spot-check humain plus intensif.
- Canonisation : remplacement progressif des `llm_v1` par `manual`
  via review humaine ou sourcing atelier-par-pays.

Pas avant V2. Documenté ici uniquement pour ne pas perdre de vue.

## Définition de "done" V1

- [ ] Schema `coin_names_i18n` étendu avec `source` + `confidence` +
  `model` (migration SQLite + recreate-and-copy si CHECK existant).
- [ ] Scrape Numista FR+EN livré et runé, couverture ≥ 95 % par
  langue.
- [ ] LLM batch DE+IT+ES+NL runé, taux d'`UNCERTAIN` ≤ 10 %.
- [ ] Spot-check manuel sur 30 coins (5/langue × 6 langues).
- [ ] Hook ajouté dans `bootstrap_coins_from_referential.py` pour
  l'enrichissement des futurs nouveaux coins (langues à câbler une par
  une).
- [ ] `progress.md` mis à jour (chunk I1 → done).

## Fichiers de cette stratégie

| Doc | Contenu | Machine cible |
|---|---|---|
| `i18n-strategy.md` (ce fichier) | Décisions + overview | — |
| `i18n-scrape-numista.md` | Chunk scrape FR+EN via TOR | VPS Hetzner |
| `i18n-llm-translation.md` | Chunk LLM batch DE/IT/ES/NL | PC |
| `i18n-probe.md` | Journal d'investigation (archivé) | — |
| `i18n-bootstrap-kickoff.md` | **Périmé — voir warning en tête** | — |

## Mémoire à sauver

Une fois cette stratégie validée :

- "Numista sous-domaines = Google Translate auto, pas canon. Seuls FR
  et EN ont du contenu humain. Stratégie aliases multi-lang = scrape
  FR/EN + LLM Claude pour les autres, marqué `source`+`confidence`."
- "Future work V2 : sourcer les ateliers de mintage nationaux pour
  remplacer les `llm_v1` par du `manual/canon`."
