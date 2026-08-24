# Work in progress — les chantiers vivants

> **Un chantier est ici parce qu'il avance encore.** Ce qui est livré ou abandonné est
> dans [`../archive/`](../archive/README.md) ; le reste-à-faire qu'ils portaient est
> dans [`../BACKLOG.md`](../BACKLOG.md) ; le **pourquoi** des décisions est dans
> [`../adr/README.md`](../adr/README.md) ; l'**état du système** dans
> [`../architecture/README.md`](../architecture/README.md).
>
> Revu le **2026-08-24** : 40 chantiers → 13. Les 25 autres ont été archivés.

## 🎯 Par où reprendre

**[`pipeline-propre/REPRENDRE-ICI.md`](./pipeline-propre/REPRENDRE-ICI.md).** Les lots 5
et 6 de `/besoin` sont **commités et jamais vus à l'écran**. La suite commence par un
déploiement et une vérification, pas par du code — et ce déploiement **change ce que la
file sert** (Σ « à portée » 840 → 557), ce qui s'annonce au PO avant, pas après.

⚠️ **Avant de toucher au code, charge les skills** (`.claude/skills/`, indexées dans
`CLAUDE.md`). Le devShell pose le flip Direction A : une écriture locale échoue par
défaut ([ADR-009](../adr/009-direction-a-writer-canonique-unique.md)). C'est le piège
n°1 du dépôt.

⚠️ **Le clone du VPS suit encore `codeberg`.** Un `git pull` nu y ramène un arbre en
retard. Déployer avec `git fetch github repo-cleanup && git merge --ff-only
github/repo-cleanup`.

## Les chantiers

### Au front

| Chantier | Où il en est |
|---|---|
| [`pipeline-propre/`](./pipeline-propre/) | `/besoin` — quelle classe nourrir, par quel geste, quand s'arrêter. Lots 0-4 déployés, **5-6 commités non déployés**. 671 classes, couverture 250/671 |
| [`review-collaborative-v2/`](./review-collaborative-v2/) | **En production et utilisée.** Un ami tranche depuis `eurio-admin.musubi.dev`, en quarantaine. Reste : une vérif d'écriture du recadrage, le bail sur la file (lot 7), le full clean (lot 9). Décision : [ADR-012](../adr/012-review-collaborative-ecriture-directe.md) |
| [`scan-sans-retrain/`](./scan-sans-retrain/) | La voie « backbone gelé + banque » de [ADR-008](../adr/008-deux-voies-backbone-gele-et-arcface.md). Le plancher `min_exemplars` a été mesuré nuisible puis retiré. **Note d'état en tête de `PREREQUIS.md`** : où on en est, ce qui attend le PO, dans quel ordre |
| [`backup-pipeline/`](./backup-pipeline/) | Lots 0-5 livrés, **VPS uniquement**. 32 décisions dans `DECISIONS.md`, synthèse dans [ADR-014](../adr/014-sauvegarde-duplicati-et-anneaux.md). Hub : `HANDOFF-NEXT-SESSION.md` |

### Mesures et constats — à lire avant d'agir sur leur sujet

| Chantier | Ce qu'il établit |
|---|---|
| [`banque-dino/`](./banque-dino/) | Ce que vaut la banque d'ancres et ce qu'elle coûte à rebâtir. **Deux de ses constats sont périmés depuis le 2026-08-19** et portent leur correction datée |
| [`peche-dino/`](./peche-dino/) | Le périmètre d'une file de review se définit par la **prédiction**, pas par la cible du scrape. 55 crops sur 57 étaient hors sujet dans l'ancienne file |
| [`scan-quality/`](./scan-quality/) | Le cadre d'expérimentation du scan sur vrais téléphones. `DURABILITE-CORPUS.md` dit où sont les photos et comment ne pas les perdre |
| [`review-autovalidation/`](./review-autovalidation/) | `PROBLEME.md` pose le sujet : 90 % des décisions de review demandent un geste sur le **cadrage**, pas sur la classe. **`REPRENDRE-ICI.md` (2026-08-24) porte les mesures qui y répondent** et découpe le reste-à-faire en deux sessions — la review en lot qui perd du travail humain, puis le geste binaire de pêche |
| [`refacto-page-cohorte/`](./refacto-page-cohorte/) | La cible de la page cohorte, écrite après avoir construit avant d'avoir défini. Fonde [ADR-013](../adr/013-la-maille-est-la-classe.md) |

### En attente d'un geste

| Chantier | Ce qui bloque |
|---|---|
| [`giga-cohorte/`](./giga-cohorte/) | Entraîner sur les 50 pièces qui comptent (20 → 50 reconnues, 0 perdue). Plan établi sur mesures le 2026-08-18 |
| [`coin-richness/`](./coin-richness/) | ~85 %. Reste le run eBay sur la cohorte, le tour visuel 19 pages, le GO/NO-GO sur le scale à 524 (~2000 appels Numista, multi-session) |
| [`hardening-2026-07/`](./hardening-2026-07/) | **46 findings de robustesse confirmés, cadrés en 9 fiches `F01`…`F09` prêtes à dispatcher.** Rien n'a bougé depuis juillet |
| [`repo-refactor/`](./repo-refactor/) | Le méta-chantier de la branche `repo-cleanup`. Sa section « Déjà établi » contient des faits vérifiés qui ont coûté cher — la lire avant toute exploration |

## La règle

Un chantier qui n'avance plus part dans [`../archive/`](../archive/README.md), et son
reste-à-faire descend dans [`../BACKLOG.md`](../BACKLOG.md). Une décision qui survit au
chantier remonte en **ADR**. Un `work-in-progress/` qui compte quarante dossiers ne
pilote plus rien — c'est ce qu'on vient de corriger.
