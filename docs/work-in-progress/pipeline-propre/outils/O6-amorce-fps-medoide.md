# O6 · L'amorce du FPS au médoïde

> **Statut : LIVRÉ le 2026-08-22** (commit `244c06b3`, `--seed-order medoid`
> devenu le défaut du builder). Mesuré par bras témoin : **+3,7 pts à N=10**,
> et le creux à N=1 supprimé (76,2 → 71,8 en `fps` ; 76,0 → 86,8 en médoïde).
> Banque de production `a55e6594da32`. Cf. [`../JOURNAL.md`](../JOURNAL.md).
> Pas de station — c'est la **racine**.
> Améliore la pêche, la review, le verdict et le scan d'un coup.
> Prolonge [`eurio-banque`](../../../../.claude/skills/eurio-banque/SKILL.md) §3
> et [`COURBE-REFERENCES.md`](../../scan-sans-retrain/COURBE-REFERENCES.md).

## Le geste

Changer **le premier crop que le FPS retient** pour chaque classe. Aujourd'hui
c'est le point le plus lointain ; ce serait le médoïde — le plus représentatif.

## Ce qui est mesuré, et pourquoi ça vaut le coup

Le *farthest-point sampling* choisit d'abord le crop le plus **diversifiant**,
donc le plus **atypique** de sa classe. Un exemplaire atypique en banque agit
comme un **faux attracteur** : il attire des crops qui ne sont pas de la classe.

Le mécanisme, longtemps inféré, a été **mesuré** le 2026-08-20 — à **nombre
d'ancres strictement identique** (795 lignes, un exemplaire par classe), en
gardant le rang le *moins* diversifiant au lieu du plus :

```bash
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db ./.venv/bin/python \
  -m scripts.bench_refs_curve --model dinov2_vitl14 --refs 0 1 2 3 --rank-order last
# 76,2 %   77,8 %   78,4 %   80,9 %      ← contre 73,8 % au rang 1 en ordre `first`
```

**77,8 % contre 73,8 %.** Le creux à N=1 de la courbe disparaît. Ce n'est pas un
effet de volume : le nombre de vecteurs est le même des deux côtés.

C'est le **meilleur rapport valeur/effort du chantier** : 4 à 6 points sans une
seule donnée nouvelle, sans un crop de plus à trancher, sans un appel eBay.

## Ce que `--rank-order last` n'est pas

**Une sonde, pas un builder.** Elle tronque la banque *après coup* en gardant les
derniers rangs FPS ; aucun build réel ne produit cette banque. Elle prouve le
mécanisme, elle ne livre pas le remède.

Le remède est dans `training/foundation/anchors.py` :
`farthest_point_select` doit **amorcer au médoïde** — le crop dont la distance
moyenne aux autres crops de la classe est minimale — puis continuer en FPS
normal. Les rangs suivants restent des points lointains ; seul le premier change.

## Le préalable non négociable

⛔ **La banque servie porte encore `min_exemplars = 2` ; le code ne l'applique
plus.** Le build `365dcab2a253` (2026-08-20 14:27) a été bâti avec le plancher —
1 533 → 1 495 ancres, 182 → 124 classes à exemplaires, 68 classes ramenées au
canonique seul. Le défaut est depuis revenu à 1.

Conséquences si on rebâtit sans traiter ça :

1. **Deux changements bougent à la fois** — l'amorce du FPS *et* le retour des
   68 classes. Le delta mesuré ne serait attribuable à ni l'un ni l'autre.
2. **Le garde P1 ne dirait rien.** Il compte les classes à ≥ 2 exemplaires
   (`USEFUL_MIN_REFS`), un compte que le retour à 1 laisse invariant. Le
   découplage est voulu ; l'inversion sera donc **silencieuse**.

**Deux options, à trancher avant de coder :**

| | option | ce qu'elle donne | ce qu'elle coûte |
|---|---|---|---|
| A | poser `min_exemplars = 2` en base le temps de la mesure, mesurer l'amorce seule, puis retirer | un delta attribuable | un rebuild de plus (237 s + ~41 min de P3) |
| B | rebâtir une seule fois et mesurer les deux ensemble | moitié moins cher | on ne saura pas attribuer, et le §3 de la skill dit déjà que le plancher coûte ~1 point |

**Recommandation : A.** On vient précisément de payer le prix d'un changement
mal attribué. Poser 2 en base est **une ligne dans `dino_thresholds`**, sans
toucher au code — le mécanisme est resté entier et couvert par 14 tests.

## Le protocole de mesure

Le même que celui qui a réfuté le plancher, parce qu'il a fait ses preuves :

1. **Contrôle à N=0.** Les deux banques doivent rendre le même score à 0,1 pt
   près (671 canoniques, aucun exemplaire). Si elles divergent, la population
   held-out a changé et la comparaison ne vaut rien.
2. **Held-out, pas fuité.** 779 des 1 958 crops du gold *sont* des lignes de la
   banque ; les noter contre elle mesure une similarité de 1,0 avec soi-même.
3. **McNemar exact** (`shared/stats/paired.py`) sur chaque palier. Un écart de
   courbe sans sa p-value ne se cite pas.
4. **Par classe autant qu'en agrégat.** 1 073 des 1 179 crops held-out (**91 %**)
   appartiennent aux 57 classes riches : un agrégat held-out est une mesure des
   classes riches déguisée en mesure de la banque. C'est exactement ce qui a
   fait poser le plancher.

## Le coût complet

| étape | durée |
|---|---|
| écrire l'amorce médoïde dans `farthest_point_select` | ~½ journée |
| rebuild `go-task ml:dino-anchors:build -- --force --kind 2eur_all` | **237 s** |
| backfill obligatoire des prédictions | **~28 à 41 min** |
| courbe `vitl14`, 7 paliers, 3 populations | **~7 min** |

⚠️ Le backfill n'est pas optionnel : sans lui, la file de review continue de
trier sur les vecteurs de l'ancienne banque. Et **il sort en code 0 même en
erreur** (défaut M8) — la preuve retenue est `calibration_blockers → []`, jamais
le code de sortie.

⚠️ Sous le devShell (`EURIO_DB_READONLY=1`) le build **refuse de démarrer** : le
traçage en base est une écriture.

## Comment on vérifie qu'il marche

- **Le critère** : held-out à N=10 en `vitl14`, contre la référence **84,8 %**
  (banque servie actuelle) ou **85,7 %** (banque d'avant le plancher, selon
  l'option retenue au préalable). Avec McNemar.
- **Le contrôle négatif** : à N=0, les deux banques doivent être identiques.
- **La mutation** : neutraliser l'amorce médoïde (revenir au point lointain) doit
  faire rougir le test de `farthest_point_select` ; si le test reste vert, il
  teste la signature, pas le comportement.
- **Le témoin de volume** : le build doit annoncer **12 454** assets vus, pas
  6 205. Une base périmée répond normalement.

## Ce que cet outil n'est pas

- **Ce n'est pas un changement d'encodeur.** DINOv3 est réfuté
  (`vit_small_p16.dinov3` 78,7 % contre `dinov2_vits14` 85,9 % à taille égale,
  McNemar `p ≤ 3,6e-15`). `dinov2_vitl14` reste l'encodeur de la review.
- **Ce n'est pas le retour du plancher.** Le plancher supprimait des données
  pour soigner ce symptôme ; l'amorce le corrige à la source. Un exemplaire
  unique **aide** sa classe — mesuré, 67,6 → 69,1 % (p=0,048).
- **Ce n'est pas une amélioration du scan.** Le corpus de scan a **0 capture
  versionnée** ; rien ici ne dit ce que la banque vaudra sur une frame caméra.
