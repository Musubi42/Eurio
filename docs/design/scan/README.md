# Scan — la killer feature

> **Objectif UX** : l'user pointe sa caméra vers une pièce, la détection est continue, le résultat apparaît en < 2 secondes. Pas de bouton capture, pas de cercle à aligner, pas de guide bloquant. Style Yuka / lecteur de QR.
>
> **État actuel** : le pipeline ML a des briques en place (`app/src/main/java/com/musubi/eurio/ml/` — CoinDetector, CoinEmbedder, CoinAnalyzer, EmbeddingMatcher). La Phase 2A (classification bridge) est en cours ; la Phase 2B (ArcFace 500+ classes) est la prochaine étape bloquante. La partie UX n'est pas encore designée.

---

## Sous-docs

- [`ux-research.md`](./ux-research.md) — pattern Yuka, continuous detection, états d'échec, feedback visuel.
- [`ml-pipeline.md`](./ml-pipeline.md) — flux caméra → détection → embedding → matching → résultat. Référence aux docs ML existantes.
- [`remote-fallback.md`](./remote-fallback.md) — **question ouverte** : que faire quand le scan local échoue parce que la pièce n'est pas dans le modèle ?
- [`data-flow.md`](./data-flow.md) — qu'est-ce qu'on lit côté Room, qu'est-ce qu'on fetch côté Supabase, quelles sont les données qui sortent du scan.
- [`debug-overlay.md`](./debug-overlay.md) — l'overlay de debug qui affiche bounding box, top-K matches, latences, outils de dump. Activé toujours en build debug, togglable via 7-tap en release. Voir aussi [`../_shared/dev-debug-strategy.md`](../_shared/dev-debug-strategy.md).

---

## Décisions tranchées

| Décision | Contexte |
|---|---|
| **Scan continu, pas de bouton** | PRD §5.1 + mémoire `feedback_scan_ux.md`. Style Yuka, zéro friction. |
| **100% on-device par défaut** | Aucune photo envoyée au backend pour un scan qui réussit localement. Respect vie privée + zéro latence. |
| **Fallback serveur optionnel en cas d'échec** | Idée du 2026-04-13 : si le scan local ne matche pas, envoyer la photo à un endpoint serveur qui a le modèle à jour. **Pas tranché, voir `remote-fallback.md`.** |
| **Vue unique paramétrée pour la fiche pièce** | Voir [`../coin-detail/README.md`](../coin-detail/README.md). Le résultat du scan = fiche avec un CTA "Ajouter au coffre". |
| **Pas d'affichage fantaisiste en cas de doute** | PRD §5.1 : jamais de résultat avec confidence basse affiché comme certain. Si doute, on dit "pièce non identifiée" + suggestions. |
| **Overlay de debug dédié** | Décidé le 2026-04-14. Un `ScanDebugOverlay` affiche en temps réel la bounding box, le top-K, les latences et des outils de dump. Activé toujours en build debug, togglable via 7-tap sur le numéro de version en build release. Voir [`debug-overlay.md`](./debug-overlay.md) et [`../_shared/dev-debug-strategy.md`](../_shared/dev-debug-strategy.md). |

---

## Flow cible (happy path)

```
Tap onglet Scan
  ↓
Caméra CameraX active, preview plein écran
  ↓
[Overlay léger] cercle pulsé indicatif, NON bloquant
  ↓
CoinDetector (déjà en place) tourne en continu sur les frames
  ↓
Dès qu'une pièce est détectée + nette + bien cadrée
  ↓
CoinEmbedder calcule l'embedding de la pièce (TFLite on-device)
  ↓
EmbeddingMatcher compare aux embeddings canoniques locaux (KNN)
  ↓
Si top-1 confidence > seuil → résultat immédiat
  ↓
[Transition] snapshot figé de la frame, feedback visuel (pulse vert)
  ↓
Fiche pièce s'ouvre en modal bottom-sheet (ou full screen)
  ↓
CTA "Ajouter au coffre" (1 tap)
  ↓
Retour au scan pour la suivante
```

## Flow cible (échec)

```
Scan tourne
  ↓
Confidence top-1 < seuil (ou écart top-1/top-2 insuffisant)
  ↓
[Après 3 secondes de scan continu qui ne converge pas]
  ↓
Overlay discret : "Approche un peu, ou essaie une meilleure lumière"
  ↓
Si ça ne converge toujours pas après 6 secondes
  ↓
Option : capturer manuellement un snapshot → page "pièce non identifiée"
  ↓
Sur cette page :
  - Affichage de la photo capturée
  - Infos extraites partielles si dispo (pays probable, valeur faciale probable détectée par le modèle)
  - Boutons :
    - "Essayer à nouveau" (retour scan)
    - "Envoyer au support pour analyse" (= fallback serveur, voir remote-fallback.md)
    - "C'est une pièce de {valeur}" → permet à l'user de la taguer manuellement et de l'ajouter quand même au coffre (mode dégradé)
```

## Feedback visuel (à préciser en UX research)

- **Détection en cours** : cercle pulsé blanc/gris discret.
- **Pièce détectée** : cercle devient vert, pulse plus rapide.
- **Match trouvé** : flash vert léger + transition vers la fiche.
- **Confiance basse** : cercle orange + texte d'aide.
- **Échec** : cercle rouge pâle + bouton capture manuelle.

**Zéro son** par défaut. Vibration haptique discrète à l'ouverture de la fiche (configurable).

---

## Questions ouvertes

- [ ] Seuil de confidence exact pour déclarer un match. Dépend des métriques Phase 2B.
- [ ] Gestion recto/verso : un scan = une face. Est-ce qu'on demande à l'user de retourner la pièce pour confirmer ? Est-ce qu'on matche sur une seule face suffit ? → dépend de la discrimination du modèle.
- [ ] **Remote fallback** : stratégie à décider. Voir [`remote-fallback.md`](./remote-fallback.md).
- [ ] Comportement si plusieurs pièces sont dans le champ : on détecte la plus grande ? On refuse ? On scanne chacune en série ?
- [ ] Est-ce qu'on sauvegarde la photo scannée par l'user dans `user_collection.user_photo_path` systématiquement, ou seulement si l'user ajoute au coffre ? Impact stockage.
