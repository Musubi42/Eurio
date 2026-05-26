# Inspection Log — running diary

Format : `YYYY-MM-DD HH:MM` + 1 ligne.

```
2026-05-26 22:00  Chantier ouvert. Setup doc structure.
```
2026-05-26 22:05  Sampler HTML construit. Screenshots 4 groupes × 4 méthodes faits.
2026-05-26 22:15  Observation : 4 catégories d'erreurs identifiées (A faux positif, B inner feature, C multi-album, D OK). Volume cat A+B ~15-20%, D ~25-30%, C ~50-60%. Voir findings/01-*.md.
2026-05-26 22:50  Expé 01 lancée (sampler_by_score bottom/top × 30). Verdict asymétrique : TOP 83 % D ✓, BOTTOM 30 % A+B ✗ (pollué par C). Composite OK pour tri descendant, KO pour reject auto. Théories 01+02 à instancier séparément. Voir experiments/01-*.md.
