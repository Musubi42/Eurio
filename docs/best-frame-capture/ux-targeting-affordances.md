# UX — Cibles, affordances et guidage doux du scan

> Notes posées après l'audit visuel du chunk 4 (2026-05-15). À reprendre
> plus tard pour travailler l'UX du scan en profondeur. **Pas d'action
> immédiate** : la pipeline best-frame n'est pas encore terminée.

## Insight principal

L'overlay graphique de debug (bbox arrondie qui devient cercle + halo
quand le lock se déclenche) a un effet UX inattendu : **il rend les
limites du modèle compréhensibles sans avoir à imposer des règles à
l'utilisateur**.

Cas concret : table avec plusieurs pièces, le user pointe sur celle du
milieu, le modèle détecte celle légèrement à droite. Sans feedback
visuel, le user pense que l'app est cassée. Avec feedback visuel, il
voit la cible se poser sur la mauvaise pièce, comprend tout seul que
c'est le cadre qui est trop chargé, et **améliore son comportement**
(écarte les autres pièces) au lieu de pester.

Conséquence pratique : **éviter les copy walls** du style "scanne une
seule pièce, bien éclairée, sur fond neutre…". Le visuel raconte la
même histoire, mais en montrant au lieu de prescrire — c'est la
différence entre un panneau "interdit de courir" et un sol mouillé qui
glisse un peu.

## Métaphore : viseur d'avion de chasse

Référence visuelle pour la suite : **HUD de cockpit / radar
militaire**.

- État 0 (rien à détecter) : écran neutre, peut-être un réticule
  passif (croix discrète au centre, ou rien).
- État 1 (acquisition) : carré qui apparaît autour de la cible
  détectée, anguleux et "computery". C'est le "TARGET SPOTTED".
- État 2 (verrouillage en cours) : transition vers un cercle / cible
  arrondie, plus serrée. Pulse léger. C'est le "TRACKING".
- État 3 (verrouillé) : la cible devient solide, change de couleur,
  ne pulse plus. C'est le "LOCKED ON".
- Échec / abort : flash rouge bref, retour à l'état 0.

L'idée n'est pas de faire littéralement F-22 mais d'emprunter le
**vocabulaire visuel** : changement de forme = changement de stade,
pulse = activité, fixité = certitude.

Le chunk 4 a déjà 60 % de cette grammaire (carré → cercle + halo,
pulse pendant acquiring, fixité pendant locked, flash rouge pour
abort). Le reste est cosmétique + accompagnement.

## Pistes à explorer plus tard

### Indicateurs ambient

Petites icônes/badges discrets qui apparaissent quand une condition
n'est pas optimale, sans bloquer le scan :

- **Luminosité** : icône soleil/lune barré si l'exposition est mauvaise.
  Pas un message d'erreur, juste un pictogramme dans un coin.
- **Stabilité** : icône main tremblante si la frame bouge trop.
- **Multi-pièces** : icône "···" si plusieurs détections concurrentes
  (le modèle ne sait pas laquelle choisir).
- **Distance** : icône loupe + / − si la pièce est trop loin ou trop
  proche pour normaliser proprement.

Tous montrés en bas d'écran, micro-taille, fade-in/fade-out. Jamais
bloquants. L'utilisateur les apprend au fil de l'usage.

### Évolution graduelle du réticule

Au lieu de juste bbox → cercle, on pourrait avoir une transition plus
narrative :

1. **Scan inactif** : croix fine pulse lentement au centre (l'app
   regarde).
2. **Détection** : la croix se contracte vers la position détectée,
   se transforme en angles "computery".
3. **Stabilisation** : les angles se ferment en carré, ligne plus
   épaisse.
4. **Acquisition** : carré → octogone → cercle, en quelques frames.
5. **Verrouillage** : cercle plein, halo, flash de confirmation.
6. **Décision** : transition fluide vers l'AcceptedCard (le réticule
   devient l'arrière-plan du coin viewer).

C'est plus de boulot d'anim mais ça rend l'attente "active" plutôt
que "morte".

### Audio (peut-être)

Bip discret au verrouillage (style scanner de supermarché ou QR app
de banque) — confirme l'action sans nécessiter regard sur l'écran.
Optionnel + désactivable.

### Haptic

Petit tick à l'acquisition, plus long au verrouillage. Confirme
sensoriellement, encore une fois sans demander d'attention visuelle.

## Quand reprendre ce doc

- Après chunk 6 (state machine formelle) : on aura les vrais états
  pour mapper le vocabulaire visuel.
- Phase 5 (Discovery moment) est probablement le bon moment pour
  unifier réticule de scan + entrée dans l'AcceptedCard.
- Avant la première release publique (le polish UX = différenciateur
  clé sur ce type d'app).

## Notes liées

- Mémoire `feedback_scan_ux` — scan continu QR-like, pas de boutons /
  guides bloquants. Cette piste UX est strictement compatible : on
  ajoute du feedback ambiant, jamais du gating.
- `docs/best-frame-capture/vision.md` — pour le scénario d'usage.
- `docs/app-implem-phases/README.md` — 14 décisions UX déjà actées.
