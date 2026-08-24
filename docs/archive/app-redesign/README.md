# Refonte app — vue par vue (à partir des findings CoinSnap)

> Workspace de la refonte du **proto web (PWA)** scène par scène, avant port Android prod.
> Méthode : on retravaille **une vue à la fois**, on en discute (ce qu'on a / ce qu'on veut),
> on modifie, le PO teste sur son téléphone (PWA auto-update via `go-task proto:deploy`).
>
> Source d'inspiration : [teardown CoinSnap](../coinsnap-teardown/README.md) (parcours complet +
> screenshots). Findings distillés : [findings-coinsnap.md](./findings-coinsnap.md).
> Batch précédent (best coins, historique, etc.) : [coinsnap-teardown/PLAN.md](../coinsnap-teardown/PLAN.md).

## Mode de travail

- **1 doc markdown par vue** dans `views/` : état actuel → ce qui marche → ce qui cloche → cible → décisions.
- On **discute** la vue avant de coder (pas de code sans accord sur la cible).
- Claude peut lancer `go-task proto:dev` et **ouvrir la PWA en local (Chrome)** pour voir les
  animations en direct → on regarde le même écran.
- Déploiement audit : `go-task proto:deploy` → https://eurio-proto.vercel.app (PWA auto-update).
- Doctrines : R1 proto-first, R2 tokens, chunk-by-chunk avec audit visuel.

## Décisions transverses (shell / IA) — actées le 2026-06-15

| # | Décision | Détail |
|---|---|---|
| T1 | **Nav à 3 icônes** | Retirer l'onglet **Marché**. Bottom nav = Coffre · Scan(FAB) · Profil. Le marketplace (North Star) n'est pas abandonné — il reste en germe via les liens « où trouver » de la fiche, onglet à réintroduire plus tard. |
| T2 | **Scan = flux unifié** | Fusionner `ScanIdle` + `ScanTransition3D` + `RevealStratifie` + `CoinDetail` en **un seul flux** : scan (halo identifié) → bottom sheet qui monte → **Coin Details full page**, navbar toujours visible. Supprime des scènes. |
| T3 | **Pas de replay** | Quand la pièce est identifiée : halo + son + titre « Identifié » **une seule fois**. Tap écran = stop immédiat de la rotation + animation de fin. Plus de boucle/replay. |
| T4 | **Densité = hiérarchie** | On vise la densité **propre** de CoinSnap (info présente, pas saturée) sur la fiche — par regroupement/priorisation, pas en supprimant de l'info. |
| T5 | **Éditorial léger dans le coffre** | Le feed d'articles léger vit dans le coffre (résout la question « où loger l'éditorial C4 »). Coffre par ailleurs **allégé**. |

## État des vues

| Vue | Doc | Statut |
|---|---|---|
| Scan + reveal (cœur) | [views/scan.md](./views/scan.md) | ✅ **livré en proto** (session 1, 2026-06-15) — flux unifié `ScanReveal`, audité device. Voir [session-log.md](./session-log.md) |
| Fiche pièce (Coin Details) | [views/coin-detail.md](./views/coin-detail.md) | 📝 cadré + wireframe cible (récit gardé, toggle Yours/Réf, courbe rareté, Discord) |
| Coffre | [views/coffre.md](./views/coffre.md) | 📝 cadré (trop lourd → alléger + bande articles) |
| Profil | [views/profile.md](./views/profile.md) | ⏳ à faire |
| Onboarding | — | ⏳ à faire |

> Méthode rappelée par le PO : **chaque chose a son poids et se discute** (pas « 3 décisions → tout
> coder »). On valide vue par vue, wireframe/flow à l'appui, le PO teste sur tel. On ne discute pas
> 15 ans, mais on est d'accord avant de coder.
