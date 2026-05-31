# Mission — Croissance & monétisation

> Index : [`README.md`](./README.md) · Stratégie : [`product-strategy.md`](./product-strategy.md)
> (la *thèse* de growth vit dans la stratégie ; ici c'est le **travail** pour l'exécuter.)

## Objectif

Faire **grossir l'audience** et activer les **paliers de revenu** (affiliation → premium →
commission). Coût ~nul (train local, Supabase free, inférence on-device) ⇒ **la croissance
prime**, le revenu suit la taille.

## Les leviers (à construire)

### 1. Machine à contenu short-form (pilier principal)

Modèle des indie makers : comptes TikTok / Reels / Shorts, **skits divertissants et
partageables** finissant par un CTA app (cf. inspirations dans `product-strategy.md`).
À construire :
- une **liste de formats récurrents** domaine pièces (« cette pièce vaut €X », rareté,
  défi « trouve cette pièce », reveal de complétion, nouvelle sortie de la semaine, ASMR scan) ;
- un **calendrier** de publication soutenable en solo ;
- les **hooks app** qui rendent un scan/une complétion facilement filmables et partageables.

### 2. Hook produit partageable

Boutons de partage : « ma collection vaut €X », « il me manque 3 pays sur la carte eurozone ».
Rend la rétention virale.

### 3. Catalogue web (SEO + funnel)

Sortir le moat de données en **catalogue web public** multilingue (le « 2euros.org » propre,
officiel). Acquisition organique + entonnoir app + surface d'affiliation.

### 4. Affiliation (P1 — premier revenu)

Transformer les liens « où acheter » (mission Valorisation) en **liens affiliés**
(eBay Partner Network, LMDLP, Monnaie de Paris…). Zéro paiement à gérer, zéro stock.

### 5. Premium (P2)

Abonnement sur la couche valeur avancée : historique de cote, **alertes nouvelles sorties**
(différenciant), alertes prix, backup cloud, stats. Spec à écrire.

## Dépendances souples

- Le **contenu** peut démarrer dès que l'app montre quelque chose de filmable (scan + carte).
- L'**affiliation** s'appuie sur la mission Valorisation (le « où acheter »).
- Tout ça **précède et nourrit** la Marketplace (audience + wishlists + « à vendre »).

## Done quand

Une **boucle d'acquisition active** (contenu + SEO + partage) et un **premier revenu**
(affiliation) tournent ; premium spécifié.

## Détail / exécution

Memories : `project_marketplace_routing_benchmark`, `project_ebay_api_strategy`,
`project_lmdlp_rebuild`, `project_i18n_strategy` (multilingue pour le catalogue web/SEO).
