# Bench encodeurs zero-shot (banque 2eur_all, set labellisé review)

- 604 crops labellisés · 546 ancres (composition de la banque `2eur_all` live)
- Recall mesuré sur crops in-scope (vérité dans la banque) ; bande pays = ancres du pays cible du listing (même logique que la prod).
- Chaque modèle utilise SA transform recommandée (résolution/normalisation) — le zero-shot est un proxy du potentiel post-fine-tune ArcFace, pas une mesure absolue.

| Modèle | M params | px | dim | global@1 | global@5 | pays@1 | pays@5 | ms/img |
|---|---|---|---|---|---|---|---|---|
| dinov2_vitb14 | 86.6 | 224 | 768 | 66.3% | 80.2% | 79.8% | 90.5% | 47 |
| dinov2_vits14 | 22.1 | 224 | 384 | 53.7% | 72.8% | 70.8% | 87.9% | 29 |
| timm:tiny_vit_21m_224.dist_in22k_ft_in1k | 20.6 | 224 | 576 | 22.4% | 37.3% | 43.2% | 69.1% | 27 |
| timm:tiny_vit_11m_224.dist_in22k_ft_in1k | 10.5 | 224 | 448 | 18.5% | 32.5% | 43.0% | 64.4% | 25 |
| timm:mobilevitv2_200.cvnets_in22k_ft_in1k | 17.4 | 256 | 1024 | 16.4% | 30.6% | 36.6% | 63.9% | 37 |
| timm:efficientformerv2_s2.snap_dist_in1k | 12.1 | 224 | 288 | 13.8% | 24.1% | 34.7% | 62.3% | 25 |
| timm:repvit_m2_3.dist_450e_in1k | 22.4 | 224 | 640 | 12.1% | 22.7% | 30.9% | 60.4% | 52 |
| timm:convnextv2_nano.fcmae_ft_in22k_in1k | 15.0 | 224 | 640 | 9.9% | 19.5% | 25.4% | 55.6% | 32 |
| timm:eva02_tiny_patch14_336.mim_in22k_ft_in1k | 5.6 | 336 | 192 | 4.1% | 10.1% | 15.5% | 42.5% | 59 |
| timm:mobilenetv4_conv_large.e600_r384_in1k | 31.3 | 384 | 1280 | 3.9% | 8.9% | 13.3% | 39.2% | 38 |

