# Vue — Classement (post-v1-online)

> Doc-pont psychologie → app. Périmètre **post-v1-online** (compte + serveur requis). Overview : [`../README.md`](../README.md).
> Futur : la v1 est offline-first sans auth (décision #12) → le classement vient **après**.

## 1. Rôle

> Donner une **échelle de statut social** (modèle Trackmania) **menée par le local**, fondée sur la
> **rareté détenue** plutôt que le volume. « Où je me situe » — sans démoraliser.

**Drive primaire** : Statut — secondaire : Social.

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Comparaison sociale** (Festinger) | on s'évalue par rapport aux autres similaires | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) |
| **Local dominance** | « 10ᵉ de ta région » mord plus que « 1000ᵉ mondial » | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) |
| **N-effect** | « tu es **1 of 12** à détenir cette pièce » > leaderboard de millions (Garcia & Tor 2009 : moins de concurrents → motivation compétitive plus forte ; la rareté/unicité Cialdini joue en parallèle — voir `03` §4 pour la distinction) | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) |
| **Proximité au n°1** | être près du sommet dope la compétitivité | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) |
| **Goal-gradient** | on accélère à l'approche du but (ex. « 1 pièce pour passer 9ᵉ ») | [`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) |

## 3. Actions × biais

| Action | Levier |
|---|---|
| Voir son rang **multi-échelle** : amis < région < pays < zone euro | local dominance |
| Voir « tu es **1 of N** à détenir X » | N-effect |
| Voir « il te manque 1 pièce pour passer 9ᵉ » | proximité au n°1 + goal-gradient |
| Comparer à un **ami** | comparaison sociale (similaire) |

## 4. Contenu

- Classements **menés par le local/amis** (le mondial existe mais n'est jamais l'entrée par défaut).
- **Statut par rareté détenue** (pas volume brut) → valorise les pièces rares qu'on veut faire chercher.
- **Grades de compétence** (médaille-like) à côté, pour un feedback **solo non-démoralisant**.

## 5. Garde-fous

- **Jamais le classement mondial brut à un débutant** (il serait 4 000 000ᵉ → décourageant). Réduire
  l'échelle (amis/région/set de niche).
- **Upward comparison démoralisante** → toujours afficher une **comparaison gagnable** à côté (message « il te manque N pièce(s) » uniquement si le delta est ≤ 2 pièces réel — jamais approximé ni arrondi à la baisse).
- Filtre **SDT** : nourrir la compétence (« tu progresses »), pas une pure carotte de statut.
- **Pas de PvP agressif** — filtre SDT : le classement nourrit la compétence, pas la dominance pure ([`03`](../../psychologie-documentation/03-comparaison-sociale-classement.md) §Garde-fous).

## 6. Drives servis

Statut ⬤ · Social ◑ · Complétion ◔ (rang lié à la rareté détenue).

## 7. À proto'er (R1) + prérequis

**Neuf**, et **post-v1** : nécessite **compte + backend social** (rupture avec offline-first). À
proto'er quand le palier social s'ouvre. Note : alimente directement le **partage** ([`02`](./02-social-partage.md)).
