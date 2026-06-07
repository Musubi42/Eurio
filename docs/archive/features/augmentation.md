# Feature : Augmentation — fabriquer des variantes représentatives

> Question centrale : **à partir des photos sources qu'on a,
> comment fabrique-t-on des variantes qui couvrent les conditions
> in-the-wild ?**
>
> L'augmentation est le pont entre `scrape` (les photos qu'on
> possède) et `model` (les images que voit ArcFace pendant le
> training). Une bonne aug ne peut pas compenser zéro photo source ;
> mais une mauvaise aug gâche un bon corpus.

## État actuel

- **Recipe baseline figée** : `e6ea78f284ff` (utilisée en test-2 et
  test-1 v2).
  - background : prob 0 (désactivé)
  - perspective : prob 0.8, max tilt 15°
  - relighting : prob 0.8, ambient 0.65, intensity 0.6–1.25
  - overlays : prob 1.0, patina + dust, opacity 0.15–0.4
  - count cible : 100 augs/coin, 50 utilisées
- **Pré-bake** : les variantes sont générées en avance et stockées
  sous `ml/datasets/<nid>/augmentations/<iid>/`, lues au training
  via symlinks. Permet de comparer différentes recipes sans recoder
  le pipeline.

## Ce qu'on observe (test-1 v2)

- La recipe **fonctionne sur les commémoratives à design unique**
  (FI-2017, FR-2016, IT-2016 → 3/3 live).
- Elle **ne crée pas assez de marge** sur les standards UE
  (AT/BE/ES) — le cluster reste serré, mean_spread = 0.09, top-1/2
  collés à <0.05 sur certains cas.
- 3 erreurs live résiduelles : AD-2014 bright, ES-1999 dim,
  ES-1999 tilt. Toutes vont vers IT-2016 ou AD-2014. **Pattern
  d'attracteur** sur conditions extrêmes — la recipe couvre mieux
  certaines classes que d'autres.
- DINO cos aug-vs-real n'est **pas prédictif** (validé deux fois) —
  ne pas piloter l'optim de recipe sur cette métrique.

## Trois axes d'optim possibles

### A. Pousser les augs sur les axes faibles

Hypothèses à valider par itération lab :

- **Plus de tilt** (15° → 25° / 35°) — la plupart des erreurs live
  arrivent sur la condition `tilt`.
- **Motion blur léger** — pas dans la recipe actuelle, courant en
  capture device.
- **Glow / specular highlights** — pour casser les confusions
  bright qui collent les standards UE.
- **Finger smudges / occlusions partielles** — l'utilisateur tient
  parfois la pièce.
- **Variations de fond** (background prob > 0) — actuellement
  désactivé, mais le wild capture rarement un fond neutre.

Chaque variation est une nouvelle recipe à bencher contre la
baseline `e6ea78f284ff` sur la même cohort.

### B. Augmentation à partir de plusieurs photos sources

C'est la grande inflexion attendue de la feature `scrape`. Quand
chaque eurio_id a 10-50 photos réelles différentes, l'augmentation
cesse d'être "fabriquer du wild à partir d'une photo studio" et
devient **diversification d'un pool wild déjà varié**.

Conséquences attendues :
- Moins besoin d'overlays patine/dust artificiels — il y a déjà des
  pièces vraiment usées dans le pool.
- Moins besoin de relighting agressif — il y a déjà des photos
  variées en lumière.
- Plus besoin d'aug "structurelle" qui injecte la variabilité que
  la photo unique ne donne pas.
- Plus besoin d'aug "régularisante" plus douce qui empêche
  l'overfit sur les défauts spécifiques de chaque source.

Donc : **scrape change la nature même du levier augmentation**.
À documenter au fur et à mesure que le pool grossit.

### C. Augmentation conditionnée (diffusion-based)

Plus expérimental : générer des variantes "lit de côté, légèrement
usée, tenue à la main" via un modèle de diffusion conditionné sur
la photo source. C'est ce que la littérature (DATUM, DoGE
CVPR'24) propose pour bridger studio→wild quand on n'a pas de
corpus user.

Stopgap intéressant **avant** que `scrape` ait un volume suffisant.
Coût compute lab non négligeable mais zéro impact runtime
(génération offline).

À considérer en deuxième temps, après avoir mesuré ce qu'apporte un
vrai corpus scrapé.

## Méthodologie d'optim

L'augmentation se mesure par **itération lab côte à côte sur la
même cohort** :

1. Geler une cohort baseline (ex: `mix-zone-7-cls-v2` actuelle).
2. Recipe baseline = la recipe actuelle (`e6ea78f284ff`).
3. Recipe candidate = variante isolée (un seul axe modifié).
4. Bench R@1 strict + live R@1 + per-class breakdown.
5. Verdict : amélioration significative et reproductible (pas
   juste seed-dépendante).

L'isolation par `iteration_id` (lab-prod-refacto phase 2) rend ça
trivial : chaque candidate vit dans son dossier sans polluer les
autres.

## Métriques pour piloter cette feature

- **Live R@1 strict** par classe — métrique de vérité (le bench est
  un proxy bruyant, le R@1 train n'a pas de sens).
- **mean_spread** top-1/top-2 — proxy de la marge créée par la
  recipe. Plus c'est haut, plus la recipe sépare les classes.
- **Per-condition R@1** (bright / dim / tilt) — détecte les axes
  sous-représentés dans la recipe.
- **Confusion matrix** — révèle les attracteurs (ex: IT-2016 sur
  test-1 v2).
- **Aug-vs-DINO cos** — sanity check uniquement, pas un proxy.

## Pistes ouvertes

- **Recipe per-class adaptive** : recipe différente selon la
  difficulté observée (plus d'augs sur les standards qui collapsent).
  Risque : asymétrie d'apprentissage. À évaluer.
- **Curriculum** : augs douces au début du training, plus dures
  ensuite. Standard dans la littérature, jamais essayé ici.
- **Mixup / CutMix** : levier classique deep learning, jamais
  utilisé. Pertinence sur fine-grained discutable.
- **Auto-recipe** : faire converger la recipe automatiquement
  contre une métrique cible (e.g. live R@1). Coûteux, à n'envisager
  qu'après stabilisation.

## Implémentation

L'implémentation actuelle vit dans `ml/augmentations/` (recipes
+ baker). L'UI lab permet de créer/modifier des recipes et de
suivre les itérations.

Nouvelles recipes : créer via l'admin `/lab/recipes/new` (ou la
table directe). Référencées par les itérations via `recipe_id`.

Le bake écrit dans `ml/datasets/<nid>/augmentations/<iid>/`, lu
au training via symlinks. Pas de duplication d'image, pas de
pollution inter-itérations.

## Liens vers features voisines

- **Scrape** : amont direct. Doubler le pool source change la
  stratégie d'aug. Cf. [`scrape.md`](./scrape.md).
- **Model** : aval direct. Une aug qui marche sur ArcFace
  from-scratch peut être superflue sur DINOv2 (le foundation a
  déjà absorbé une bonne partie de la variabilité). Cf.
  [`model.md`](./model.md).

## Implémentation référencée

- Recipes & baker : `ml/augmentations/recipes.py` +
  `ml/augmentations/iteration_augmentations.py`
- UI lab (création / preview) : composables dans
  `admin/packages/web/src/features/lab/`
- Track UX du lab : [`training-pipeline/refacto/`](../training-pipeline/refacto/)
- Journal des itérations : [`training-pipeline/journal/`](../training-pipeline/journal/)
