# Recherche — Bottom nav + FAB central : patterns et évolution 3→4 onglets

> Consigné le 2026-04-15. Étude des patterns de navigation pour l'app Android Eurio avec pour contrainte : scan = action héro, nav toujours visible, scalable du jour 1 (3 onglets) vers un futur avec Marketplace (4 onglets).

## Question 1 — Elevated center action : patterns et pièges

### Guidance Material 3

M3 a deux composants pertinents :
1. **Navigation bar** (3–5 destinations, flat, poids égal) — ce que la plupart des apps appellent "tabs".
2. **Bottom app bar** — supporte explicitement un FAB docké, avec `FAB_ALIGNMENT_MODE_CENTER` comme mode primaire. La barre a une forme "cradle" (encoche) qui héberge le FAB.

M3 traite le FAB comme **un composant séparé ancré à la barre**, pas comme un onglet stylé plus gros. C'est important : le FAB représente l'action primaire de l'écran, la barre héberge la nav + actions secondaires. Material 3 Expressive (I/O 2025) a formalisé ça davantage avec le FAB Menu pattern et les floating toolbars.

**Piège clé des docs M3 elles-mêmes** : _"si vous utilisez un FAB vers le bas de l'écran, comprenez que la présence de la bottom navigation peut nuire à sa proéminence. Le bouton ne serait alors qu'à 16dp d'un élément navigationnel proéminent."_ Traduction : pick one hierarchy (bar+FAB) et commit, ne mets pas un FAB flottant au-dessus d'une nav bar qui a aussi un center tab proéminent — tu obtiens **deux héros qui se battent**.

### Exemples réels

- **Instagram** — *Pas un center élevé.* Tous les icônes ont un poids égal ; le "+" a bougé en top-right en 2020 quand Reels a pris le centre, et a shifté encore depuis. Les données Instagram ont apparemment montré que la consommation bat la proéminence de la création, donc ils ont de-emphase l'action creation. **Leçon inverse pour Eurio** : si scan *est* le héros, ne le cache pas.

- **TikTok** — "+" central est un fat pill button, coloré (split rouge/cyan), clairement plus grand que ses siblings. Techniquement c'est un tab stylé, pas un FAB flottant — il est *dans* la barre, pas au-dessus. Pas d'élévation/shadow, juste un bold shape+color contrast. Tap → bump tactile.

- **Snapchat** — Shutter camera est toute la zone centrale, circulaire, grande, ouvre la caméra en modal plutôt qu'en tab. C'est effectivement un mode switch dédié, pas de la nav.

- **Strava** — Classic elevated center "Record", circulaire, orange, sit *au-dessus* de la barre avec shadow. **Deux failures réelles remontés en case study** : (a) users hittent Record par accident en essayant de scroll le feed ou atteindre profil, (b) icon inconsistency (cercle outside → play triangle inside). **Leçon** : un elevated center veut dire wider tap target que tu crois, spec des safe zones généreuses autour des onglets voisins.

- **Shazam** — Bouton pulsatile animé comme action primaire, pas strictement bottom-nav mais même idée ergonomique : le mouvement est l'affordance, ripples au tap confirment l'état d'écoute.

- **Vivino** — Slimmed à 3 actions ; scan vit comme un icon caméra **dans** la barre, pas élevé. Ils ont choisi de pas partir FAB-style.

### Consensus visuel pour un vrai elevated center

- Circulaire ou squircle, **56–64dp** (vs 24dp des icônes onglet)
- Couleur brand solide
- **Élévation 6–8dp** avec shadow
- Sit **8–12dp au-dessus de la baseline** de la barre pour "break the plane" visuellement
- **Haptics** : light impact sur press-down, medium sur action trigger
- **Animation** : scale 0.92 sur press, spring back ; pulse optionnel à idle sur Home pour enseigner l'affordance (trick Shazam)

## Question 2 — Scaler 3→4 onglets sans casser la symétrie

**Le problème** : un elevated center marche avec des **counts impairs** (3 ou 5). Ajouter un 4ème onglet force soit (a) un center asymétrique, (b) démoter scan à un onglet régulier, (c) remplir un 5ème slot.

### Stratégie A — Sauter direct à 5 slots, réserver un
Plan `Coffre | [slot] | Scan | [slot] | Profil`. Aujourd'hui remplir `[slot]` avec qqch d'utile (e.g., "Découvrir" = catalogue browse, ou shortcut Series qui est vraiment une sous-surface de Coffre). Quand Marketplace ship, un slot devient Marketplace.
- ✅ Pas de redesign plus tard, symétrie préservée.
- ❌ Faut trouver une vraie 4ème destination aujourd'hui — filler tabs est un antipattern connu.

### Stratégie B — Garder 3 onglets, pousser Marketplace hors-nav
Options : card persistante sur home Coffre, icon top-app-bar, modal sheet triggerée depuis Profil. Strava, Shazam, plein d'apps fitness/utility font exactement ça — les features secondaires vivent *dans* les onglets primaires, pas dans la barre.
- ✅ Nav reste clean, scan-hero reste unambigu pour toujours.
- ❌ Discoverabilité marketplace dépend de où tu places l'entry point ; nécessite de la réflexion.

### Stratégie C — 4 onglets avec scan en FAB flottant *au-dessus* de la barre
`Coffre | Vault-sub | Profil | Marketplace` avec scan en FAB circulaire truly detached flottant *au-dessus* de la couture centrale de la barre. Le FAB n'est pas un onglet ; il est ancré à `FloatingActionButtonLocation.centerDocked` au-dessus d'une barre notched. **C'est le pattern canonique M3 BottomAppBar+FAB.**
- ✅ Scale proprement de 2 à 4+ bar-items pendant que scan reste héro.
- ✅ Avec 4 items, le FAB sit au-dessus de la couture entre items 2 et 3, ce qui **fonctionne visuellement** (la notch *est supposée* être centrée et les items split 2/2). C'est comme ça que la plupart des apps prod utilisant ce pattern gèrent les bar-counts pairs.

### L'antipattern "More" tab

Marche uniquement quand les items leftover sont low-frequency (type Samsung settings dump). Fail dur si l'item caché est engagement-critique — **Marketplace pourrait être revenue-critique**, donc **ne pas** le burry derrière "More".

## Recommandation pour Eurio

**Go with Strategy C: Material 3 BottomAppBar + centerDocked FAB from day one.**

### Rationale

1. C'est le pattern canonique M3, battle-tested, explicitement designé pour "one hero action + navigation".
2. Il **découple** scan (FAB, toujours center, toujours élevé, toujours héro) du nombre d'onglets. Aujourd'hui tu ship `Coffre | FAB(Scan) | Profil` avec barre 2-items notched. Demain tu ship `Coffre | Series | FAB(Scan) | Marketplace | Profil` avec barre 4-items notched — **le rôle visuel du FAB ne change jamais**, pas de relearning user.
3. Évite le problème de tap accidentel Strava : le FAB est physiquement séparé (élevé, shadowed, circulaire) de la tab row, donc les thumb misses atterrissent sur un tab, pas sur Scan. **Scan est la tap la plus coûteuse d'Eurio** (ouvre caméra, bouffe batterie), cette séparation compte.
4. Fit la mémoire "QR-scanner-style auto" — le FAB est l'entry point non-ambigu vers le mode scan continu, zéro ambiguïté avec la nav.

### Spec concrète à aligner

- **FAB** : 64dp circulaire, accent brand, élévation 8dp, `centerDocked` au-dessus d'un `BottomAppBar` notched de 56dp.
- **Onglets** : 2 aujourd'hui (Coffre gauche, Profil droite), 4 plus tard (Coffre | Series | Marketplace | Profil) — la notch reste dead-center parce que `CircularNotchedRectangle` auto-centre indépendamment du count.
- **Haptics** : `HapticFeedbackConstants.CONFIRM` sur FAB press ; `CONTEXT_CLICK` sur tab switches.
- **Nav bar toujours visible**, pas de `hideOnScroll` — matche le requirement "toujours atteignable".
- **Pulse animation** sur FAB sur first-run / empty-vault uniquement (trick Shazam) pour enseigner l'affordance, puis stop.

### À ne pas faire

- Ship Scan comme un onglet stylé plus gros (style TikTok) — ça couple les visuals héros au tab count et casse à l'arrivée de Marketplace.
- Utiliser un onglet "More" pour Marketplace.
- Mettre un FAB flottant **ET** un center tab proéminent — c'est le "two heroes" pitfall contre lequel M3 warn explicitement.

## Sources

**Material 3 / Android :**
- [Bottom app bar — Material Design 3](https://m3.material.io/components/bottom-app-bar/guidelines)
- [Navigation bar — Material Design 3](https://m3.material.io/components/navigation-bar/guidelines)
- [FAB — Material Design 3](https://m3.material.io/components/floating-action-button/guidelines)
- [BottomAppBar API reference](https://developer.android.com/reference/com/google/android/material/bottomappbar/BottomAppBar)
- [material-components-android BottomAppBar docs](https://github.com/material-components/material-components-android/blob/master/docs/components/BottomAppBar.md)
- [Discovering Material 3 Expressive — FAB Menu (Medium)](https://medium.com/@renaud.mathieu/discovering-material-3-expressive-fab-menu-ecfae766a946)
- [Google updates Material 3 with FAB-integrated bottom app bar (9to5Google)](https://9to5google.com/2022/05/11/material-3-io-2022/)
- [Material 3 Expressive floating toolbars (9to5Google, 2025)](https://9to5google.com/2025/05/18/material-3-expressive-toolbars/)
- [Layouts and navigation patterns — Android Developers](https://developer.android.com/design/ui/mobile/guides/layout-and-content/layout-and-nav-patterns)

**Case studies apps réelles :**
- [Instagram navigation redesign case study](https://medium.com/product-powerhouse/instagrams-strategic-navigation-redesign-product-case-study-b412ffddeb30)
- [Instagram revamps bottom bar (Android Police)](https://www.androidpolice.com/2020/11/13/instagram-revamps-its-bottom-bar-putting-reels-and-shop-front-and-center/)
- [Design Critique: Strava for iPhone (IXD Pratt)](https://ixd.prattsi.org/2023/01/design-critique-strava-for-iphone/)
- [Strava redesign case study](https://medium.com/design-bootcamp/ux-case-study-strava-redesign-from-a-runners-perspective-4f0107c8e421)
- [Design Critique: Shazam](https://ixd.prattsi.org/2020/09/design-critique-shazam-mobile-app/)
- [Vivino's new look / navigation](https://www.vivino.com/en/articles/updated-home)

**Pattern writeups :**
- [Bottom Navigation on Android — FAQs & practices (Raveesh Bhalla)](https://medium.com/@raveeshbhalla/bottom-navigation-on-android-faqs-suggested-practices-141f4975be4)
- [When Bottom Navigation Fails (UXMisfit)](https://uxmisfit.com/2017/07/09/when-bottom-navigation-fails-revealing-the-pain-points/)
- [Bottom Tab Bar Navigation Best Practices (UX Planet)](https://uxplanet.org/bottom-tab-bar-navigation-design-best-practices-48d46a3b0c36)
- [Flutter BottomAppBar + FAB guide (Code with Andrea)](https://codewithandrea.com/articles/bottom-bar-navigation-with-fab/)
