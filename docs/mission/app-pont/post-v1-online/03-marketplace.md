# Vue — Marketplace (post-v1-online)

> Doc-pont psychologie → app. Périmètre **post-v1-online**. Overview : [`../README.md`](../README.md).
> **North Star** (`../../marketplace.md`) — étoile polaire, **pas v1**. Ici : la lecture *psychologique*
> de la surface, pas la mécanique paiement/KYC/escrow (peut-être opérée par un partenaire).

## 1. Rôle

> **Acheter / vendre / troquer** des pièces dans l'app (commission). Et, en amont et **dès la v1
> (offline)**, la surface **affiliation** (« il te manque ça → acheter ici »).

**Drive primaire** : Complétion (wishlist/demande) — secondaires : Valeur (ancre prix), Social (troc).

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Le manque = moteur** (Zeigarnik — boucle inachevée → demande) | la complétion crée naturellement une **wishlist** (la demande) | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Endowment (possession → surévaluation)** | on survalorise ce qu'on possède → l'offre (« à vendre ») et le prix psychologique du vendeur | [`01`](../../psychologie-documentation/01-motivations-baseline.md) · [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **IKEA / labeur-signifiant** | la pièce chassée/scannée est plus difficile à céder — elle a été méritée | [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **Valeur / sécurité financière** | la cote par qualité ancre les prix | `01` · mission Valorisation |
| **Liquidité construite par P1/P2** | wishlists + « à vendre » existent *avant* l'ouverture du marché | `../../product-strategy.md` |

## 3. Actions × biais

| Action | Levier | Source |
|---|---|---|
| Marquer une pièce manquante **wishlist** | Zeigarnik (boucle ouverte → demande) | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| Tap « où l'acheter » → **lien affilié** (v1) puis **offre in-app** (P3) | valeur + revenu | `01` · mission Valorisation |
| Marquer une pièce **à vendre** | Endowment (possession → offre) | [`01`](../../psychologie-documentation/01-motivations-baseline.md) · [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **Troquer** avec un autre collectionneur | social + complétion mutuelle *(hypothèse — non encore sourcée dans le corpus `01-08`)* | — |

## 4. Garde-fous

- **L'app ne devient pas un casino financier** : la cote reste *informative*, pas spéculative
  (cohérent avec « pas de manipulation »).
- **Prix de transaction in-app (P3)** : afficher une tendance de référence, jamais un cours temps-réel coté (pas de graphe flottant façon bourse) — l'historique de transactions ne doit pas alimenter de logique de trading/arbitrage. Point à re-vérifier au démarrage de P3 avec la mécanique KYC/escrow.
- **Affiliation transparente** (« lien partenaire ») — déjà OK dès la v1 (page pièce, [`03-page-piece`](../v1-offline/03-page-piece.md)).
- **Paiement/KYC/escrow/fraude** = **hors design psy**, possiblement délégués à un partenaire.

## 5. Drives servis

Complétion ⬤ (wishlist/demande) · Valeur ◑ (ancre prix) · Social ◑ (troc).

## 6. À proto'er (R1) + prérequis

- **Affiliation** (liens « où acheter ») : **dès v1**, offline, dans la page pièce / cases manquantes.
- **Marketplace transactionnelle** : **P3 / post-v1**, compte + paiement + régulation → étoile polaire.
  La psycho dit : la liquidité est **déjà préparée** par les wishlists (le manque) et les « à vendre »
  (endowment) construits aux paliers d'avant.
- ⚠️ **R1 — surfaces P3** : toute vue transactionnelle nouvelle (vue offres, profil vendeur, flux troc,
  wishlist publique) devra être proto'ée avant implémentation Android — ces vues ne sont pas encore dans
  le scope proto (hors périmètre post-v1, P3).
