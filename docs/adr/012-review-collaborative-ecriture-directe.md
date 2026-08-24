# ADR-012 — Les amis reviewent le canonique directement, en quarantaine par scope

- **Statut** : ✅ Acceptée
- **Date** : 2026-08-23 · en production et utilisée depuis le même jour
- **Supersède** : l'architecture `review.db` + pont `publish`/`reconcile` de
  `collaborative-review/` (juin 2026), qui reste valide *pour son époque*

## Contexte

La review manuelle des crops eBay restera majoritaire même avec l'auto-validation, et
le PO seul ne tiendra pas le volume. Il faut faire reviewer des **amis non techniques,
depuis leur propre ordinateur**.

Le design de juin prévoyait un **tampon** : un `review.db` sur le VPS, alimenté par
`publish` depuis le canonique et renvoyant ses décisions par `reconcile`. Ce tampon
existait pour une seule raison — `eurio.db` vivait alors derrière un lease sur le Mac,
et il fallait un endroit toujours allumé.

Sous [Direction A](./009-direction-a-writer-canonique-unique.md), le canonique **est**
sur le VPS. Le tampon recopierait la donnée d'un serveur vers lui-même.

Deuxième surprise en ouvrant le chantier : **le back était déjà écrit, en triple.** Le
blocage n'était pas le calcul lourd, mais trois détails — des URLs d'images relatives
préfixées vers `127.0.0.1:8042`, un `decided_by = 'admin'` en dur, et `cv2` exclu de
l'image VPS par association avec torch alors qu'il n'y sert que de bibliothèque
d'images.

## Décision

**Un ami travaille directement sur `review_queue` du canonique, via `eurio-api`, depuis
le front hébergé.** Pas de tampon, pas de base locale chez lui, pas de PWA.

- **Identité** : un compte Authentik dans le seul groupe `eurio-reviewer`
  ([ADR-010](./010-authentik-oidc-et-pat.md)). La ligne `users` se crée au premier login.
- **Quarantaine par scope, pas par rôle.** Un nouveau scope `review:arbitrate`, donné à
  `owner` et `admin` seulement. Un principal qui ne l'a pas voit ses décisions atterrir
  dans `peer_review_decisions` en `pending`, **sans toucher `review_queue` ni
  `image_assets`**. Le PO relit en lot dans `/review/arbitrage`, désaccords DINO en tête.
- **Le navigateur envoie trois flottants ; le serveur possède les pixels.** Le recadrage
  est appliqué côté VPS par `_crop_mask_resize_float` (`opencv-python-headless` ajouté à
  l'image, **pas** torch).
- **DINO ne va ni sur le VPS ni dans le navigateur.** Les suggestions sont servies en
  lecture pure ; après un recadrage la prédiction est **datée comme suspecte**
  (`stale_since`, migration 0013) et le Mac réencode en lot.
- **L'ami ne voit jamais le mot « local », ni un numéro de port, ni un bouton mort.**

## Alternatives considérées

| Option | Verdict |
|---|---|
| Tampon `review.db` + publish/reconcile (design de juin) | ❌ Recopie la donnée d'un serveur vers lui-même sous Direction A. Deux schémas à tenir synchronisés pour rien |
| PWA + base locale chez l'ami | ❌ Un lot pèse ~3,9 Mo. Le hors-ligne n'est pas le besoin ; le besoin est « ça marche sur son PC sans rien installer » |
| Crop en Canvas côté client | ❌ Faisable en dix lignes, et **silencieusement faux** : `canvas.drawImage` ne rééchantillonne pas comme `INTER_AREA`, et pas pareil selon le navigateur et le GPU. On obtiendrait des crops qui diffèrent selon la machine de l'ami — une pollution muette du jeu d'entraînement, alors que ces pixels nourrissent l'entraînement |
| Conteneur DINO CPU sur le VPS | ⏸️ Gardé en réserve. 0 crop sur 21 223 n'a de prédiction persistée : le fallback lourd ne s'allume jamais |
| DINO dans le navigateur | ❌ La banque passerait (7,8 Mo) mais elle est encodée en `vitl14` (~300 M paramètres). Le seul modèle navigable, `vits14`, mesure 41,6-45,5 % contre 77,8 %. On servirait aux amis un DINO deux fois moins bon |
| Quarantaine par rôle | ❌ Par scope, le PO se forge un PAT restreint et recette toute l'expérience « ami » depuis son propre compte, sans créer un seul compte Authentik |
| Un second système de permissions | ❌ Deux vérités qui divergent. Les scopes existants suffisent ([ADR-010](./010-authentik-oidc-et-pat.md)) |

## Conséquences

**Bonnes.** La boucle est fermée et parcourue en production : 12 décisions signées par
un compte non-admin sont arrivées en quarantaine, canonique intact, relues en lot.
Inviter quelqu'un coûte une création de compte.

**Mauvaises, et assumées.**

- **Un ami dans `eurio-admin` en plus de `eurio-reviewer` n'est jamais mis en
  quarantaine.** Le groupe unique est une règle d'exploitation, pas une garde technique.
- Le **bail sur la file** (`claimed_by`/`claimed_at`) n'existe pas : deux amis
  simultanés se marchent dessus. Se déclenche au deuxième invité, à mesurer avant de
  dimensionner.
- `eurio-review.musubi.dev` et `admin/packages/review/` sont **toujours debout** en
  doublon. Leur retrait est un lot à part, à ne pas jouer un jour de recette.

## Une erreur de design qui mérite d'être gardée

La première implémentation **supprimait** les prédictions DINO du crop d'avant : leur
absence servait de marqueur, sans colonne ni table. C'était le plus élégant des deux
designs, et le seul à ne rien coûter en schéma. Il supposait qu'une prédiction périmée
ne vaut rien.

La première vraie session de review l'a réfuté :

> « moi je commence toujours par faire le recadrage et après je pick la bonne pièce.
> Souvent, la suggestion de Dino de base est bonne. »

Le geste réel est un ajustement **au micro** du cadrage suivi du choix de la pièce.
Supprimer retirait l'aide juste avant le moment où elle sert. Une prédiction périmée
vaut souvent encore la bonne réponse — ce que seul l'usage pouvait dire.

## Voir aussi

- Chantier vivant (reste : bail sur la file, retrait des piles en doublon) :
  [`../work-in-progress/review-collaborative-v2/`](../work-in-progress/review-collaborative-v2/)
- Décisions détaillées D1-D14 : `review-collaborative-v2/DECISIONS.md`
