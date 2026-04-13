# Scan — UX research

> Pattern "scan passif continu" : l'user ne capture pas, l'app détecte. Modèle de référence : Yuka, lecteurs QR natifs Android, Google Lens.

---

## Principes

1. **Pas de bouton capture.** Un bouton = une action à faire = friction. Le scan doit arriver à l'user, pas l'inverse.
2. **Pas de cercle à aligner strict.** Un cercle indicatif qui n'est JAMAIS une condition bloquante. Si la détection marche avec la pièce en coin de l'image, on accepte.
3. **Pas de zoom manuel.** Le détecteur trouve la pièce à n'importe quelle taille raisonnable.
4. **Feedback instantané mais non-intrusif.** Pulse discret. Jamais de modal "êtes-vous sûr ?".
5. **Tolérance à l'échec.** Si le scan ne converge pas, on ne rage-quit pas l'user : on suggère un léger ajustement (lumière, distance).

---

## Micro-interactions à prototyper

- **Pulse du cercle indicatif** pendant la détection : période ~1.2s, amplitude douce.
- **Transition scan → fiche** : snapshot figé de la frame, fade vers la fiche en 200ms. Donne l'impression que l'app "a pris la photo" même si c'est passif.
- **Haptique** : un `HapticFeedbackConstants.CONFIRM` quand le match est trouvé. Coupe le son environnant, l'user sait qu'il peut regarder son écran.
- **Pas de toast.** Jamais. Les toasts sont lus après, ou pas du tout.

## Cas d'usage réels à valider

- Scan sur une pièce posée sur une table en bois.
- Scan sur une pièce dans la main (le doigt fait du bruit dans l'image).
- Scan dans une poche / un porte-monnaie ouvert (reflets, ombres).
- Scan de nuit sous lampe incandescente jaune (température de couleur différente).
- Scan avec la pièce légèrement inclinée (pas à plat).
- Scan avec plusieurs pièces côte à côte.

Ces cas servent de benchmark pour le détecteur ET pour l'UX. Si un cas échoue, on doit savoir pourquoi (détection ? embedding ? matching ?) et afficher un message d'aide adapté.

## Anti-patterns à éviter

- "Aligne la pièce dans le cercle" — non, le détecteur se débrouille.
- "Tapote pour mettre au point" — le autofocus CameraX gère.
- "Photo prise !" ding sonore triomphant — non, discret.
- "Loading..." spinner pendant l'embedding — doit être < 200ms, sinon on a un problème de modèle, pas d'UX.
- Cropper le résultat en carré et imposer un format — on garde le context visuel de la frame.

---

## Inspirations

- **Yuka** : ouverture directe caméra, scan continu, fiche bottom-sheet à l'apparition du résultat. Pas de bouton. Référence absolue.
- **Google Lens** : détection continue de plusieurs objets, overlay de points sur chaque candidat. Trop complexe pour notre cas (on a un seul objet : une pièce), mais le principe de continuité est bon.
- **NutriScore / OpenFoodFacts** : même pattern Yuka, fiche produit immédiate au scan du code-barres.
- **Apple Vision sur iOS** (détection objets en preview) : pour la fluidité de la détection en temps réel. On ne peut pas copier côté Android, mais c'est le niveau de qualité cible.

## Ce qu'on NE copie PAS

- **CoinSnap** : paywall agressif, pubs, UX datée. Contre-exemple parfait.
- **CoinManager** : cercle à caler obligatoire, focus manuel. On veut l'opposé.
