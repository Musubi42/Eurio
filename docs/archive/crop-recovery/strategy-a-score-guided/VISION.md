# Stratégie A — Crop guidé par le score (probe-as-oracle)

> Implémente `recrop(raw_bgr, hint)` (interface dans `../BENCHMARK.md` §2) puis se mesure
> sur le banc partagé. **Ne réinvente pas la mesure.** Probe **gelée**.

## L'idée

Le score de la probe **monte** quand le crop s'agrandit, jusqu'à capter la pièce entière,
puis **redescend** si on déborde sur le fond (vérifié : balayage 0,19→0,76 sur EMU/globe).
Donc le score **est** le signal « sous-croppé / sur-croppé ». On **cherche** le crop qui
**maximise le score**, autour de la détection.

## Mécanique (à raffiner par le bench)

1. Partir du `hint` (centre + `r_final` détecté, souvent le disque interne).
2. Générer des **candidats** : rayons croissants (ex. `r_final × {1.0, 1.3, … , 2.8}`,
   bornés à l'image) ; option **recentrage** (le centre du disque ≈ centre pièce sur le
   bimétal, mais à vérifier) ; éventuellement coarse-to-fine (gros pas puis affinage autour
   de l'argmax).
3. Scorer chaque candidat avec la probe gelée (batch).
4. **Garder l'argmax** ; le banc décide ensuite `passed = score ≥ τ`.
5. Retourner la **liste** des candidats scorés (pas juste l'argmax) → permet l'hybride.

## Pièges à traiter (ce que le bench doit attraper)

- **Sur-crop sur le fond** : si la probe préfère du contexte, l'argmax peut déborder. Garde :
  borner le rayon (max ~`r_final × 3` ou fraction d'image), et/ou pénaliser quand le crop
  contient beaucoup de fond (faible « coin-ness » géométrique).
- **Centre faux** : si la détection a accroché un sous-motif décentré, agrandir autour d'un
  mauvais centre déborde. Tester un petit balayage de centre.
- **Multi-pièces / lots** : ne pas faire grossir un crop jusqu'à avaler la pièce voisine
  (réutiliser la garde voisin-aware de `detect_circles_multi`). Cf.
  `feedback_recrop_multicoin_guard`.
- **Coût** : K scores DINO / détection. Mesurer le K minimal qui tient les critères →
  enrichment OK ; **inapplicable au scan on-device** (l'assumer, c'est le rôle de B).

## Découpage : voir `PLAN.md`.

## Ce qu'on rend en fin de session (`RESULTS.md`)
Le JSON de banc (schéma `../BENCHMARK.md` §4) + un court récap : chiffres D1/D2/D3, K
retenu, garde anti-sur-crop choisie, angles morts, cas de désaccord notables.
