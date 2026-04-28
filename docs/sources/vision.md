---
title: Vision — page admin /sources
date: 2026-04-26
status: draft
---

# Vision — page admin `/sources`

## Pourquoi cette page existe

Eurio agrège aujourd'hui plusieurs sources externes pour bâtir et maintenir son
référentiel canonique :

| Source | Type | Données fournies | Volume actuel |
|---|---|---|---|
| **Numista — match** | API REST (clés rotées, ~1800 calls/mois soft) | Détection + matching de nouvelles pièces (Numista IDs ↔ eurio_id) | À chaque sortie commémo |
| **Numista — enrich** | API REST (même quota partagé) | Métadonnées canoniques (titre, dates, designer, atelier) | ~562 enrichis sur 1240 |
| **Numista — images** | API REST (même quota partagé) | Téléchargement des images obverse/reverse | ~ idem |
| **eBay Browse API** | API REST (5000 calls/jour) | Prix actifs P25/P50/P75, samples, velocity | ~116 commémos enrichies sur 517 |
| **LMDLP** | Scrape HTML | Cotation FR collectionneur (cross-validation) | snapshot 2026-04-13 |
| **Monnaie de Paris** | Scrape HTML | Catalogue officiel FR | snapshot 2026-04-13 |
| **BCE** (ECB.europa.eu) | Scrape HTML | Annonces commémoratives officielles | snapshots 2004-2025 |
| **Wikipedia** | Scrape HTML | Backfill métadonnées par pays | 21 pays |

Aujourd'hui **tout se déclenche en CLI local** (`go-task ml:fetch-numista`,
`uv run python -m market.scrape_ebay`, etc.). Quand quelque chose ne va pas —
quota Numista bientôt épuisé, prix eBay qui n'a pas été rafraîchi depuis 2 mois,
nouvelle pièce qui sort sans qu'on s'en rende compte — il n'y a aucun endroit
dans l'admin pour le voir. Il faut ouvrir une SQLite, lister un dossier, lire un
JSON.

`/sources` est ce **panneau de contrôle unique** : un coup d'œil suffit pour
savoir l'état de la chaîne d'ingestion.

## Principes

1. **Lecture seule en V1.** Aucun bouton "Fetch" qui lance un job. La page
   *montre*, elle ne *déclenche pas*. Le déclenchement UI (V2) demande une
   refonte job runner non triviale — voir `v2-triggering.md`.
2. **Une page, huit cartes.** Pas de sous-page par source en V1. Numista est
   éclaté en 3 cartes (`match`, `enrich`, `images`) car les cadences
   attendues sont très différentes — mais elles partagent le même quota
   mensuel sous-jacent (affiché identiquement sur les 3). Toutes les cartes
   sont structurellement comparables (état + quota + dernier fetch +
   couverture + delta). Une grille suffit.
3. **Source de vérité = ce qui existe déjà.** On ne crée pas de nouvelle
   table SQLite "registry" : on lit les snapshots dans `ml/datasets/sources/`,
   le `eurio_referential.json`, et les compteurs `api_call_log`
   (extension générique de l'actuel `numista_key_usage`).
4. **Le delta est first-class.** Pas juste "dernier fetch = il y a 13 jours",
   mais "dernier fetch = il y a 13 jours, +3 nouvelles pièces détectées,
   prix médian +12% sur l'échantillon stable". Le delta est ce qui transforme
   la page d'un dashboard passif en un signal d'action.
5. **Cohérence design avec l'admin existant.** Tokens Eurio
   (`--indigo-700`, `--gold`, `--surface`, `--surface-3`,
   `--success`/`--warning`/`--danger`), Tailwind + shadcn-vue, header
   `font-display italic`, labels `font-mono uppercase tracking-wider`. Voir
   `frontend.md` pour la maquette détaillée et la référence au prototype HTML
   (`docs/design/prototype/admin/`).

## Public visé

Solo dev (Raphaël). La page doit fonctionner pour quelqu'un qui ouvre l'admin
une fois par mois "pour voir où on en est" autant que pour quelqu'un qui
l'utilise au quotidien pendant un sprint d'ingestion.

## Non-goals (V1)

- ❌ Déclencher un fetch depuis l'UI → V2, doc `v2-triggering.md`
- ❌ Page détail par source (drill-in `/sources/:id`) → V2
- ❌ Édition de la liste des sources → reste en code (`SOURCES_REGISTRY` Python)
- ❌ Comparaison cross-sources de prix (LMDLP vs eBay) → autre feature, pas ici
- ❌ Alerting / notifications quand quota bas → V2 (cron + Slack/email)

## Découpage du travail

| Doc | Sujet | Périmètre |
|---|---|---|
| `vision.md` | Ce fichier — produit, principes, scope | — |
| `frontend.md` | UI/UX, layout, composants, mock prototype | À spécifier |
| `backend.md` | Endpoint `/sources/status`, agrégation, contrats | API FastAPI |
| `quotas.md` | Refacto `numista_key_usage` → `api_call_log` générique | SQLite ml/state |
| `temporal.md` | Détection nouvelles pièces, deltas, historique prix, cadence | Le plus gros sujet |
| `v2-triggering.md` | Notes pour V2 — pourquoi non-trivial, pré-requis arch | Memo futur |

## Lien avec l'app Android

L'historique des prix construit par `coin_market_prices` (INSERT-only) sert à
deux choses :

- **Côté admin /sources** : delta inter-runs, validation que le scrape eBay
  fonctionne ("on a des nouveaux prix, ils sont cohérents avec le run
  précédent")
- **Côté app Android (V2 produit)** : sparkline d'évolution dans la fiche
  coin scannée — "ta pièce vaut ~5.90€ aujourd'hui (P50), +12% sur 6 mois"

Les deux usages tirent sur la même table. C'est pour ça que l'INSERT-only
(jamais d'upsert écrasant) est non-négociable.
