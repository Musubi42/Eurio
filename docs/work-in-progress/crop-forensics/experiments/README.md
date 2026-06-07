# Expériences — index avec verdict

Chaque expérience est un fichier `NN-slug.md` avec sections fixes :
**But**, **Setup**, **Mesure**, **Résultat**, **Verdict** (win / lose /
inconclu), **Action** (ce qu'on commit ou tue).

| ID | Slug | Verdict | 1-liner |
|----|------|---------|---------|
| 01 | [composite-scorer-ab-d](./01-composite-scorer-ab-d.md) | inconclu (asymétrique) | TOP 30 = 83 % D ✓ ; BOTTOM 30 = 30 % A+B ✗ (pollué par C) |
| 02 | [unified-score-v2](./02-unified-score-v2.md) | marginal | unified = composite × area_ratio_factor. TOP 85 % D ✓ (+2 pts), BOTTOM 27 % A+B ✗ (B et C indistinguables par area_ratio) |
