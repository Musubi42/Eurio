# Pourquoi sept chantiers crop ont échoué

> Écrit le 2026-08-27, à partir d'une archéologie de `docs/archive/`,
> `docs/research/`, `docs/operations/` et du code. Chaque chiffre porte sa
> source. **Ce document existe pour qu'on ne repaie pas une huitième fois.**

## Le tableau

| # | Chantier | Date | Ce qu'il a livré |
|---|---|---|---|
| 1 | `archive/operations/crop-bimetal-undercrop.md` | 2026-05-24 | observation seule, jamais corrigée |
| 2 | `archive/crop-forensics/` | 2026-05-26/27 | une chose (tri par score) ; **toutes les théories réfutées** |
| 3 | `archive/cohort-pipeline/` (census + probe fragment) | 2026-06-04/05 | livré derrière flag ; **SAM mesuré ici** |
| 4 | `archive/crop-quality-overhaul/` | 2026-06-02/03 | **le seul arrivé en prod** (`detect_bbox_refine`) |
| 5 | `operations/crop-bimetal-harden-session.md` | 2026-06-01 | ablation de format livrée ; harden device jamais fait |
| 6 | `archive/crop-rim-overfit/` | 2026-06-14/15 | **doublement invalidé** |
| 7 | `archive/crop-recovery/` | 2026-06-15 | `RESULTS` dit « ne pas livrer A seul » — **A a été livré seul le jour même** |

## Le mode d'échec, constant

**Chaque chantier a atteint sa cible sur sa propre métrique.**

- `crop-quality-overhaul` : undercrop du parc **18,4 % → 2,6 %**, « ok 97,4 % ».
  Son oracle est `image_assets.quality_score`.
- `crop-recovery` : D2 récupération **86 %** contre un critère pré-enregistré à
  70 %, **validé PO avant de coder**. Son oracle est la probe fragment gelée.

Et pourtant, mesuré sur le canonique le 2026-08-27 :

| méthode | tranchés par un humain | rejetés | % |
|---|---:|---:|---:|
| `yolo+hough+rimrefine` | 1 002 | 705 | **70,4 %** |
| `yolo+hough+polish+rimrefine` | 403 | 285 | **70,7 %** |
| `score_recover` *(le livrable de `crop-recovery`)* | 451 | 420 | **93,1 %** |

## Les trois oracles, et pourquoi chacun était optimisable dans la mauvaise direction

### 1. `quality_score` — inerte

```sql
SELECT COALESCE(quality_reason,'(accepté)') qr, COUNT(*) n, ROUND(AVG(quality_score),4) qs
FROM image_assets WHERE resolution_status IN ('manual','rejected') GROUP BY 1;
```

| motif | n | `quality_score` moyen |
|---|---:|---:|
| accepté | 3 493 | **0,9200** |
| `rejected_in_review` *(le seul rejet qui parle du crop)* | 1 461 | **0,9208** |
| `not_2eur` | 2 042 | 0,9547 |
| `face_reverse` | 2 636 | 0,9315 |

**Huit dix-millièmes d'écart** face au seul motif qui parle de cadrage. Un score
de netteté/contraste **monte** quand on rogne un fond bruité — il récompense
l'amputation. Sa docstring l'admet : « aveugle aux vraies pannes ».

### 2. La probe fragment — répond à la mauvaise question

Écrit en juin, dans `crop-recovery/strategy-a/RESULTS.md:60-62` :

> « La probe est un oracle **"pièce entière ?"**, pas **"CETTE pièce ?"** […] Le
> score ne peut pas distinguer deux faces. »

Et, `:105` : **« Ne pas livrer A seul. Viser l'hybride. »** A a été livré seul le
même jour (commit `c831bf27`), sans B, sans l'hybride. Aucune trace de décision
— **parce qu'il n'existait aucune ADR sur le crop**.

### 3. La similarité DINO — l'optimum EST l'amputation

Testé le 2026-08-27 : on rejoue le balayage de `score_recover` en le scorant par
`top1_sim` aux ancres de la classe cible. Sur 60 crops, +0,041 de similarité en
moyenne, 23,3 % franchissent le seuil, **0 dégradé selon la métrique**.

**La planche visuelle dit autre chose.** Le balayage gagne de la similarité en
rognant la légende du bord : « LUXEMBOURG » → « LUXEMBO… », « SUVALKIJA »
disparaît, « BUNDESREPUBLIK DE… » coupé. Et il ne fait pas que zoomer — il
dézoome aussi (`07a52426`, +0,094), donc son mécanisme n'est même pas
caractérisé.

La raison est structurelle : **une similarité d'embedding décroît quand on
ajoute du fond, et reste quasi plate quand on retire de la pièce** tant que le
motif central survit. Ce n'est pas un bug, c'est la forme de la fonction.

## Le critère qui a validé `crop-recovery` était mathématiquement aveugle

Pour deux disques concentriques de rayons `R` et `kR` : `IoU = k²`.

| rognage du rayon | IoU de masque | Dice | Boundary IoU (d = 8 % R) |
|---:|---:|---:|---:|
| 3 % | 0,941 | 0,970 | 0,464 |
| **6 %** | **0,884** | 0,938 | **0,148** |
| 10 % | 0,810 | 0,895 | 0,000 |

> **`IoU ≥ 0,80` tolère l'amputation de 10,6 % du rayon** (`1 − √0,80`).

Et l'IoU est **insensible au signe** : 0,80 s'atteint en rognant 10,6 % comme en
cadrant 11,8 % trop large. Or trop large donne un crop médiocre ; trop serré
donne un crop inutilisable **et une ancre empoisonnée**.

Le chantier n'a pas été bâclé. **Il a mesuré rigoureusement la mauvaise chose.**

## Les impasses déjà payées — ne pas reproposer sans raison neuve écrite

| # | Ne PAS reproposer | La mesure qui l'a tué |
|---|---|---|
| 1 | un post-filtre single-signal (`bg_uniformity`, `near_white_ratio`, `area_ratio`, `inner_feature_score`) | `bg_uniformity` = 0 sur **80,9 %** des crops (le masque noir le dégénère) ; `inner_feature_score ≥ 1.3` sur **219/221** ; `area_ratio` @0,10 flagge **74,1 %** |
| 2 | « le plus grand cercle à bord FORT » | **94 % → 88 %**, undercrop 1 → 11. Cause : **l'anneau interne bimétal a le bord le plus fort** |
| 3 | `EURIO_CROP_OUTER_SELECT` | **Δ = +1, aucun effet.** « le rebord externe n'est souvent même pas un candidat Hough » |
| 4 | un plancher ancré sur la bbox YOLO (`bbox_floor`) | marchait (49 % → 26 %) puis tué : « il s'ancre sur la bbox **elle-même sous-croppée** » |
| 5 | remplacer globalement le détecteur par fitEllipse plein cadre | **52,5 % contre 80,0 %.** « La localisation YOLO est précieuse et à garder » |
| 6 | baisser τ du gate anti-fragment | « à τ=0,30 on réadmet **autant de fragments que de coins** » |
| 7 | régler par la marge ou le format | 12 combos × 337 hold-out : `m02-hard` ≈ `m10-hard` (83,0 vs 82,2 % R@1, dans le bruit) |
| 8 | un jitter de centre aveugle | +0,06 IoU mais faux-accept **2 % → 5 %** |
| 9 | une recherche multi-échelle scorée par la probe dénomination | **93,1 % de rejet humain** sur 3 791 crops |
| 10 | `quality_score` comme oracle | accepté 0,9200 / rejeté-crop 0,9208 |
| 11 | la garde `fill` / `minEnclosingCircle` comme filtre de forme | rappel **76 % → 22 %** |
| 12 | Claude vision comme arbitre de format | bruit floor 10 %/30 %, gain **+4 dans le bruit ±9** |
| 13 | SAM2 / MobileSAM en mode « everything » | **25-40 s/image** ; FastSAM→DINO ne bat pas YOLO@0.10 |
| 14 | **un balayage scoré par un embedding** | ampute structurellement — mesuré et regardé le 2026-08-27 |
| 15 | **refaire un chantier crop jugé sur un oracle géométrique maison** | c'est le mode d'échec commun aux sept |

## Les portes restées ouvertes

1. **Réparer la stratégie B.** Otsu + `fitEllipse` était mesurée à **0 % de
   faux-accept fragment** — la seule des quatre. Elle a perdu sur D2, la
   métrique qu'on sait fausse, et sa cause d'échec est nommée : elle s'ancre sur
   `r_hint` alors que la pièce est à **8,1× ce rayon** sur les cas ratés. Le
   correctif est prescrit dans `strategy-b/RESULTS.md:160-163` — jamais fait.
2. **SAM amorcé par une BOÎTE, serveur seulement.** Ce qui a été tué en juin est
   le mode « everything ». Le mode prompt-par-boîte est deux à trois ordres de
   grandeur moins cher (MobileSAM ~12 ms GPU, Apache-2.0, 40 Mo). L'argument qui
   l'écartait — « non portable on-device, viole R0 parité » — **ne s'applique pas
   à l'enrichissement** (ADR-017).
3. **Modéliser l'ellipse plutôt que le cercle.** À 20° d'inclinaison un modèle
   circulaire se trompe de 6 % sur un axe, à 30° de 13 %. Mesuré sur le
   canonique : rejet humain 69,0 % (10-20°) → 76,8 % (20-30°) → **90,0 %
   (≥ 30°)**. ⚠️ Réel mais **secondaire** : le plancher est déjà à 69 %.

## Deux angles morts

- **Le D2 de `crop-recovery` est à 100 % EMU/globe** ; le slice « autres » est
  **vide (n = 0)**. La généralité n'a jamais été testée.
- **La qualité de détourage de FastSAM n'a jamais été mesurée ici.** Le bench de
  juin comptait des **pièces**, pas des cadrages — son « faux-lot 100 % » est un
  problème de dédup, pas de crop.
