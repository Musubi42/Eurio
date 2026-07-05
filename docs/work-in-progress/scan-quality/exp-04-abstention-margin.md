# exp-04-abstention-margin — calibration du signal d'abstention

> Axe README §4 « Abstention / seuils » : le matcher actuel (Android +
> replay) répond TOUJOURS (top-k pur). Un faux positif confiant coûte la
> confiance — quel signal permet de dire « je ne sais pas » ? Sweep offline
> sur les `predictions.jsonl` d'exp-01 (chemin fast, corpus `9b1bc705525d`,
> n=73). **État : terminée (2026-07-06), verdict EXPLORATOIRE** (seuils
> réglés sur l'échantillon même — à valider hors-échantillon).

## 1. Hypothèse

La **marge top1−top2** discrimine mieux les erreurs que le score absolu top1.

## 2. Résultat — courbes coverage / précision (R@1 eq parmi les répondues)

**train_mean** :

| Signal | Seuil | Coverage | Précision |
|---|---|---|---|
| top1_min | 0.50 | 0.92 | 0.806 |
| top1_min | 0.60 | 0.79 | 0.862 |
| **margin_min** | **0.05** | **0.81** | **0.898** |
| **margin_min** | **0.10** | **0.60** | **0.955** |
| **margin_min** | **0.15** | **0.49** | **1.000** |

**val_mean** (dominée partout) : margin 0.10 → 0.51 / 0.838 ; margin 0.15 →
0.36 / 0.923.

Lectures :
- **La marge écrase le score absolu** : à couverture ~0.80, margin donne
  0.898 de précision là où top1_min plafonne à 0.862 avec moins de couverture.
  Le score absolu ne filtre quasi rien avant 0.45 (coverage 1.0).
- **train_mean domine val_mean sur toute la courbe** — cohérent avec exp-01,
  et un argument de plus pour train_mean (meilleure séparabilité, pas juste
  meilleur top-1).
- À margin ≥ 0.15 : zéro faux positif sur les 73 frames, mais on ne répond
  plus qu'une fois sur deux — le point utile pour le produit est probablement
  margin ~0.05–0.10 (répondre 60–80 % du temps à 90–95 % de précision),
  couplé au buffer de consensus (5/3 sticky) qui redonne des chances.

## 3. Décision

| Étage | Verdict |
|---|---|
| **S0** | 🟡 exploratoire — signal margin >> top1 net, mais seuils réglés in-sample (n=73) : **ne pas câbler de valeur** |

## 4. Verdict écrit

La marge top1−top2 est le bon signal d'abstention pour ce matcher (précision
0.955 à 60 % de couverture sur train_mean, contre 0.806–0.862 pour le score
absolu à couverture comparable) ; le score absolu seul est presque inutile
sous 0.45. Aucun seuil n'est promu : n=73 et calibration in-sample. **Action** :
re-tracer ces courbes sur le corpus élargi (split calibration/validation), puis
si ça tient, brancher `thresholds.json` du candidat (le replay le supporte
déjà) et spécifier le comportement produit « pas sûr → ne propose pas ».
