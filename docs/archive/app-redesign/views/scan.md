# Vue Scan (+ reveal) — le cœur de l'app

> ✅ **LIVRÉ EN PROTO (session 1, 2026-06-15).** Scène unique `admin/packages/proto/src/scenes/scan/ScanReveal.vue`
> + `src/styles/scan-reveal.css`. Détails d'implémentation, findings et état de vérification :
> [../session-log.md](../session-log.md). Le reste du doc ci-dessous = la cible (conservée comme référence).
> ⚠️ « La vue scan » inclut en réalité **le shell nav** (navbar persistante, retrait du Marché) et le
> **reveal** — chantier couplé, pas une vue isolée.

## Ce qu'on a (état actuel) — 3 scènes séparées

1. **`ScanIdle.vue`** — pseudo-caméra + anneau-guide, auto-match après 2 s (mock ML), route vers `/scan/transition`.
2. **`ScanTransition3D.vue`** — transition diégétique 3D.
3. **`RevealStratifie.vue`** — reveal **plein écran** : héros 3D (rotation idle + drag), bottom-sheet 2 crans (peek/expanded), jalons en overlay (set/pays/légendaire) avec confetti+son, CTA « Ajouter au coffre ».
4. **`CoinDetail.vue`** — fiche pièce, scène **encore distincte** (ouverte via « Voir détails » ou depuis le coffre).

Nav : navbar **déjà rendue** pendant le scan (`meta.nav:'scan'`), chrome `dark`.

## Ce qui marche / qu'on garde (PO : « j'adore »)

- L'instant **identifié** : halo autour de la pièce fixée + **son** + titre « Identifié ».
- La pièce **3D qui tourne**, et le **tap pour la figer** + jouer l'animation de fin.
- Le **bottom-sheet** qui monte (pattern reveal pull-up déjà en place).

## Ce qui cloche

- **Replay/boucle** : l'animation se rejoue / continue. → on n'en veut pas (une fois, point).
- **Reveal = scène plein écran séparée** qui « capture » l'utilisateur : on perd la navbar / le retour scan direct.
- **Reveal ≠ fiche** : reveal et `CoinDetail` sont 2 surfaces → redondance, double maintenance.
- **4e onglet Marché** présent.

## Cible (ce qu'on veut) — précisée par le PO 2026-06-15

**Idée maîtresse** : on **supprime une étape**. La pièce identifiée et sa fiche vivent sur
**un seul écran** — la fiche n'est plus une page d'après, c'est le **bas qui remonte**. Moins de
transitions, plus direct.

Détails actés :
- Retirer le bandeau **« Match verrouillé »**. Garder juste **« Identifié »** en haut, avec la pièce.
- **Titre remonté**, collé sous la pièce (ex. « Luxembourg · 2022 »).
- Remplacer les boutons **« Rejouer / Continuer »** par le **début de la modale (handle visible)** qu'on tire vers le haut.
- **Pas de replay** : l'identification (halo + son + titre) joue **une fois**. Tap = fige la rotation + anim de fin.
- **Célébrations** (série/pays complétés, légendaire) : jouent **à l'instant de l'identification** (overlay), pas sur un écran séparé.

### Wireframe A — pièce identifiée (état « peek »)

```
┌─────────────────────────────┐
│            Identifié         │  ← label sobre (plus de « match verrouillé »)
│                              │
│           ╭───────╮          │
│          (  3D     )         │  ← pièce fixée, halo, son (1×). Tap = stop + fin.
│           ╰───────╯          │
│                              │
│       Luxembourg · 2022      │  ← titre remonté, collé sous la pièce
│        Grand-Duc Henri       │  ← sous-titre / thème
│                              │
│   ╭───────────────────────╮  │
│   │ ─────  (handle)  ───── │  │  ← début de la modale : on tire vers le haut
│   │ Valeur 3,79 € · Rare   │  │  ← peek du contenu fiche
│   ╰───────────────────────╯  │
│  [Coffre]   ( ◎ )   [Profil] │  ← navbar TOUJOURS visible (re-scan en 1 tap)
└─────────────────────────────┘
```

### Wireframe B — modale tirée (= Coin Details, plein écran)

```
┌─────────────────────────────┐
│ ─────  (handle)  ─────       │  ← on peut re-baisser
│  Luxembourg · 2022           │
│  ╭───────╮  [ Yours | Réf. ] │  ← toggle (Réf = 3D, Yours = photo)
│  (  3D    )                  │
│  Valeur 3,79 €   ▁▂▃▅ rareté │  ← courbe de rareté (cf. coin-detail.md)
│  ── Le récit ──              │
│  …sections condensées…       │
│  ── Reste connecté (Discord)─│
│  [Coffre]   ( ◎ )   [Profil] │  ← navbar persistante
└─────────────────────────────┘
```

→ La modale **EST** la Coin Details. Hypothèse de travail : **fusion** `RevealStratifie` + `CoinDetail`
en une surface (sheet à 2 crans : peek → plein). On supprime potentiellement 1-2 scènes.

## Décisions actées (2026-06-15, avec le PO)

| # | Question | Décision |
|---|---|---|
| 1 | **Fusion technique reveal↔fiche** | **Scène unique + `CoinDetailBody.vue` partagé.** Une seule scène `ScanReveal` à sheet 2 crans ; l'expanded (~92 %, au-dessus de la navbar, scrollable) monte un `CoinDetailBody.vue` extrait, que la route `/coin/:id` réutilise (ctx=owned/reference). 1 source de vérité, zéro inline dupliqué (R0). |
| 2 | **3D pendant le scan** | **Un seul objet 3D continu** : naît à l'instant « identifié » sur la surface caméra (moment diégétique aimé, tap = fige), persiste dans le peek (plus petit), rétrécit en header du sheet à l'expanded. 1 seule stage Three (perf + simplicité). |
| 3 | **Ajout au coffre** | **Auto-add + undo.** La pièce s'ajoute au coffre dès l'identification, avec toast « Annuler ». ⚠️ Prend le contre-pied de la doctrine « scanner ≠ posséder » — choix PO assumé (friction minimale, le undo couvre le faux positif). |
| 4 | **Toggle face en proto** | **Garder Avers/Revers** (réels). Yours/Référence reste différé Android (décision E1 : pas de fausse photo, R0). |

## Plan d'implémentation (chunk-by-chunk, audit visuel entre chaque)

1. **Chunk 1 — Extraction `CoinDetailBody.vue`** (refacto pur, zéro changement visuel). Sortir le corps de `CoinDetail.vue` (récit → caractéristiques) dans un composant paramétré par `ctx`. `CoinDetail.vue` devient une coquille (topbar + body + CTA). _Audit : la fiche `/coin/:id` doit être identique au pixel._
2. **Chunk 2 — Scène `ScanReveal` unifiée.** Fusionner `ScanTransition3D` + `RevealStratifie` en une scène : halo identifié (1×, pas de replay) → 3D continu → sheet 2 crans (peek → expanded). Retirer « Match verrouillé », titre remonté sous la pièce, handle visible au lieu de Rejouer/Continuer. Navbar persistante.
3. **Chunk 3 — Expanded = fiche complète.** Le cran expanded monte `<CoinDetailBody ctx="scan"/>` ; 3D en header du sheet.
4. **Chunk 4 — Auto-add + undo + célébrations.** Auto-ajout au coffre à l'identification + toast undo ; célébrations (série/pays/légendaire) en overlay à l'instant de l'ID.
5. **Chunk 5 — Câblage routes + nav 3 icônes.** Router : `/scan` → `ScanReveal` (supprimer `/scan/transition` + `/scan/reveal`) ; retirer l'onglet Marché (T1). Nettoyage des scènes mortes.

## Findings CoinSnap applicables

- Sheet pull-up vers une fiche dense et propre (leur résultat d'ID est exactement ça).
- Navbar persistante + FAB scan central (re-scan immédiat).

## Note technique

- Le scan reste un **faux-scan** (`simulateScan`) en proto ; la vraie ML est côté Android.
- Voir [[feedback_reveal_sheet_pattern]], [[feedback_celebration_overlay]], [[feedback_scan_ux]].
