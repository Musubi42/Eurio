# Les seuils — d'où ils viennent, où ils devraient vivre

> Tracé dans le code le 2026-08-18. Chaque emplacement est vérifié, pas supposé.

## Ce qui existe aujourd'hui

Trois seuils pilotent l'entraînement. **Deux sont figés dans le code Python**,
un seul est déjà configurable.

| Seuil | Valeur | Où il vit | Configurable ? |
|---|---:|---|---|
| `m_per_class` — refus dur | **4** | `ml/training/foundation/preflight.py:43` (défaut) **et** config d'itération | ✅ **oui**, par itération |
| `MIN_REAL` — alerte « pauvre » | **10** | `ml/store/funnel_constants.py:29` | ❌ non, constante Python |
| `TRAINING_TARGET` — cible après augmentation | **100** | `ml/training/foundation/enrichment.py:32` | ❌ non, constante Python |

### Ce que chacun fait vraiment

- **`m_per_class = 4`** — sous 4 sources réelles, le run est **refusé** :
  l'entraînement tournerait sur des doublons rééchantillonnés, donc sans signal.
  C'est un seuil **technique**, lié à la façon dont un batch est composé
  (combien d'exemplaires d'une même classe par lot).
  Il est déjà surchargeable : `DEFAULT_TRAINING_CONFIG` le porte
  (`ml/serving/iteration_runner.py:78`), et chaque itération stocke sa config.

- **`MIN_REAL = 10`** — sous 10 crops eBay réels, la classe est **signalée
  pauvre** (badge « underfed »), sans blocage. C'est le fameux « plancher 10 ».
  Le commentaire du code le dit lui-même : *repère qualité, n'affecte pas la
  cible* (`ml/training/iteration_augmentations.py:87`).

- **`TRAINING_TARGET = 100`** — cible d'images **après augmentation**. Le facteur
  d'augmentation est dérivé : `ceil(100 / sources réelles)`. Une classe à 10
  réelles est donc multipliée ×10 ; une classe à 50 réelles ×2.

## Pourquoi c'est un problème

**Le seuil de 10 est arbitraire et personne ne l'a jamais éprouvé.** C'est un
pari : « 10 photos réelles suffisent si on augmente ×10 ». Il n'a été confronté
à aucune mesure de reconnaissance.

Or c'est exactement le genre de valeur qu'on veut faire bouger *à la lumière des
résultats* :

> Si les classes à 50 photos réelles ne se trompent jamais et que celles à 10
> échouent, on monte le seuil. Sans toucher au code, sans redéployer.

Aujourd'hui, changer 10 en 25 demande de modifier une constante Python, de
redéployer l'API locale ET le canonique. C'est un frein direct à
l'expérimentation, donc au but du projet.

## Ce qu'on veut

**Les seuils vivent en base, pas dans le code.**

Principes proposés :

1. **Une valeur par défaut globale**, en base, modifiable sans redéploiement.
2. **Une surcharge par cohorte** — une cohorte d'essai peut viser plus haut sans
   changer la règle générale.
3. **La valeur utilisée est figée dans l'itération**, comme `m_per_class` l'est
   déjà. Sinon on ne peut plus dire *avec quel seuil* un modèle a été entraîné,
   et la comparaison entre runs perd son sens.
4. **Le front ne définit jamais un seuil.** Il lit et affiche celui que le back
   annonce. (Aujourd'hui `FLOOR`/`GOAL` sont écrits en dur dans
   `admin/packages/studio-local/src/features/lab/composables/useCohortFloor.ts`
   — c'est une dette introduite le 2026-08-18, à retirer.)

## Une distinction à ne pas perdre

Trois notions différentes portent aujourd'hui le mot « assez ». Les garder
séparées, avec des noms distincts à l'écran :

| Notion | Question | Nature |
|---|---|---|
| refus dur (`m_per_class`) | l'entraînement a-t-il un sens ? | **technique**, imposé par le batch |
| plancher (`MIN_REAL`) | la classe est-elle assez nourrie ? | **choix produit**, à régler par l'expérience |
| cible (`TRAINING_TARGET`) | combien d'images après augmentation ? | **paramètre de bake** |

Le désordre actuel vient de ce qu'un écran affiche « ≥ 100 par classe », un autre
« plancher 10 », un troisième « seuil dur 4 » — trois réponses à ce qui ressemble
à la même question.

## Questions tranchées — voir `DECISIONS.md`

Les trois questions que ce fichier laissait ouvertes ont leur réponse :

| Question | Réponse | Où |
|---|---|---|
| Un seuil **par classe** ? | Le schéma le porte (`scope='class'`), l'écran ne l'expose pas — aucune mesure ne dit aujourd'hui quelle classe est difficile | `DECISIONS.md` §D2 |
| Une classe **déjà prête** quand le seuil monte ? | Elle redevient incomplète, c'est voulu ; l'écran nomme le changement de règle au lieu d'afficher une régression | §D1 |
| Un seuil **de promotion** distinct ? | Non — la promotion se décide sur le benchmark, pas sur un compteur de photos | §D3 |

**Implémenté le 2026-08-18.** Les trois seuils vivent en base
(`training_thresholds` au canonique, migration `0006`), résolus par
`ml/store/thresholds.py` (classe → cohorte → global → constante), réglables par
`PUT /lab/thresholds` et `PUT /lab/cohorts/{id}/thresholds`, et **gelés dans
`experiment_iterations.training_config_json`** à la création d'une itération.
Les constantes Python restent comme filet : table absente = comportement d'avant,
à l'identique.
