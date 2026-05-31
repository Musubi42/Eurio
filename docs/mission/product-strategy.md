# Stratégie produit Eurio

> La vision, l'étoile polaire, les paliers de valeur/revenu, et la croissance.
> Index des missions : [`README.md`](./README.md).

## Vision

**Eurio = le Pokédex des pièces euro.** L'acte central est le **scan** : on pointe sa
caméra sur une pièce, l'app l'identifie et la propose au coffre — comme TikTok tourne
autour de la création de contenu. Tout le reste orbite : coffre → sets à compléter →
**carte eurozone** (% possédé par pays, axe de progression unique au domaine) →
gamification (streak, grade, badges). Offline-first, reconnaissance **on-device**.

## North Star — la marketplace

À terme : **acheter / vendre / troquer des pièces dans l'app**, Eurio prenant une
**commission** sur la transaction (modèle Leboncoin). C'est l'étoile polaire, pas le
point de départ : les paiements / KYC / escrow / fraude / régulation viendront plus tard
et seront **peut-être opérés par un partenaire** (pas forcément nous).

**Principe d'échelle à paliers** : chaque palier livre de la valeur **tout seul**. Si on
n'atteint jamais la marketplace mais qu'on construit une belle app de collection aboutie,
**c'est déjà gagné**. La marketplace est alimentée par les paliers d'en dessous — elle n'a
pas de cold-start frontal.

## Le moat & l'économie

- **Moat = la donnée.** Référentiel officiel quasi-complet, à jour au bleeding-edge
  (on connaît les nouvelles commémo *avant* Numista via JO/couverture), prix par qualité,
  multilingue. Peu d'acteurs ont ça proprement.
- **Coût quasi-nul** : entraînement ML local (PC perso), Supabase free tier, **inférence
  on-device** (zéro coût d'inférence cloud), app locale. → On peut **prioriser la croissance
  avant le revenu** ; la monétisation suit la taille, sans pression de burn.

## Les paliers (valeur ↔ revenu)

| Palier | Valeur utilisateur | Revenu | Missions |
|---|---|---|---|
| **P0 — App gratuite** | scan + coffre + sets + carte eurozone : collecter, compléter, jouer | — (on grossit) | Scan, App |
| **P1 — Valorisation & complétion** | « combien vaut ma collection », cote par qualité, « il me manque ça → acheter ici » | **affiliation** (eBay Partner Network, LMDLP, monnaies) — zéro friction, pas de paiement à gérer | Valorisation, Croissance |
| **P2 — Premium** | historique de cote, **alertes nouvelles sorties** (notre moat), alertes prix, backup cloud, stats avancées | abonnement | Valorisation, Croissance |
| **P3 — Marketplace** | acheter/vendre/troquer in-app | **commission** | Marketplace |

La liquidité de P3 est construite par P1/P2 : la valorisation crée naturellement des
**wishlists** (« ce qui me manque ») et des items **« à vendre »** → l'offre et la demande
existent déjà quand la marketplace ouvre.

## Stratégie de croissance

Coût ~nul ⇒ la croissance prime. Quatre leviers, le premier en tête.

### 1. Contenu short-form viral (pilier principal)

Le modèle des **indie makers** : des comptes TikTok / Reels / YouTube Shorts qui publient
du contenu **divertissant et partageable**, avec un CTA app à la fin. Références d'inspiration :
l'app réveil qui ne s'éteint que si tu photographies un objet imposé (frigo…), l'app de
dating « anime/waifu » dont toute la com est des mini-skits romance. Le format est un *skit*
qu'on a envie de **renvoyer à un pote**.

Transposé aux pièces (idées de formats) :
- **« Cette pièce dans ta monnaie vaut €X »** — reveal satisfaisant (scan → cote).
- **La plus rare / la plus chère** (Monaco Grace Kelly, etc.), micro-histoires de pièces.
- **Défi « trouve cette pièce »**, complétion d'un pays sur la carte (dopamine).
- **« On vient de débloquer la commémo qui sort cette semaine »** (on l'a au bleeding-edge).
- ASMR/oddly-satisfying de scan + ajout au coffre.

→ Une **machine à contenu** (calendrier, formats récurrents) fait partie de la mission Croissance.

### 2. Hook produit partageable

Le scan→valeur et la **carte eurozone à compléter** sont intrinsèquement partageables
(« regarde ma collection / il me manque que 3 pays »). On bâtit le partage dans l'app.

### 3. Catalogue web (SEO + funnel)

Le moat de données peut sortir en **catalogue web public** : le « 2euros.org » propre,
officiel, multilingue. Acquisition organique (SEO sur « valeur pièce 2 euros X »…) +
entonnoir vers l'app + surface d'affiliation.

### 4. Rétention

Streak (hook #1), **alertes nouvelles sorties** (différenciant — on les connaît avant
les autres), complétion de sets/carte. → Boucle d'engagement qui nourrit aussi le contenu.

## Monétisation — détail par palier

- **Affiliation (P1)** : on surface déjà l'intention d'achat (« il te manque Y »). On
  monétise via liens affiliés eBay Partner Network / LMDLP / Monnaie de Paris. Aucun
  paiement ni stock à gérer. **Premier revenu, le plus rapide.**
- **Premium (P2)** : abonnement pour la couche valeur avancée (historique, alertes,
  backup, stats). L'audience numismate paie pour la cote et la rareté.
- **Commission marketplace (P3)** : % sur transaction, North Star.

## Principes

- On avance sur l'**envie** et l'**opportunité** (dépendances souples) — le seul vrai
  prérequis dur reste les **captures** pour débloquer le bench du scan.
- Chaque palier est **autonome** : pas de pari tout-ou-rien sur la marketplace.
- **Qualité avant tout** (R0) : on construit une app qu'on est fier de montrer — c'est
  aussi ce qui rend le contenu viral crédible.
