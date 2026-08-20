# Bench encodeurs zero-shot (banque 2eur_all, GOLD FIGÉ de review)

<!-- ===== EN-TÊTE HUMAIN — ajouté à la main le 2026-08-20. -->
<!-- Le corps sous « CORPS GÉNÉRÉ » vient de ml/scripts/bench_encoder_dino.py. -->
<!-- 🔴 PIÈGE : `--out <ce fichier>` fait un Path.write_text() du rapport ENTIER -->
<!-- (bench_encoder_dino.py:868) — il n'append pas, il REMPLACE. Un rerun -->
<!-- pointé ici DÉTRUIT cet en-tête. Écrire ailleurs (`--out /tmp/bench.md`) -->
<!-- puis recoller le corps sous le séparateur. ===== -->

> **Ce qui a été mesuré, en une phrase** : quatre backbones **gelés** (aucun
> entraînement) ont ré-encodé la banque d'ancres `2eur_all` *et* les crops d'un
> gold figé, et on a compté qui retrouve la bonne classe. Run
> `20260820T011143Z`, gold `0ecbb1d70e3c`, **1958 crops, 0 crop non encodé**.

> 🔴 **La banque a changé depuis ce run — tous les chiffres ci-dessous notent
> une banque qui n'existe plus.** Le run a tourné contre les **1533 ancres** du
> build `23c637d93b43`. La banque servie aujourd'hui est le build
> `365dcab2a253` du `2026-08-20T14:27:56+00:00` : **1495 ancres, 671 classes,
> 124 classes à exemplaires**, bâtie **avec** le plancher `min_exemplars=2`,
> 68 classes ramenées au canonique seul. ⚠️ **Le plancher a depuis été retiré du
> code** (défaut revenu à 1, inactif) : la banque servie le porte, un rebuild ne
> le porterait plus.
>
> Ce que le changement fait, et ne fait pas :
>
> - **Le classement des encodeurs tient.** DINOv3 reste réfuté ; rien dans le
>   plancher ne joue en faveur d'une famille de backbone plutôt qu'une autre.
> - **Les niveaux absolus ne tiennent plus.** Le re-bench held-out après
>   plancher rend `dinov2_vits14` **74,1 %** (contre 75,5) et `dinov2_vitl14`
>   **84,8 %** (contre 85,7) à N=10 — **le plancher a dégradé**, cf.
>   [`COURBE-REFERENCES.md`](COURBE-REFERENCES.md) §Mise à jour.
> - **Les 4 payloads de ce run attendent toujours** dans
>   `ml/state/encoder_bench_pending/` : la table `encoder_bench_runs` n'existe
>   pas au canonique (migration `0009` non appliquée). Les pousser un jour
>   **sans dire qu'ils notent la banque d'avant le plancher** ferait croire à un
>   état courant.

## La conclusion

**DINOv3 est réfuté sur notre tâche.** À taille comparable (21,6 M contre
22,1 M), `vit_small_patch16_dinov3` fait **78,7 %** top-1 contre **85,9 %** pour
`dinov2_vits14` : **−7,2 points**. Le ConvNeXt-Tiny DINOv3 (27,8 M) plafonne à
81,5 %, toujours sous le petit DINOv2. Les trois écarts contre le champion
`dinov2_vitl14` sont significatifs en McNemar apparié (p ≤ 3,6e-15).

Les benchmarks publics disaient l'inverse — +24 % relatif de mAP en recherche
d'instance, +10,8 pts sur Met (arXiv 2508.10104), sur une famille de tâches qui
**ressemble** à la nôtre (peu de références par classe, discrimination par
détail fin). **Ils n'ont pas transféré.** C'est le résultat de méthode le plus
réutilisable de ce chantier : un benchmark public n'est pas une preuve, même
quand sa tâche ressemble à la nôtre — et surtout quand elle lui ressemble.
[`PROTOCOLE-BENCH.md`](../banque-dino/PROTOCOLE-BENCH.md) §« Sur DINOv3 »
l'avait posé avant le run ; le doute avait été écrit comme une hypothèse
falsifiable (**H12** de [`VISION.md`](../../model-efficiency/VISION.md)) et la
mesure qui la tue avait été semée avec elle.

Conséquence opérationnelle : **`dinov2_vitl14` reste l'encodeur de la review**
(91,6 %), et le candidat léger à instruire est **`dinov2_vits14`** (85,9 % pour
16 ms/img et 22,1 M params), pas un DINOv3.

## Les trois réserves — à lire avant de citer un chiffre d'ici

**(a) C'est la tâche REVIEW, pas la tâche SCAN.** Le gold est fait de photos de
vendeurs eBay. ⚠️ **La distinction n'est pas « nettes contre floues »** — beaucoup
de photos eBay sont floues, de loin, avec du reflet. Elle est plus étroite : une
photo eBay est **cadrée par un vendeur qui veut montrer la pièce** (statique,
pièce entière, choisie parmi plusieurs) ; une frame de scan n'est choisie par
personne. Côté corpus, l'état juste est **0 capture versionnée pour 2 264 images
device non protégées**
([`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md)) —
c'est le prérequis P5. Ce tableau décide **quel encodeur sert la review**, il ne
décide **pas** ce qui part dans l'APK (D4 de [`DECISION.md`](DECISION.md), H10 de
[`VISION.md`](../../model-efficiency/VISION.md)).

**(b) Les bloqueurs imprimés dans le corps généré ont été lus sur une réplique
périmée.** Le run a tourné à 01:11Z contre une réplique du 19 août 16:31,
antérieure au rebuild de la banque (`2026-08-19T14:36:14+00:00`) et au backfill
P3. Sur la réplique **fraîche** (pull du 2026-08-20 03:22), l'encodeur de
production ne porte **plus aucun bloqueur** :

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3; from store.encoder_bench import calibration_blockers
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
print(calibration_blockers(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14'))"
# → []
```

Les trois candidats gardent leurs deux bloqueurs P1/P3, mais **par
construction** : aucune banque n'a jamais été bâtie sous eux, donc leur
fraîcheur est non mesurable. Ce n'est pas une anomalie du run.
⚠️ Et la requête de complétude P3 écrite en dur dans
[`PREREQUIS.md`](PREREQUIS.md) / [`GESTE-P3.md`](GESTE-P3.md) est **fausse** :
elle compare `computed_at < built_at` en **chaînes**, deux formats différents,
et rend `12454` là où `datetime()` des deux côtés rend `0`.

**(c) Le classement vaut pour un backbone gelé sur CETTE banque.** Le banc
ré-encode les images d'ancre avec chaque modèle, mais **le choix** de ces images
— le farthest-point sampling — a été fait dans l'espace de `dinov2-vitl14`. Un
DINOv3 avec sa propre banque, rebâtie sous son encodeur, **n'a pas été mesuré**
(hypothèse **H13**). Le biais joue contre les candidats ; il n'est pas quantifié.
Ce rebuild reste d'ailleurs **interdit** tant que le défaut **Q6** est ouvert
(aucun lecteur de `dino_class_references` n'est scopé par encodeur —
[`FINDINGS.md`](FINDINGS.md) §8.10).

<!-- ===================== CORPS GÉNÉRÉ — NE PAS ÉDITER ===================== -->

```
==============================================================================
⚠ CALIBRATION PROVISOIRE — NE PAS RECOPIER CES SEUILS DANS dino_thresholds

  dinov2_vits14 :
    - P3: aucun build trace dans dino_anchor_builds pour 2eur_all/dinov2-vits14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque (scripts.build_dino_anchors --kind 2eur_all) puis relancer scripts.backfill_dino_predictions --force
    - P1: la banque servie pour 2eur_all/dinov2-vits14 ne couvre que 0 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push
  dinov2_vitl14 :
    - P3: 12454 predictions 2eur_all/dinov2-vitl14 anterieures au build courant (2026-08-19T00:28:21+00:00) — relancer scripts.backfill_dino_predictions --force
    - P1: la banque servie pour 2eur_all/dinov2-vitl14 ne couvre que 125 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push
  timm:vit_small_patch16_dinov3.lvd1689m :
    - P3: aucun build trace dans dino_anchor_builds pour 2eur_all/timm:vit_small_patch16_dinov3.lvd1689m — la fraicheur des predictions ne peut pas etre prouvee — batir la banque (scripts.build_dino_anchors --kind 2eur_all) puis relancer scripts.backfill_dino_predictions --force
    - P1: la banque servie pour 2eur_all/timm:vit_small_patch16_dinov3.lvd1689m ne couvre que 0 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push
  timm:convnext_tiny.dinov3_lvd1689m :
    - P3: aucun build trace dans dino_anchor_builds pour 2eur_all/timm:convnext_tiny.dinov3_lvd1689m — la fraicheur des predictions ne peut pas etre prouvee — batir la banque (scripts.build_dino_anchors --kind 2eur_all) puis relancer scripts.backfill_dino_predictions --force
    - P1: la banque servie pour 2eur_all/timm:convnext_tiny.dinov3_lvd1689m ne couvre que 0 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push

  Ce qui reste VALIDE malgré ces bloqueurs : le classement des
  encodeurs (recall@1/@5, bande pays). Le banc ré-encode la banque et
  les crops à chaque run, il ne lit aucune prédiction stockée — P3 ne
  peut donc pas le fausser.
  Ce qui est BLOQUÉ : la proposition de seuil (spread_at_p97), qui se
  lit sur des prédictions et une banque dont la fraîcheur n'est pas
  prouvée. --allow-provisional rend le chiffre, marqué provisoire.
==============================================================================
```

- gold `0ecbb1d70e3c` · 1958 crops figés · 1958 soumis (gold entier)
- banque `2eur_all` servie : 1533 ancres, build `42d17f9e708345f4826869f044b95a48`
- Recall mesuré sur crops in-scope (classe de banque présente) ; bande pays = ancres du pays de la VÉRITÉ tranchée (`truth_country`).
- Chaque modèle utilise SA transform recommandée (résolution/normalisation) — le zero-shot est un proxy du potentiel post-fine-tune ArcFace, pas une mesure absolue.

| Modèle | M params | px | dim | in-scope | non encodés | global@1 | global@5 | pays@1 | pays@5 | ms/img | provisoire |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dinov2_vitl14 | 304.4 | 224 | 1024 | 1958 | 0 | 91.6% | 97.9% | 97.4% | 99.7% | 122 | oui |
| dinov2_vits14 | 22.1 | 224 | 384 | 1958 | 0 | 85.9% | 97.2% | 96.0% | 99.7% | 16 | oui |
| timm:convnext_tiny.dinov3_lvd1689m | 27.8 | 224 | 768 | 1958 | 0 | 81.5% | 91.8% | 90.4% | 98.9% | 16 | oui |
| timm:vit_small_patch16_dinov3.lvd1689m | 21.6 | 256 | 384 | 1958 | 0 | 78.7% | 91.7% | 89.9% | 99.1% | 22 | oui |

## Seuil d'auto-acceptation (spread)

- `dinov2_vits14` : **aucun seuil rendu** — Seuil non promouvable : P3: aucun build trace dans dino_anchor_builds pour 2eur_all/dinov2-vits14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque (scripts.build_dino_anchors --kind 2eur_all) puis relancer scripts.backfill_dino_predictions --force | P1: la banque servie pour 2eur_all/dinov2-vits14 ne couvre que 0 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push. Relancer avec allow_provisional=True (CLI : --allow-provisional) pour obtenir un chiffre explicitement marque provisoire.
- `dinov2_vitl14` : **aucun seuil rendu** — Seuil non promouvable : P3: 12454 predictions 2eur_all/dinov2-vitl14 anterieures au build courant (2026-08-19T00:28:21+00:00) — relancer scripts.backfill_dino_predictions --force | P1: la banque servie pour 2eur_all/dinov2-vitl14 ne couvre que 125 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push. Relancer avec allow_provisional=True (CLI : --allow-provisional) pour obtenir un chiffre explicitement marque provisoire.
- `timm:vit_small_patch16_dinov3.lvd1689m` : **aucun seuil rendu** — Seuil non promouvable : P3: aucun build trace dans dino_anchor_builds pour 2eur_all/timm:vit_small_patch16_dinov3.lvd1689m — la fraicheur des predictions ne peut pas etre prouvee — batir la banque (scripts.build_dino_anchors --kind 2eur_all) puis relancer scripts.backfill_dino_predictions --force | P1: la banque servie pour 2eur_all/timm:vit_small_patch16_dinov3.lvd1689m ne couvre que 0 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push. Relancer avec allow_provisional=True (CLI : --allow-provisional) pour obtenir un chiffre explicitement marque provisoire.
- `timm:convnext_tiny.dinov3_lvd1689m` : **aucun seuil rendu** — Seuil non promouvable : P3: aucun build trace dans dino_anchor_builds pour 2eur_all/timm:convnext_tiny.dinov3_lvd1689m — la fraicheur des predictions ne peut pas etre prouvee — batir la banque (scripts.build_dino_anchors --kind 2eur_all) puis relancer scripts.backfill_dino_predictions --force | P1: la banque servie pour 2eur_all/timm:convnext_tiny.dinov3_lvd1689m ne couvre que 0 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push. Relancer avec allow_provisional=True (CLI : --allow-provisional) pour obtenir un chiffre explicitement marque provisoire.

## Apparié McNemar (référence : `dinov2_vitl14`)

- `dinov2_vits14` : b=163 c=50 · p = 3.598e-15
- `timm:vit_small_patch16_dinov3.lvd1689m` : b=286 c=32 · p = 3.812e-52
- `timm:convnext_tiny.dinov3_lvd1689m` : b=237 c=39 · p = 9.027e-36

## Traçabilité

- `20260820T011143Z-0ecbb1d70e3c-dinov2-vits14` — provisional=1
- `20260820T011143Z-0ecbb1d70e3c-dinov2-vitl14` — provisional=1
- `20260820T011143Z-0ecbb1d70e3c-timm-vit_small_patch16_dinov3.lvd1689m` — provisional=1
- `20260820T011143Z-0ecbb1d70e3c-timm-convnext_tiny.dinov3_lvd1689m` — provisional=1

```
==============================================================================
⚠ CALIBRATION PROVISOIRE — NE PAS RECOPIER CES SEUILS DANS dino_thresholds

  dinov2_vits14 :
    - P3: aucun build trace dans dino_anchor_builds pour 2eur_all/dinov2-vits14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque (scripts.build_dino_anchors --kind 2eur_all) puis relancer scripts.backfill_dino_predictions --force
    - P1: la banque servie pour 2eur_all/dinov2-vits14 ne couvre que 0 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push
  dinov2_vitl14 :
    - P3: 12454 predictions 2eur_all/dinov2-vitl14 anterieures au build courant (2026-08-19T00:28:21+00:00) — relancer scripts.backfill_dino_predictions --force
    - P1: la banque servie pour 2eur_all/dinov2-vitl14 ne couvre que 125 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push
  timm:vit_small_patch16_dinov3.lvd1689m :
    - P3: aucun build trace dans dino_anchor_builds pour 2eur_all/timm:vit_small_patch16_dinov3.lvd1689m — la fraicheur des predictions ne peut pas etre prouvee — batir la banque (scripts.build_dino_anchors --kind 2eur_all) puis relancer scripts.backfill_dino_predictions --force
    - P1: la banque servie pour 2eur_all/timm:vit_small_patch16_dinov3.lvd1689m ne couvre que 0 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push
  timm:convnext_tiny.dinov3_lvd1689m :
    - P3: aucun build trace dans dino_anchor_builds pour 2eur_all/timm:convnext_tiny.dinov3_lvd1689m — la fraicheur des predictions ne peut pas etre prouvee — batir la banque (scripts.build_dino_anchors --kind 2eur_all) puis relancer scripts.backfill_dino_predictions --force
    - P1: la banque servie pour 2eur_all/timm:convnext_tiny.dinov3_lvd1689m ne couvre que 0 classes a exemplaires (attendu >= 180) — relancer scripts.build_dino_anchors --kind 2eur_all --force --push

  Ce qui reste VALIDE malgré ces bloqueurs : le classement des
  encodeurs (recall@1/@5, bande pays). Le banc ré-encode la banque et
  les crops à chaque run, il ne lit aucune prédiction stockée — P3 ne
  peut donc pas le fausser.
  Ce qui est BLOQUÉ : la proposition de seuil (spread_at_p97), qui se
  lit sur des prédictions et une banque dont la fraîcheur n'est pas
  prouvée. --allow-provisional rend le chiffre, marqué provisoire.
==============================================================================
```

