# research/ — mesures empiriques & découvertes

Sous-dossier des **probes, benchmarks et findings** du chantier
`ebay-multi-marketplace`. Distinct des docs du dossier parent :

- Dossier parent = **specs, kickoffs, décisions, runbooks** (ce qu'on
  fait et comment).
- `research/` = **ce qu'on a mesuré** et ce qu'on en a appris.

## Index

| Doc | Sujet | Statut |
|---|---|---|
| [marketplace-language-distribution.md](marketplace-language-distribution.md) | Quelle langue de titres domine sur chaque marketplace eBay (chunk V1) → `MARKETPLACE_ACTIVE_LANGS` | ✅ livré |
| [marketplace-routing-benchmark.md](marketplace-routing-benchmark.md) | Quel marketplace maximise le recall par pays d'origine → `_ROUTES` | ✅ concluant — routing `{DE, ES}` fixe acté |

## Probes connexes (dossier parent)

Certaines investigations vivent encore dans le dossier parent pour des
raisons d'historique de références :

- `../i18n-probe.md` — probe HTML Numista (a montré : seuls FR/EN
  traduits, WAF à ~7 req).
- `../language-probe.md` — spec de la tokenisation theme multilingue
  (consommée par I2).

## Convention

Une découverte qui change une décision produit doit :
1. être journalisée dans le doc `research/` correspondant ;
2. déclencher la mise à jour de la spec/décision dans le dossier parent
   (`marketplace-map.md`, `progress.md`, etc.) ;
3. si elle est durable et non-évidente, être ajoutée à la mémoire
   projet.
