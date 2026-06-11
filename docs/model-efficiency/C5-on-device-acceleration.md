# C5 — Accélération on-device

**Statut : 🔲 pas commencé**  ·  Dépend de : C0

## Objectif

Faire tourner le modèle **plus vite sur le téléphone** en exploitant les
accélérateurs (GPU / NNAPI / NPU-TPU), au lieu de l'interpréteur **CPU pur**
actuel. Objectif : scan fluide sur plus de devices.

## Pourquoi à cette place

Le délégué est orthogonal à la qualité : gros gain de latence potentiel sans
toucher au modèle. Mesurable dès que C0 + une métrique de latence existent.

## Hypothèses (à challenger)

- **H5 — La perf fp16 ViT-S est OK sur milieu/haut de gamme.**
  Croyance : faible — **aucune latence mesurée** à ce jour. Test : mesurer
  ms/inférence sur Pixel 9a (et d'autres devices si dispo) en CPU vs délégué.
- **Hypothèse délégué — un délégué GPU/NNAPI accélère ce graphe ViT.**
  À prouver : tous les ops ViT ne sont pas toujours supportés par les délégués
  (fallback CPU partiel possible). Test : activer le délégué, mesurer + vérifier
  qu'aucun op ne retombe en CPU.

## Benchmark à semer

| Device | Backend | ms / inférence | Notes |
|---|---|---|---|
| Pixel 9a (Tensor G4) | CPU | | baseline |
| Pixel 9a | GPU delegate | | |
| Pixel 9a | NNAPI / NPU | | |

## Plan

- [ ] Ajouter une mesure de latence on-device (logcat ou bench harness).
- [ ] Mesurer la baseline CPU (Pixel 9a).
- [ ] Tester délégué GPU puis NNAPI dans `CoinRecognizer` ; vérifier le support
      des ops (pas de fallback silencieux).
- [ ] Documenter le tiering device réel (remplace le tableau « estimation » de
      la VISION).

## Résultats

_(vide)_

## Décisions & next

_(à compléter)_
