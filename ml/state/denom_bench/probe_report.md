# Probe denom « 2€ vs junk » — bench (généré par train_denom_probe.py)

_Généré : 2026-06-13T00:30:32+00:00 · gold : 624 pos hi / 241 neg hi (train+CV) · 60 lo (sanity) · 27 unk exclus_

## Protocole

- Features : embedding DINOv2 vitl14 gelé (1024-d, L2-norm) ± `bimetal_score` normalisé (z-score sur le train hi).
- Éval : StratifiedKFold k=5 (seed 0), scores **out-of-fold uniquement** ; `conf=lo` jamais vu à l'entraînement.
- Seuil opérationnel : max junk capturé sous **vrais 2€ perdus ≤ 2%**.

## Résultats (conf=hi, out-of-fold)

| scorer | AUC | seuil@loss≤2% | 2€ perdus | junk capturé | par kind |
|---|---|---|---|---|---|
| anchor max-sim (baseline) | 0.844 | 0.540 | 1.9% | 26.1% | {'banknote': '1/1', 'cent': '11/170', 'chart': '3/6', 'fragment': '9/14', 'medal': '7/14', 'notcoin': '27/27', 'one_euro': '0/4', 'stamp_postmark': '5/5'} |
| bimetal (baseline) | 0.881 | 1.414 | 1.0% | 30.3% | {'banknote': '0/1', 'cent': '50/170', 'chart': '0/6', 'fragment': '6/14', 'medal': '5/14', 'notcoin': '8/27', 'one_euro': '0/4', 'stamp_postmark': '4/5'} |
| probe dino | 0.956 | 0.334 | 1.9% | 71.4% | {'banknote': '1/1', 'cent': '110/170', 'chart': '3/6', 'fragment': '14/14', 'medal': '8/14', 'notcoin': '27/27', 'one_euro': '4/4', 'stamp_postmark': '5/5'} |
| probe dino+bm | 0.947 | 0.331 | 1.9% | 78.8% | {'banknote': '1/1', 'cent': '132/170', 'chart': '2/6', 'fragment': '14/14', 'medal': '11/14', 'notcoin': '24/27', 'one_euro': '1/4', 'stamp_postmark': '5/5'} |

## Courbe de seuils — probe dino+bm (modèle retenu)

| seuil | 2€ perdus | junk capturé |
|---|---|---|
| 0.05 | 0.0% | 2.5% |
| 0.10 | 0.0% | 18.3% |
| 0.15 | 0.2% | 32.8% |
| 0.20 | 0.2% | 53.9% |
| 0.25 | 0.8% | 65.6% |
| 0.30 | 1.3% | 74.7% |
| 0.35 | 2.1% | 80.5% |
| 0.40 | 3.5% | 83.4% |
| 0.45 | 5.9% | 86.7% |
| 0.50 | 7.8% | 89.6% |
| 0.55 | 11.1% | 92.1% |
| 0.60 | 15.2% | 92.5% |
| 0.65 | 21.1% | 93.8% |
| 0.70 | 31.4% | 95.4% |
| 0.75 | 41.0% | 95.4% |
| 0.80 | 54.2% | 95.9% |
| 0.85 | 69.2% | 97.1% |
| 0.90 | 83.0% | 97.5% |
| 0.95 | 93.3% | 99.2% |

## Sanity hold-out conf=lo (bruité — ne sert PAS à choisir le seuil)

- 36 pos / 24 neg, scorés par le modèle final (fit sur tout le hi) au seuil 0.331 :
- vrais 2€ perdus = 27.8% · junk capturé = 50.0% · par kind : {'cent': '5/16', 'fragment': '3/3', 'medal': '3/3', 'other': '1/2'}

## Référence HANDOFF-C7 §1

Le seuil naïf sur `max(obverse-ness, reverse-ness)` perdait 4–16 % des vrais 2€ pour 25–68 % de junk capturé (run AT-2005). La baseline (a) ci-dessus le reproduit sur ce gold ; la probe doit faire nettement mieux.
