# exp-NN-<slug> — <titre court>

> Copier ce fichier en `exp-NN-<slug>.md`. Une expérience = **une variable**,
> un corpus figé, une baseline battue (ou pas), un verdict écrit. Réfs :
> [`corpus-spec.md`](./corpus-spec.md) §7 (replay), §8 (scorecard),
> §8bis (McNemar), §9 (baseline).

## 1. Hypothèse

_Une phrase falsifiable. Ex. : « les centroïdes train_mean séparent mieux que
val_mean sur frames in-the-wild »._

## 2. Variable unique

| | Baseline | Candidat |
|---|---|---|
| **Variable** | _val_mean_ | _train_mean_ |
| **Tout le reste** | identique (modèle, seuils, corpus, chemin de replay) | idem |

- **Candidat** : `ml/state/scan_experiments/exp-NN-<slug>/<label>/`
  (`embeddings_v1.json` + modèle + `thresholds.json` optionnel).
- **Baseline** : `ml/state/scan_baselines/<name>/` (bundle gelé re-runnable, §9).

## 3. Corpus

| Champ | Valeur |
|---|---|
| `corpus_version` | _hash 12 hex (affiché par replay_corpus)_ |
| `n_frames` | _N_ |
| Filtre | `cohort_id=…`, `conditions=…`, `iteration=…` |
| Chemin replay | `fast` (modèle/centroïdes/seuils) ou `full` (détection/normalisation) |

## 4. Commandes (reproductibilité)

```bash
# (si nouvelles captures) import
go-task ml:scan-corpus:import ITERATION=<iid>
# replay apparié candidat vs baseline
go-task ml:scan-corpus:replay -- \
  --candidate ml/state/scan_experiments/exp-NN-<slug>/<label> \
  --baseline  ml/state/scan_baselines/<name> \
  --cohort-id <cid> [--conditions bright,dim,tilt,glare,inhand] [--path fast]
```

## 5. Scorecard (schéma §8 — coller le `scorecard.json`)

```jsonc
{ "candidate": "...", "baseline": "...", "corpus_version": "...", "n_frames": 0,
  "primary": { "r_at_1_eq": null, "r_at_5_eq": null, "r_at_1_strict": null },
  "by_condition": {}, "abstention": { "coverage": null, "precision_at_coverage": null },
  "mcnemar": { "n_discordant": 0, "p_value": null } }
```

## 6. McNemar (§8bis — obligatoire)

- Paires discordantes : `baseline_only=…`, `candidate_only=…`, `p=…`.
- Rappel : à n≈48, IC95 ≈ ±13 pts — on ne conclut « gain » que sur un **delta
  franc (≥ ~5 pts)** ou un **shift net par condition**. Sinon : « non
  concluant, agrandir le corpus ».

## 7. Décision go/no-go par étage

| Étage | Question | Verdict |
|---|---|---|
| **S0** replay offline | Le candidat bat-il la baseline en apparié ? | ⬜ go / ⬜ no-go / ⬜ non concluant |
| **S1** re-scan device (mêmes pièces) | Le gain offline se voit-il en vrai ? | ⬜ |
| **S2** latence/tier device | Coût acceptable (Pixel 9A + low-tier) ? | ⬜ |
| **S3** adoption bundle | Promu dans le bundle prod ? | ⬜ |

## 8. Verdict écrit

_Trois phrases max : ce qu'on a mesuré, ce qu'on en conclut, la prochaine
action. Pas de survente — un p > 0.05 n'est pas un gain._
