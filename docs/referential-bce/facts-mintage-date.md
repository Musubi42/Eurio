# Axes tirage + date d'émission BCE (facts lang-invariants)

> Chantier BCE, axes 2 (tirage) & 3 (date). Livré 2026-05-30.
> Voir aussi `i18n-descriptions.md` (axe 4) et la mémoire `project_bce_i18n`.

## Objectif

Le **tirage** (`issuing_volume`) et la **date d'émission** (`issuing_date`) de la
BCE sont **identiques dans les 24 langues** → on les parse depuis la page **EN**
uniquement (aucun fetch supplémentaire, snapshots déjà cachés par le harvester
i18n).

## Schéma (décidé avec le user)

Tout dans `coin_observations` (provenance-first, **n'écrase pas** `coins.mintage`
— d'ailleurs vide ; le tirage Numista vit dans `mint_release_observations`
per-issue). 1 row par (eurio_id, `bce_official`, type) :

- `observation_type='mintage_official'` → payload `{value: int|None, raw_text}`
- `observation_type='issuing_date'`     → payload `{year, month, day, raw_text}`

`coins.release_date` **n'a pas** été créée (option chantier D écartée) : provenance
d'abord, on promeut une colonne canonique plus tard si besoin.

## Parsers extractifs (`referential/bce_facts.py`)

Les valeurs contiennent du bruit → parsers **extractifs** (trouvent le motif,
ignorent le reste), `raw_text` toujours conservé :

- **Tirage** : `« 1.6 million coins »` → 1 600 000 ; `« 100,000 coins »`,
  `« 2 000 000 coins »`, `« max 750 000 coins »`. **489/489 parsés.**
- **Date** : `« September 2017 »` → {2017, 9} ; `« 21 October 2019 »` → +day ;
  `« Fourth quarter 2022 »` → année seule (month=None). **487/487 année OK,
  427 avec mois.**
- Bruit géré : pied de page « Copyright 2026, European Central Bank » que la
  dernière pièce d'une page absorbe (n'affecte pas l'i18n, champs antérieurs) ;
  coquille BCE « I ssuing date » (espace) qui fait baver la date dans le volume.

Matching `eurio_id` via `BceAdapter.match_group` (assignation 1-to-1, cf.
`i18n-descriptions.md`).

## Cross-check tirage BCE ↔ Numista (consigne trust-model)

`coins.mintage` étant vide, on compare le BCE total à la **somme de tous les
types d'issue Numista** (CIRC + BU + COIN_CARD + PROOF) par eurio_id depuis
`mint_release_observations`.

Résultat (470 coins) : **193 exacts, 362 à ±5 % (77 %), 108 divergences >5 %**.

**Investigation** (MT 2023, HR 2023, LU 2015, ES 2016) → divergence
**définitionnelle, pas un bug** :
- petits ateliers (MT/HR) : BCE total = somme exacte de tous les types Numista
  (ex. MT 2023 : 95 500 = CIRC 5 000 + BU 10 000 + COIN_CARD 80 500) ;
- résidus >5 % : Luxembourg systématique (BCE = **tirage autorisé** > minté réel,
  ×2.7-3), Malta (Numista incomplet), variantes (FR 2024 Olympics *coloured* =
  sous-ensemble), joint-issues où Numista agrège plusieurs ateliers (FR 2019
  mur de Berlin 15M Numista vs 10M BCE).

**Règle** : les deux sont légitimes → **stockés séparément avec provenance, sans
réconciliation ni écrasement**. BCE `mintage_official` = total autorisé officiel
(autoritatif), Numista per-issue reste à sa place. Le cross-check est informatif
(reporté à chaque run), pas une réconciliation.

## Lancer

```bash
go-task ml:scrape-bce-facts                  # 2004→année-1
go-task ml:scrape-bce-facts -- --year 2023
go-task ml:scrape-bce-facts -- --dry-run     # cross-check sans écrire
```

Idempotent (UPSERT sur `UNIQUE(eurio_id, source, observation_type)`).

## Stats du run initial (2026-05-30)

- **470 `mintage_official`** + **468 `issuing_date`** observations écrites.
- 474 coins matchés (même matcher 1-to-1 que i18n/images).
- Cross-check : 193 exacts, 362/470 à ±5 %, 108 divergences >5 % (stockées, non réconciliées).
