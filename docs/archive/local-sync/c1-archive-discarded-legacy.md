# C1 — archive des 20 décisions legacy écartées au re-seed du Mac (2026-07-03)

> Traçabilité de la réconciliation C1 (migration Direction A). Le Mac a été
> re-seedé depuis le VPS canonique (`pull-replica`), effaçant 189 lignes que son
> `bootstrap_backfill` avait corrompues localement. **Ton travail de tri du jour
> (14 décisions humaines) était déjà sur le VPS — rien perdu de récent.**
>
> Ci-dessous les **20 seuls écarts « jadis humains »** : de VIEILLES décisions
> (`machine=None`, pré-système-de-sync) que le canonique VPS avait déjà
> **superseded** par du traitement ultérieur, et que le bootstrap du Mac avait
> ressuscitées. Décision PO (2026-07-03) : **faire confiance au VPS.** Conservé
> ici au cas où l'une mériterait d'être re-tranchée dans le nouveau système.
>
> Backups d'avant re-seed : `eurio.db.pre-migA-20260703` sur Mac / VPS / PC.

| asset | colonne | reason legacy | valeur Mac (écartée) | valeur VPS (gardée) |
|---|---|---|---|---|
| `35f347c0c974` | eurio_id | deferred_lot | es-2016-old-town-of-segovia | es-1999-standard-juan-carlos-i-1st |
| `9aad20de41f0` | eurio_id | deferred_lot | es-2016-old-town-of-segovia | es-1999-standard-juan-carlos-i-1st |
| `a79f1eff3299` | eurio_id | deferred_lot | es-2016-old-town-of-segovia | es-1999-standard-juan-carlos-i-1st |
| `cc792f9f922b` | eurio_id | deferred_lot | es-2016-old-town-of-segovia | es-2010-standard-juan-carlos-i-2nd |
| `ce56435e0737` | eurio_id | deferred_lot | es-2016-old-town-of-segovia | es-1999-standard-juan-carlos-i-1st |
| `19bf32458ee8` | eurio_id | human_decided_lot | de-2020-german-polish-reconciliation | de-2020-brandenburg-bundeslander |
| `6d7772b1a745` | eurio_id | human_decided_lot | de-2020-german-polish-reconciliation | de-2020-brandenburg-bundeslander |
| `e7d4caa90036` | eurio_id | human_decided_lot | de-2020-german-polish-reconciliation | de-2020-brandenburg-bundeslander |
| `e8ef3523eaf7` | eurio_id | human_decided_lot | de-2020-german-polish-reconciliation | de-2020-brandenburg-bundeslander |
| `d3af872bced1` | eurio_id | human_decided_lot | fi-2016-100th-birth | fi-2016-90th-death |
| `dc16d9e7e9ab` | eurio_id | human_decided_lot | fi-2017-100-years-independence | fi-2009-200th-autonomy |
| `90282ef40b34` | eurio_id | reflagged_from_coin | at-2005-50th-state-treaty | at-2016-200th-national-bank |
| `82215687ca79` | eurio_id | trash_other | es-2016-old-town-of-segovia | es-2015-standard-felipe-vi |
| `17739a2d9673` | resolution_status | reflagged_from_coin | needs_review | manual |
| `2eb40310701e` | resolution_status | reflagged_from_coin | needs_review | manual |
| `7712f9147ce7` | resolution_status | reflagged_from_coin | needs_review | manual |
| `bde85aba9171` | resolution_status | reflagged_from_coin | needs_review | manual |
| `3a0fb275a394` | training_eligible | human_decided | 1 | 0 |
| `a31dea6b7e28` | training_eligible | human_decided | 1 | 0 |
| `a3540b819f15` | training_eligible | human_decided | 1 | 0 |

**Lecture** : la majorité sont des `deferred_lot` (le review humain avait *reporté*
la décision → valeur provisoire) que le canonique a depuis classés proprement en
standards. Les `human_decided_lot` de-2020 (reconciliation → brandenburg) sont les
plus discutables, mais restent pré-sync et re-tranchables. Le VPS fait foi.
