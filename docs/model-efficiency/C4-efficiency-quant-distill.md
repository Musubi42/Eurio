# C4 — Efficacité : quantization + distillation

**Statut : 🔲 pas commencé**  ·  Dépend de : C0

## Objectif

Réduire **poids** et **latence** du modèle sans perdre (trop) en qualité, pour
élargir le parc de téléphones cibles (lien C5) et alléger l'APK.

État : fp16 = **41.8 MB**, 5.68 GMACs. Le backbone ViT-S (21,7M params) est le
poste de coût.

## Pourquoi à cette place

Indépendant de la couverture : peut avancer en parallèle dès que C0 fournit une
baseline contre laquelle mesurer la perte de qualité.

## Hypothèses (à challenger)

- **H3 — fp16 ≈ sans perte ; int8 dégrade un ViT.**
  Croyance : moyenne (typique, **pas mesuré sur ce modèle**). Test : lancer
  `ml/scripts/spike_vits14_litert.py` → cosinus vs eager + latence CPU pour
  fp32 / int8-dynamic / fp16, puis R@1 (C0) par variante.
- **Hypothèse distillation — un student léger (TinyViT / EfficientFormer /
  MobileViT, déjà dans `timm`) garde ~la qualité du ViT-S prof.**
  Croyance : à prouver. Test : distiller, mesurer R@1 (C0) + taille + latence
  vs le prof.

## Benchmark à semer

| Variante | Taille | Cosinus vs fp32 | Latence CPU | R@1 (C0) |
|---|---|---|---|---|
| fp32 | 83.3 MB | 1.000 | | |
| fp16 | 41.8 MB | | | |
| int8-dynamic | ~21 MB ⚠️ estimation | | | |
| student distillé | ~10-15 MB ⚠️ estimation | | | |

## Plan

- [ ] Lancer le spike → remplir cosinus + latence réels (supprime ⚠️).
- [ ] Mesurer R@1 (C0) par variante quantizée.
- [ ] POC distillation d'un student ; comparer le triplet taille/vitesse/qualité.
- [ ] Choisir la variante de déploiement par tier de device (lien C5).

## Résultats

_(vide — le spike fournit les premières lignes)_

## Décisions & next

_(à compléter)_
