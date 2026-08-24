# Vue Fiche pièce (Coin Details)

> 🟢 **Refonte livrée (session 6, 2026-06-15), non committé.** Voir `../session-log.md`.
> **Patte graphique unifiée** : `/coin/:id` adopte le **sombre immersif** du résultat de scan, rendu CANONIQUE sur le corps partagé `CoinDetailBody` (overrides `.scan-reveal-root` supprimés → 1 source de vérité, R0). Numéros lourds déjà absents.
> Livré aussi : **courbe de rareté** (tirage→percentile, en-tête, pièces rares only), **caractéristiques refaites** (pièce 3/4 FIGÉE + flèche Ø en travers + métriques color-codées cool/warm, fin du caliper à tirets + cartes redondantes), **bloc communauté Discord** (« Reste connecté »), **CTA fond solide sombre** (ne bave plus).
> **Conséquence corps partagé** : le scan reveal hérite des mêmes ajouts (rareté/caractéristiques/Discord) — cohérence voulue, à valider visuellement.
> Réservé Android (delta parity) : **toggle Yours/Référence** (Yours = photo user, inexistante en proto → proto = Référence 3D seule).
> Déféré (brainstorm) : condensation accordéon vs scroll long.
> ⚠️ Couplée à la vue Scan (le reveal pull-up débouche dessus — cf. [scan.md](./scan.md) T2). Le corps est partagé (`CoinDetailBody`).

## Ce qu'on a (état actuel) — `CoinDetail.vue`

Long scroll dense (`ctx = scan | owned | reference`) :
- Hero : image pièce + toggle **Avers/Revers** + (owned) bandeau Ajoutée/Condition/Valeur
- **Récit** immersif (carte sombre : headline + lead + 4 chapitres événement/contexte/créateurs/lieu)
- 01 Identité · 02 Valorisation (P25/P50/P75) · 03 Historique prix · 04 Projection 5 ans · 05 Sets liés · 06 **Caractéristiques** (diagramme Ø + métriques + ligne factuelle, ajouté au batch précédent) + détails/sources
- CTA sticky bas (Ajouter / Retirer)

## Ce qui cloche

- **Trop long / trop dense mal hiérarchisé** : 6 sections numérotées + récit → effet « lourd » alors que CoinSnap (plus d'info encore) paraît plus léger.
- **Bug data** : `coin.theme` parfois pollué (« 2nd map » = label de revers commun) → titre de récit moche. → **fix référentiel** eurio.db, pas proto.
- CTA sticky (`coin-detail-cta`) : fondu transparent→clair qui bave sur la carte récit sombre.

## Cible — précisée par le PO 2026-06-15

Directions **actées** :
- **On GARDE le récit** (notre signature, CoinSnap ne l'a pas). Travail = **comment on superpose/condense les sections** autour, à brainstormer ensemble (pas couper).
- **Hiérarchie condensée façon CoinSnap** : info présente mais groupée, aérée, sans numéros lourds (01/02/03…).
- **Toggle Yours / Référence** (on récupère leur pattern, bien fait) : **Référence = notre modèle 3D** (interactif), **Yours = la photo de l'utilisateur**.
- **Courbe de rareté** : si la pièce est rare, afficher une petite **courbe de rareté** (pattern CoinSnap apprécié). À distinguer de la courbe de cote/prix.
- **Lien communauté en bas** : bloc « Reste connecté » → **Discord** (CoinSnap a Facebook ; nous Discord pour créer la communauté).

### Wireframe cible (à valider, pas figé)

```
┌─────────────────────────────┐
│  Luxembourg · 2022           │
│  ╭───────╮   [ Yours | Réf ] │  ← Réf = 3D interactif · Yours = photo
│  (  3D    )                  │
│  ╰───────╯                   │
│  3,79 €        ▁▂▃▅▇ Rare    │  ← valeur + COURBE DE RARETÉ
│ ─────────────────────────────│
│  ◆ Le récit (immersif, gardé)│  ← notre signature, condensé/superposé
│  ◆ Caractéristiques (Ø, coté)│
│  ◆ Cote & historique (repli) │
│  ◆ Sets liés                 │
│ ─────────────────────────────│
│   Reste connecté → Discord   │  ← bloc communauté
│  [ + Ajouter au coffre ]     │  ← CTA (fond solide, ne bave plus)
└─────────────────────────────┘
```

## Reste à trancher (étape par étape)

1. **Layering du récit** : comment il s'imbrique avec les sections data (au-dessus ? entrelacé ? replié ?). → brainstorm dédié.
2. **Ordre/priorité** des blocs sous le hero.
3. **Courbe de rareté** : source de la donnée (mintage → percentile ? cote/face ?) + quand l'afficher (seuil de rareté).
4. **Toggle Yours en proto** : « Yours » = vraie photo, inexistant en proto → mock ou réservé Android (cf. [scan.md](./scan.md)).
5. **Repliables** (accordéon) vs scroll long.
6. Fusion avec le reveal (T2) : cette fiche EST l'état « plein » du sheet de scan.

## Findings CoinSnap (structure de leur fiche, à s'inspirer)

2 faces → prix par grade → « get precise grade » → mintage → Supply/Demand → **Physical Features (diagramme coté)** → table (pays/composition/designer) → Coin Design (avers/revers + lettering) → **« Stay Connected » (communauté)**. Tout aéré, sectionné, sans numéros lourds. **+ courbe de rareté** pour les pièces rares.
