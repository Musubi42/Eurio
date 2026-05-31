# Mission — App de collection

> Index : [`README.md`](./README.md) · Stratégie : [`product-strategy.md`](./product-strategy.md)

## Objectif

La **boucle produit** en Kotlin/Compose M3 : `scan → coffre → sets → carte eurozone →
profil`. Transformer l'identification d'une pièce en **collection et jeu** — c'est ce qui
crée la rétention et porte tous les paliers de valeur.

## Acquis

- MainActivity scan fonctionnelle ; prototype HTML de référence (`docs/design/prototype/`).
- **14 décisions UX actées** (nav M3 BottomAppBar + FAB centerDocked, scan = écran d'accueil,
  coffre 3 sous-vues, carte eurozone, gamification Duolingo-like, Room dès v1…).
- Plan en 6 phases (0→5).

## Reste à faire (phases — détail dans `app-implem-phases/`)

| Phase | Lot |
|---|---|
| 0 | Fondations : nav shell + Room + bootstrap catalogue packagé |
| 1 | Scan câblé dans sa destination + card post-scan adaptive |
| 2 | Coffre — Mes pièces + fiche pièce + ajout vault |
| 3 | Coffre — Sets browser + grille silhouette |
| 4 | Coffre — **Catalogue carte eurozone** (différenciateur) |
| 5 | Profil + gamification (streak, grade, badges) |

## Dépendances souples

- **Avance en parallèle du scan** : en dev on peut câbler la boucle avec un scan imparfait
  (ou un mock). La qualité du modèle n'est pas un prérequis pour construire l'UX.
- **Proto-first (R1)** : tout nouveau visuel passe d'abord par le prototype HTML.
- La carte/sets (P0) préparent le terrain pour Valorisation (cote dans la fiche/coffre) et
  Croissance (carte partageable, contenu).

## Done quand

App multi-écrans utilisable, boucle scan→coffre→sets→carte→profil complète et fière à montrer
(la qualité visuelle nourrit aussi la growth).

## Détail / exécution

`docs/app-implem-phases/` (phases 0-5 + recherches), `docs/design/`.
Memories : `reference_app_implem_phases`, `feedback_scan_ux`, `feedback_proto_first`.
