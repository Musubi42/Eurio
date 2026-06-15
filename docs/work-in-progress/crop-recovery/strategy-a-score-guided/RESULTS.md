# RESULTS — Stratégie A : crop guidé par le score

> Session 2026-06-15. Probe **gelée** (oracle), τ=0,55, jeux D1/D2/D3 figés
> (`../BENCHMARK.md`). Code : `ml/bench/crop_recovery/strategy_a.py`. JSON de banc :
> `ml/state/crop_recovery/run_A_score_search.json`. **Non committé** (attente accord PO).
>
> **Comment reproduire** (depuis `ml/`, venv) :
> ```bash
> .venv/bin/python -m scripts.run_crop_recovery_bench \
>   --import bench.crop_recovery.strategy_a --strategy "A:score_search" --datasets D1,D2,D3a,D3b
> ```

## 1. Scorecard final

| Métrique | Baseline | **A** | Cible | Verdict |
|---|---|---|---|---|
| **D2** récup EMU/globe | 0 % | **86 %** (263/305) | ≥70 % | ✅ **largement atteint** |
| D3a rétention `success` | 100 % | **100 %** (337/337) | ≥98 % | ✅ |
| D3b faux-accept fragments | 0 % | **3,8 %** (3/80) | ≤2 % | ❌ marginal (cf. §4) |
| D1 IoU médian (gold géom.) | 0,29 | **0,765** | ≥0,80 | ❌ plafond structurel (cf. §3) |

- **Coût K** : ~24 scores DINO / cas (médiane ; recherche coarse-to-fine interne, étages
  ①+③). Acceptable en **enrichment serveur**, **inapplicable au scan on-device** (assumé —
  c'est le rôle de B).
- **Primaire atteint** : A récupère **86 %** des zero_crops EMU/globe (score médian du
  meilleur crop **0,865** vs baseline **0,07**). Le diagnostic « le score monte avec la
  taille jusqu'à la pièce entière » est **confirmé à l'échelle** : la recherche multi-échelle
  retrouve la pièce entière dans 86 % des cas.

## 2. Ce que fait la stratégie (mécanique retenue)

`recrop()` propose un nuage de candidats ; le harness les score (probe gelée) et garde
l'argmax. Deux étages :

1. **① ladder de rayon au centre du hint** : `r_final × {1,0…4,0}` **∪** fractions absolues
   du petit côté `{0,12…0,42}·short`. Les **fractions absolues sont la clé du saut 43 %→86 %**
   : quand la détection rend un `r_final` minuscule (médiane des cas durs ≈ **5 % du short**,
   détection parasite sur un sous-motif), l'ancrage `×mult` ne peut **pas** atteindre la pièce
   entière ; les rayons absolus la couvrent indépendamment de `r_final`.
2. **③ rayon fin** autour du meilleur rayon (`×{0,85…1,15}`) → resserre l'IoU. C'est la source
   gagnante dans 180/263 récupérations D2.
- Garde anti-sur-crop : **borne dure `r ≤ 0,48·short`** (empêche le crop d'avaler tout le cadre).
- **Étage ② (recentrage par jitter de centre) : testé puis ABANDONNÉ.** Mesuré : **+0,06 IoU
  D1 mais D3b 2 %→5 %** — le jitter aveugle fabrique des faux-positifs probe sur les
  fragments. Le recentrage fiable est géométrique = rôle de B.

## 3. Pourquoi D1 IoU plafonne à 0,765 (preuve, pas opinion)

**Ce n'est pas un défaut de granularité — c'est la qualité du `hint` de détection.** Vérifié
sur les 458 cas D1 (run JSON, script `/tmp/diag_d1c.py` reproductible) :

- Le **rayon** choisi est bon : `r_choisi/r_gold` médian **1,05**, **67 %** dans ±15 %.
- Le **centre du hint lui-même est sur la mauvaise pièce dans 46 % des cas** (offset
  centre/`r_gold` ≥ 0,3). Ce sont des raws **multi-pièces** (avers + revers côte à côte) où la
  détection prod accroche une autre pièce que l'avers recroppé-main (le gold).
- **A n'aggrave jamais** : 0 cas où mon candidat dérive d'un hint pourtant correct.
- Conséquence : **33 % des cas D1 ont IoU ≈ 0** (mauvaise pièce). Les 67 % bien centrés ont
  déjà **IoU médian 0,809**. Ce sont les zéros qui tirent la médiane globale à 0,765.

La probe est un oracle « **pièce entière ?** », pas « **CETTE pièce ?** » : quand le hint est
sur le revers, A produit un crop de pièce entière parfaitement valide… mais qui ne matche pas
le cercle gold de l'avers. **Le score ne peut pas distinguer deux faces.** Atteindre 0,80
suppose de corriger le centre par la **géométrie** → c'est exactement ce que vise la
stratégie B (cf. `../BENCHMARK.md` §6bis : « B vise surtout l'IoU D1 »). A à 0,765 est déjà
**très au-dessus** du sweep naïf de référence (0,55).

## 4. Pourquoi D3b est à 3,8 % (et pourquoi je n'ai pas « triché » pour le faire passer)

Les 3 faux-accepts sont des crops dont la **probe elle-même** donne un score **juste au-dessus
de τ** (0,575 / 0,593 / 0,612) sur des fragments synthétiques (motif central 0,5×, sans pièce
entière récupérable). Ils proviennent de **3 sources différentes** (`A:r1.3`, `A:fine`,
`A:abs0.42`) — donc pas un étage à blâmer, mais le **prix de la recherche multi-échelle** : plus
on tente de crops, plus on a de chances de tomber sur un faux-positif probe près du seuil.

- C'est **structurel à A** : la même agressivité qui donne 86 % de récup sur D2 expose 2-3
  faux-positifs probe sur 80 fragments. Le sweep de référence (moins agressif) est à 1 %, mais
  plafonne à 43 % de récup.
- **n=80 → 1 fragment = 1,25 %.** Élaguer un candidat précis pour repasser sous 2 % serait du
  **sur-apprentissage sur l'échantillon D3b** (ce que le BENCHMARK met en garde). Vérifié :
  **0** récupération D2 ne dépend uniquement des rayons agressifs (`abs≥0,36` / `mult≥3,5`) —
  on *pourrait* les retirer sans perdre de D2, mais ça ne supprimerait pas les FP des petits
  rayons / du fine. Le vrai correctif est un **rejet de fragment géométrique** (B), pas une
  recherche moins large.

**D3a = 100 % par construction** : le harness inclut toujours le candidat baseline et garde
l'argmax ; comme baseline passe (~100 % sur D3a), l'argmax passe aussi. A ne peut pas casser
D3a.

## 5. Angles morts / cas de désaccord

- **Multi-pièces (lots)** : pas de jeu « lot » dans D1/D2/D3 → la **garde voisin-aware**
  (`feedback_recrop_multicoin_guard`) n'est **pas mesurable** ici. La seule protection en banc
  est `r ≤ 0,48·short`. **À l'intégration prod (A5)**, brancher la garde voisin-aware via
  `detect_circles_multi` (le `hint` ne porte pas les voisins → re-détection nécessaire).
- **Slice « autres » de D2** : vide (n=0) — D2 est 100 % EMU/globe. La généralité hors
  EMU/globe **n'est pas testée**.
- **Désaccord attendu A↔B** : les **46 % de hints mauvaise-pièce** (D1). A garde un crop de
  pièce entière (l'autre face) ; B devrait recadrer sur l'avers gold par la géométrie. C'est
  là que le front `/crop-recovery` (tri par désaccord) sera le plus instructif.

## 6. Recommandation

A **remplit son mandat** : booster de **récupération** côté serveur (D2 86 % ≫ 70 %, D3a
intact). Ses deux manques (D1 IoU, D3b) sont **précisément les forces de B** (géométrie :
recentrage + rejet de fragment). → **Ne pas livrer A seul. Viser l'hybride** : B pour la
géométrie/IoU et le rejet de fragment, A en **booster de récupération**. Le banc loggue tous
les candidats de A → l'évaluateur hybride (`scripts.run_crop_recovery_bench --hybrid …`)
pourra trancher **sans re-run** dès que B aura produit son JSON.

**Prochaines étapes** : (1) attendre le run B ; (2) évaluer `hybrid argmax` et `B_prior_then_A`
sur l'union ; (3) si l'hybride domine D2 sans violer une garde, l'adopter ; (4) intégration
prod derrière flag (A5) avec garde multi-pièces.
