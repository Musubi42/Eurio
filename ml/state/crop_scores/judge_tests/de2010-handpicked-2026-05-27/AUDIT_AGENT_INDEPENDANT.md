# Audit indépendant — cohorte de2010-handpicked, tests T01–T09

> **Origine** : agent `general-purpose` lancé avec system prompt = mission
> Eurio + accès aux 9 JSONs des tests + cohorte. Aucun contexte de la
> session précédente. Demandé en tant que « deuxième paire d'yeux
> impartiale » pour auditer les conclusions de l'instance principale.
>
> **Date** : 2026-05-27
> **Modèle** : Claude Sonnet 4.6 (via agent local)
> **Verdict synthétique** : l'expérience ne discrimine pas significativement
> les marges entre 0.02 et 0.10 — le signal est sous le bruit floor du juge.

---

## 1. Synthèse chiffrée (n=30 par test)

| Test | Params | D | C | B | A | R | margin ok | undercrop strong |
|---|---|---|---|---|---|---|---|---|
| T01 baseline | m=0.02 hard 224 | 6 | 16 | 3 | 5 | 0 | 7 | 4 |
| T02 | m=0.10 hard 224 | 5 | 16 | 4 | 5 | 0 | 11 | 4 |
| T03 | m=0.15 hard 224 | 5 | 13 | 4 | 4 | 4 | 4 | 4 |
| T04 | m=0.05 hard 224 | 6 | 15 | 4 | 4 | 1 | 8 | 4 |
| T05 | m=0.10 feather 224 | 5 | 17 | 3 | 4 | 1 | 9 | 4 |
| T06 baseline replay | m=0.02 hard 224 | 6 | 16 | 4 | 4 | 0 | 6 | 4 |
| T07 edge=none | m=0.10 none 224 | 11 | 10 | 4 | 4 | 1 | 8 | 4 |
| T08 m010 replay | m=0.10 hard 224 | 6 | 15 | 5 | 4 | 0 | 8 | 5 |
| T09 output 192 | m=0.10 hard 192 | 7 | 11 | 3 | 5 | 4 | 3 | 4 |

## 2. Bruit du juge (replays stricts)

- **T06 vs T01** : 3/30 assets changent de catégorie (10 %), 9/30 changent
  `margin_assessment` (30 %), 13/30 ont au moins un axe qui bouge (43 %).
- **T08 vs T02** : 3/30 cat (10 %), 9/30 margin (30 %), 16/30 au moins un
  axe (53 %).

**Noise floor catégorie ≈ 3 verdicts (10 %).** Noise floor margin_assessment
≈ 9 verdicts (30 %, axe quasi-inutilisable). L'axe `face` bouge aussi 5–7
fois en replay : non fiable.

## 3. Effet margin : signal ou bruit ?

- T02 vs T01 (apparent) : 2 changements cat / 12 margin.
- T08 vs T06 (contrôlé) : 4 changements cat / 12 margin.

**Conclusion ferme : le passage 0.02 → 0.10 ne produit aucune amélioration
catégorielle distinguable du bruit.** Le delta cat (2–4) est *inférieur ou
égal* au noise floor (3). Sur `margin_assessment` le signal apparent
(too_tight 20→15) disparaît dans la dispersion des replays (T06=19, T08=17).
T04 (0.05) bouge moins (11 assets vs 16 pour T02 vs T01), ce qui est
cohérent avec un changement de paramètre plus petit, mais n'apporte rien
non plus. **L'expérience ne discrimine pas les marges entre 0.02 et 0.10.**

## 4. Edge=none (T07)

Sur les 7 changements de catégorie T07 vs T02, **la quasi-totalité des
passages C→D correspond à un juge qui ne voit plus le contexte multi-pièces**
(raw mal interprété comme single-coin), pas à une amélioration objective du
crop. Exemples flagrants : `7096a30d` "Cinq pièces proof" → "Pièce unique
Bremen" ; `3624dc78` part en R alors que le raw est inchangé.
**Hypothèse (a) confirmée : le mask hard cachait du contexte au juge, pas à
ArcFace.** Le mask retire du fond hors-pièce qui ne porte aucun signal
d'identité. **T07 est un artefact de méthodologie, pas une découverte
produit.** Ne pas conclure que edge=none améliore le training.

## 5. Output 192 (T09)

Régression nette : R passe 0→4, ok passe 11→3, too_tight 15→25. Les reasoning
des cat-changes parlent quasi tous de "crop sombre", "détails à peine
discernables", "fortement occultée". **Hypothèse : le downscale 224→192
dégrade la lisibilité au point que le juge bascule vers reverse-par-défaut
sur les pièces ambiguës et perd la finesse pour distinguer C/D.** C'est plus
un effet sur le juge que sur le modèle (ArcFace digère 112 sans souci). À ne
pas sur-interpréter, mais 192 est clairement sous-optimal pour cette méthodo.

## 6. Recommandation produit

1. **Ne pas adopter margin 0.10 sur la base de cette expé.** Le signal est
   sous le noise floor. Garder 0.02 par défaut OU faire le cutover sur base
   théorique ArcFace (~0.10–0.20 = standard), pas sur ces données.
2. **Le juge Claude vision est trop bruité pour des deltas fins.** 30 assets
   × bruit 10 % cat / 30 % margin ⇒ il faut soit (a) augmenter n à 100–200,
   (b) moyenner k=3 replays par condition et travailler sur le verdict
   majoritaire, (c) basculer sur des métriques objectives (accuracy ArcFace
   sur un val-set étiqueté).
3. **Edge=none = piste fausse**, à abandonner sur base de ces données. Si on
   veut la tester, il faut une métrique downstream (loss ArcFace), pas le
   juge.
4. **Risque méthodologique sous-estimé** : le juge a `face` qui flip 5–7
   fois en replay sur 30 — un axe binaire censé être objectif. Cela invalide
   aussi l'usage du juge pour pré-trier obverse/reverse à grande échelle
   sans agrégation multi-replay.
5. **Avant tout nouveau test format**, fixer le protocole : k≥3 replays par
   condition, n≥100 assets, et un **val-set ArcFace** comme ground truth
   secondaire. Sans cela, on continuera à mesurer le bruit du juge.
