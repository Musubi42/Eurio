# Niveaux de collectionneur

> Découvreur → Passionné → Expert → Maître. Système simple, non punitif.
>
> **Principe** : le niveau reflète l'engagement réel du collectionneur. Pas de XP farmé. Pas de régression.

---

## Les 4 niveaux

| Niveau | Message | Ambiance |
|---|---|---|
| **Découvreur** | "Tu découvres l'univers des pièces euro" | Accueil chaleureux, suggestions de premiers scans |
| **Passionné** | "Tu prends goût à la collection" | Mise en avant des séries en cours |
| **Expert** | "Tu construis une belle collection" | Focus sur les sets difficiles et la valorisation |
| **Maître** | "Tu es un collectionneur confirmé" | Pas de prochaine étape visible — reconnaissance |

---

## Critères de passage (v1 provisoire)

Un user passe au niveau suivant quand **au moins un** des critères est rempli. Évite de bloquer un user qui construit sa collection par une voie atypique (ex: peu de pièces mais très rares).

### Découvreur → Passionné
- ≥ 6 pièces dans le coffre, OU
- 1ère série complète

### Passionné → Expert
- ≥ 26 pièces dans le coffre, OU
- ≥ 3 séries complètes, OU
- Valeur totale > 500 € (P50)

### Expert → Maître
- ≥ 100 pièces dans le coffre, OU
- ≥ 5 séries complètes, OU
- Valeur totale > 2000 € (P50), OU
- Au moins 1 pièce "Très rare"

## Règles

- **Pas de régression.** Une fois un niveau atteint, il est permanent. Si l'user vend des pièces, il garde le niveau.
- **Pas de notification spammy.** Passage de niveau = 1 notification douce avec animation plein écran au prochain ouvrier de l'app.
- **Pas de niveau 5+.** Après Maître, plus de "next level" visible. Le prestige est dans la collection elle-même, pas dans un chiffre qui grimpe à l'infini.
- **Calcul 100% local.** Depuis Room `user_collection` + `coin_price_observation`.

---

## Barre de progression

Affichée dans le header du profil : `▓▓▓▓▓░░░░░ 47% vers Expert`.

Calcul : la progression est celle du **critère le plus proche** pour atteindre le prochain niveau.

Exemple : l'user est Passionné avec 15 pièces et 1 série complète.
- Critère "pièces" : 15 / 26 = 58%
- Critère "séries" : 1 / 3 = 33%
- Critère "valeur" : 200 / 500 = 40%
- Progression affichée : **58%** (le meilleur)

Affichage du hint : *"Encore 11 pièces pour devenir Expert"*.

---

## Questions ouvertes

- [ ] Les seuils numériques (6, 26, 100) sont arbitraires. À calibrer sur les premiers users réels pour que la progression se sente ni trop rapide ni trop lente.
- [ ] Est-ce qu'on affiche la progression des 3 critères en parallèle, ou juste le meilleur ? → probablement juste le meilleur, pour ne pas surcharger.
- [ ] Faut-il un niveau secret "Légende" pour les users avec 500+ pièces ou valeur > 10 000 € ? (Risque : effet compétitif).
- [ ] Comment interagit le niveau avec l'onboarding ? Un user qui importe une grosse collection d'un coup passe-t-il direct à Expert ou on plafonne à Passionné le temps qu'il utilise l'app ?
