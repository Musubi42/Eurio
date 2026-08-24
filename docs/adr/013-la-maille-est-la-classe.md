# ADR-013 — La maille du modèle est la CLASSE, jamais la pièce

- **Statut** : ✅ Acceptée
- **Date** : 2026-08-18 (posée) · 2026-08-23 (les trois conventions diagnostiquées)

## Contexte

Le modèle n'apprend pas « une pièce », il apprend **un dessin**. Plusieurs pièces qui
partagent leur face nationale forment **une seule classe**, et leurs photos
s'additionnent. Mesuré sur la cohorte `giga-40-vague1` : **129 pièces = 40 classes** ;
le drapeau européen 2015 regroupe à lui seul 21 pièces.

Le désordre venait de compter dans les deux unités à la fois : la page cohorte
affichait 129 lignes, le contrôle avant entraînement en comptait 40. Même question,
deux nombres, et aucun écran ne disait lequel était le bon.

Pire, **trois conventions différentes portent le nom `class_id`** dans la base. Le
problème s'est présenté **quatre fois** au cours de la seule implémentation de
`/besoin` — c'est le défaut le plus coûteux du dépôt après le flip Direction A.

## Décision

**Tous les écrans, tous les comptages et tous les seuils comptent en classes.** La
pièce n'est qu'un détail dépliable.

Et **`class_id` se traduit, jamais ne se compare directement**. Les trois conventions,
telles que mesurées :

| Où | Règle |
|---|---|
| `coins` | `COALESCE(design_group_id, eurio_id)` — un Erasmus est `eu-erasmus-2022` |
| `dino_class_references.class_id` | l'**`eurio_id` du représentant** : la commémorative elle-même ; pour une courante, le premier membre du groupe (`anchors.py`, `_class_specs_2eur_all`) |
| `encoder_bench_gold.class_id` | l'`eurio_id` représentant du groupe (`ORDER BY year, eurio_id`) |

**Une seule fonction traduit** : `ml/shared/bank_classes.py::bank_class_ids_for_class`.
Toute requête qui joint la banque d'ancres à `coins` sans passer par elle est fausse —
y compris celles écrites dans les docs et dans les skills.

Preuve du coût : une requête écrite avec la convention `coins` rend **2166 crops
« hors banque »** qui sont pourtant en banque. **Elle ne lève rien.** Elle rend un
nombre plausible.

## Alternatives considérées

| Option | Verdict |
|---|---|
| Compter en pièces partout | ❌ Ce n'est pas ce que le modèle apprend. Une cohorte de 129 pièces qui produit 40 classes rend tous les seuils (« 8 exemplaires par classe ») ininterprétables |
| Afficher les deux nombres côte à côte | ❌ Deux nombres pour la même question, c'est le désordre qu'on corrige. La pièce reste accessible, mais **dépliée**, jamais comptée |
| Unifier les trois `class_id` en base par migration | ⏸️ Souhaitable, mais c'est une migration lourde sur des tables que la banque, le bench et le référentiel lisent tous. La fonction de traduction est le pont, et elle doit exister de toute façon pour l'historique |
| Renommer les colonnes pour lever l'ambiguïté | 🟡 Pas fait. Ce serait le vrai remède, et il reste ouvert |

## Conséquences

**Bonnes.** Les écrans, la banque et le préflight de cohorte comptent enfin la même
chose. `/besoin` peut dire « quelle classe nourrir, par quel geste, et quand
s'arrêter » sans ambiguïté d'unité.

**Mauvaises, et assumées.**

- **La traduction reste une discipline, pas une contrainte.** Rien n'empêche
  d'écrire un `JOIN` direct : ça compile, ça tourne, ça rend un nombre faux.
  **Devant toute requête qui compare un `class_id`, demander *lequel*.**
- Le bake tire des pièces hors cohorte (14 % du dataset, mesuré sur une cohorte de 6)
  — c'est la conséquence directe de la maille `design_group`, et c'est assumé.
- Les docs et les skills antérieures à ce diagnostic peuvent porter des requêtes
  fausses. Elles sont corrigées au fil de l'eau, pas d'un coup.

## Voir aussi

- Skill `eurio-banque` (la maille `class_id`, la courbe références/classe)
- Skill `eurio-cohort` (préflight, expansion `design_group`)
- [`../work-in-progress/pipeline-propre/VISION.md`](../work-in-progress/pipeline-propre/VISION.md) §V4 — le diagnostic, avec ses requêtes
- [`../work-in-progress/refacto-page-cohorte/VISION.md`](../work-in-progress/refacto-page-cohorte/VISION.md) — la cible côté écran
