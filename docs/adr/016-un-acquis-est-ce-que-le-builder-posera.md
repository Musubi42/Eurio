# ADR-016 — Un acquis, c'est ce que le builder posera

- **Statut** : ✅ Acceptée
- **Date** : 2026-08-24

## Contexte

Un écran qui pilote le travail de review doit répondre à « cette classe est-elle
nourrie ? ». `have` — les exemplaires en banque DINO — ne bouge qu'au
`build_dino_anchors` suivant : pendant une session il est FIGÉ, donc un verdict
bâti sur lui seul ressert une classe qu'on vient de remplir. D8
(`pipeline-propre/DECISIONS.md`) a donc ajouté les **acquis** : les crops
validés, pas encore bâtis, comptés en plus de `have` pour trancher.

Le principe est bon. Son implémentation promettait des exemplaires qui
n'arriveraient jamais, de deux façons, et un exemplaire promis n'est pas une
erreur neutre : `bottleneck_for` tranche sur `have + acquis ≥ target`, donc la
classe passe **`pleine`**, sort de la file, et n'en revient plus. Le verdict
devient un état absorbant que rien ne peut satisfaire.

**1. La clé.** Le compte se faisait sous `top1_eurio_id` — là où le *modèle* voit
le crop. Le builder, lui, range un exemplaire là où l'*humain* l'a mis
(`anchors._candidate_crops_for_class` : `image_assets.eurio_id IN members`).
Les deux divergent exactement là où l'image ne sépare pas deux variantes d'un
même dessin. Constaté depuis l'écran : `lu-2025-…-throne-hologram` affichait
`0/8` **+6** alors que `GET /coins/…-hologram/assets` rend `total: 0`.

**2. Le temps.** Les portes SQL décrivent les crops que le builder *envisage*,
pas ceux qu'il *pose* : il borne le pool, choisit par FPS, et écarte par
`floor_sim = 0,45` les crops trop éloignés du canonique. Un crop éligible que le
dernier build n'a pas pris a donc été **refusé**, et le prochain le refusera
pareil — sur la même donnée.

## Décision

**Un acquis est un crop que le builder posera : compté à l'étiquette humaine, et
seulement s'il est postérieur au build servi.**

Trois conséquences de forme :

| | Où |
|---|---|
| La clé de rangement du builder, en une fonction | `shared/bank_classes.py::builder_class_key_by_eurio_id` |
| Les statuts que le builder accepte, en une constante | `shared/class_need.py::BUILDER_VALIDATED_STATUSES` (verrouillée sur `anchors._VALIDATED_STATUSES` par un test) |
| Le compte au top-1, conservé mais **jamais décisif** | `ClassNeed.accepted_by_model` |

La porte temporelle se referme d'elle-même : au rebuild suivant, un crop pris
sort par la banque, un crop refusé passe derrière `built_at`. Aucun état à
matérialiser, aucune écriture.

⛔ **Toute comparaison de dates passe par `datetime()` des deux côtés.** Trois
formats cohabitent dans la base (`'2026-08-23 17:51:31'`, `'…T20:42:48Z'`,
`'…T20:41:15+00:00'`) ; l'espace vaut 0x20 et le `T` 0x54, donc comparer les
chaînes classe à l'envers. Le piège a déjà coûté 12 454 faux « périmés ».

## Mesure

Réplique du 2026-08-24 23:52, banque `2eur_all` / `dinov2-vitl14`, build
`53d22c38` (`built_at = 2026-08-24T20:41:15+00:00`) :

| | avant | après |
|---|---|---|
| Σ acquis | 1 560 sur 140 classes | **45 sur 18 classes** |
| `rebuild_would_place` | 119 | **40** |
| classes `pleine` | 108 | **99** |

Sur 1 481 crops éligibles hors banque, 45 sont postérieurs au build : les 1 436
autres ont déjà été soumis à un build complet.

Effet de bord mesuré : les 8 classes que `dino_drift` comptait comme
« gagneraient une photo » après le rebuild ont **toutes** au moins un crop
tranché après ce build (`fr-2017-…-rodin` : 9 crops, résolus 93 s plus tard).
Le plancher `floor_sim` alors invoqué n'explique donc pas ce résidu — c'était de
la fraîcheur. Le compteur porte désormais la même porte temporelle et peut
retomber à zéro ; le remettre dans `is_stale` reste un arbitrage PO.

## Alternatives considérées

| Option | Verdict |
|---|---|
| Garder la clé modèle « puisqu'elle ferme des classes » | ❌ elle ferme des classes qui n'ont rien reçu, définitivement |
| Supprimer le compte au top-1 | ❌ il porte un signal que rien d'autre ne porte : deux variantes que l'image confond |
| Matérialiser « refusé par le build N » en base | ❌ une date suffit et ne se désynchronise pas |
| Recopier les portes du builder dans chaque appelant | ❌ déjà fait deux fois (`class_need`, `dino_drift`) ; deux copies divergent en silence |

## Voir aussi

- [ADR-013](./013-la-maille-est-la-classe.md) — `class_id` se traduit, jamais ne se compare
- `docs/work-in-progress/pipeline-propre/DECISIONS.md` §D8 et §D15
