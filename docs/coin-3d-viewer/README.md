# Coin 3D Viewer

Vue 3D interactive d'une pièce de monnaie, déclenchée à la fin d'un scan
réussi (la pièce identifiée apparaît avec un flip cinématique de 600 ms,
et l'utilisateur peut la manipuler en attendant de voir les détails).

Cette feature a deux histoires :

1. **Proto Three.js** — `docs/design/prototype/scenes/scan-coin-3d.{html,js}` —
   validation visuelle du concept (mesh procédural bimétal, UV mapping XY→photo,
   normal map Sobel, éclairage 2-key + ACES). ✅ Réussi.
2. **Implémentation Android** — `app-android/.../features/scan/components/Coin3DViewer.kt`
   et autour — portage SceneView/Filament 1:1 du proto, avec quelques évolutions
   techniques (custom material `.filamat`, cache disque des normal maps, animation
   flip Compose). ✅ Shippé, validé sur Pixel 9a.

## Objectif produit

- Acte central : scan → identification → **animation 3D de la pièce détectée** → fiche détaillée
- Le viewer 3D est un **moment de plaisir**, pas une fonctionnalité technique. Il vend la qualité de l'app.
- L'utilisateur peut tourner la pièce, zoomer, voir les deux faces et la tranche.

## Contraintes Eurio (toujours valides)

- **100% local** côté inférence et rendu. Pas de requête à l'infra Eurio pour afficher la 3D — uniquement les synchros périodiques.
- **Photos originales Numista intouchables.** On ne modifie pas le dataset source. Tout traitement passe par des **métadonnées** stockées à côté ou par du calcul runtime.
- **Pas d'augmentation de scope** : un viewer 3D, pas un studio de delighting/photogrammétrie/PBR pro.

## Approche retenue

Mesh procédural bimétal (anneau argent + disque or + tranche cylindrique + rebord
saillant), textures = scans Numista plaqués via UV mapping XY→photo, normal map
dérivée par Sobel sur la luminance pour la subtilité du relief sous éclairage.

Les paramètres PBR (metalness/roughness/normalScale, IBL) se transposent 1:1
entre Three.js et Filament. Les seuls deltas réels sont des contraintes
toolchain Filament documentées dans `porting-android.md` (D-PORT-3 à 7).

## Documents

- [`decisions.md`](./decisions.md) — D1–D8 actées et chemins explicitement rejetés (proto, restent valides en prod)
- [`technical-notes.md`](./technical-notes.md) — géométrie 2€, math UV, Sobel, lighting (référence transposable Three.js ↔ Filament)
- [`porting-android.md`](./porting-android.md) — trace du portage Android : status par phase, table de correspondance API, décisions de portage (D-PORT-1 à 7), pièges Filament/SceneView rencontrés

## Statut

| Pièce | Statut |
|---|---|
| Proto Three.js (pièce 226447 + carousel) | ✅ |
| Implémentation Android (Phases 0–6) | ✅ |
| Extension hors 2€ (1€, 50¢, etc.) | ⏳ — factory de mesh par dénomination, pas avant un vrai besoin produit |
| Tranche per-pays | ⏳ — texte d'inscription par ISO, voir D5 et R5 dans `decisions.md` |
