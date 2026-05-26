# Inspection Log — running diary

Format : `YYYY-MM-DD HH:MM` + 1 ligne.

```
2026-05-26 22:00  Chantier ouvert. Setup doc structure.
```
2026-05-26 22:05  Sampler HTML construit. Screenshots 4 groupes × 4 méthodes faits.
2026-05-26 22:15  Observation : 4 catégories d'erreurs identifiées (A faux positif, B inner feature, C multi-album, D OK). Volume cat A+B ~15-20%, D ~25-30%, C ~50-60%. Voir findings/01-*.md.
2026-05-26 22:50  Expé 01 lancée (sampler_by_score bottom/top × 30). Verdict asymétrique : TOP 83 % D ✓, BOTTOM 30 % A+B ✗ (pollué par C). Composite OK pour tri descendant, KO pour reject auto. Théories 01+02 à instancier séparément. Voir experiments/01-*.md.
2026-05-26 23:30  Branchement composite score = tri par défaut UI Crop (backend + frontend). DÉCOUVERTE : top-scores composites sont souvent UNDERCROP SUSPECTS. Le composite mesure "ressemble à une pièce", pas "bien cadré" — un crop tiny d'une partie centrale d'une pièce bimétal a bien rim+metal, donc score haut. area_ratio (cat B) et composite sont orthogonaux. Implication pour expé 02 : besoin d'un signal "rim_to_crop_ratio" qui détecte si le crop est zoomé trop loin SUR une pièce (cat B), distinct de "est-ce une pièce" (cat A).
2026-05-26 23:55  Expé 02 lancée (unified_score = composite × area_ratio_factor). BOTTOM 27 % A+B (marginal vs v1 30 %), TOP 85 % D (+2 pts). Conclusion : area_ratio ne distingue pas cat B (undercrop bimétal) de cat C (album multi) → multiplication échoue. Recommandation : exposer 2 signaux indépendants au lieu d'un score unifié, thresholds séparés par dimension.
