# Teardown CoinSnap — parcours utilisateur & extraction

> **But.** Disséquer CoinSnap (concurrent que le PO trouve réussi) pour en extraire les bons
> patterns de vues et d'interactions, et décider ce qu'on porte dans notre **proto** (source de
> vérité design) puis en **prod** Android.
>
> **Méthode.** Tour complet de l'app live via `adb` (screenshots + dump UI) le 2026-06-15 sur
> Pixel 9a. App = `com.coinidentifyer.ai` (éditeur **Glority**, ceux de PictureThis / Picture
> Insect — c'est une *franchise d'identifieurs IA*, pas un studio numismatique). Version 2.7.1.
>
> ⚠️ **Posture critique.** CoinSnap est un identifieur grand public agressivement monétisé,
> pas un outil de collectionneur. Il a **mal identifié** notre test (Finlande 2€ 2005 FAO →
> "Andorra 2 euro 2015"). On copie l'**ergonomie et la densité de contenu**, PAS le modèle ML
> ni la stratégie paywall. Notre North Star reste la marketplace + le scan-first.

Screenshots commentés dans `screens/` (préfixe `sNN-`, ordre du parcours).

---

## 1. Carte du parcours (journey map)

```
LANCEMENT
  └─ Paywall plein écran "Design Your Trial" (s00)        ← interstitiel à chaque session
        └─ [X] ─→ HOME

HOME (onglet, s01/s02/s20)
  ├─ Header valeur : « € 16 · 6 Coins · 4 Issuers »        ← stat collection en hero
  ├─ 2 CTA : [Identify] (plein) + [Grading] (outline)
  ├─ Bandeau « free 7-day Premium pas encore réclamé »     ← nudge premium permanent
  ├─ Expert Picks  → pièce du jour + explainer pédago      ← contenu éditorial quotidien
  └─ Coin Talk     → articles longs (Preservation, History)← engagement hors-scan
  [bottom nav] Home · (FAB caméra) · Collection

CAPTURE (FAB caméra ou Identify/Grading, s03/s21)
  ├─ Réticule CIRCULAIRE « Focus one coin in circle »      ← single-coin, comme nous
  ├─ Shutter explicite (pas de scan continu)               ← ≠ notre doctrine QR-style
  ├─ Zoom 1,2x · flash · import galerie · slots récents
  └─ capture ─→ RÉSULTAT

RÉSULTAT D'IDENTIFICATION (IdentificationResultActivity, s05→s09)
  ├─ 2 faces CANONIQUES reconstituées (avers+revers)       ← même avec 1 seule photo donnée
  ├─ Toggle « Yours » : ta photo ↔ image catalogue         ← comparaison visuelle
  ├─ Nom + année + prix par grade « €3,63 – €5,69 · SUP »
  ├─ Carte « Get Precise Grade » (premium)
  ├─ Expert Insights : Mintage 240 000
  ├─ Supply Analysis  (paragraphe généré IA)               ← narratif rareté
  ├─ Market Demand & Value (paragraphe IA)                 ← narratif désirabilité
  ├─ Physical Features : render 3D coté (Ø, épaisseur)     ← visuel premium
  │     + table Country/Composition/Designer/Krause
  ├─ Coin Design : descriptions avers/revers + lettering
  └─ [bottom action bar] re-scan · share · + Add to Collection

AJOUT AU VAULT (bottom sheet « Collection Details », s11/s12)
  ├─ Variety · Custom set · Value(€) · Grade
  └─ + dépliable : Date Acquired · Edit Name · Photos
  └─ « Add to collection » ─→ toast « Added to My set 1 » + CTA « View collection »

COLLECTION (onglet, s16→s19)
  ├─ tabs : Summary / All / Sets
  ├─ Summary : carrousel « Your Best Coins » + badges laurier
  │     (« Rarest », « Most Valuable » par mintage/valeur)  ← gamification douce
  ├─ All    : liste à plat (holder 2 faces, grade·valeur), Sort, filtre pays, multi-select
  └─ Sets   : « Create New Set » + cartes set (cover, valeur totale, count, date)
       └─ Set detail : stats + filtre pays + Sort + Add Coin

RÉGLAGES (engrenage, AppSettingsActivity — texte seul)
  Manage Membership · Preferred Currency · Help/Suggestion ·
  « Your History » (toutes les ID passées) · Log in/Sign up (compte OPTIONNEL) · Legal
```

**Architecture de nav** : 3 zones (Home / Collection) + **FAB caméra central** — exactement le
pattern M3 BottomAppBar+FAB qu'on a déjà acté (cf. `reference_app_implem_phases`). Validation
externe de notre choix de shell.

---

## 2. Ce qu'on EXTRAIT (pépites à porter au proto)

| # | Pattern CoinSnap | Pourquoi c'est bon | Cible chez nous |
|---|---|---|---|
| E1 | **Toggle « Yours » ↔ image canonique** sur le résultat | Rassure (« est-ce bien MA pièce ? »), valorise la photo de l'user | Reveal/fiche scan : superposer capture vs avers canonique |
| E2 | **Render 3D coté avec Ø/épaisseur annotés** | Transforme une fiche technique aride en objet désirable | Fiche pièce — on a déjà un sandbox 3D (`features/dev/Coin3DSandbox`) à promouvoir |
| E3 | **Narratifs « Supply Analysis » + « Market Demand »** | Donne du *sens* à la rareté/valeur, pas juste des chiffres | On a déjà mintage + cote ; ajouter 2 paragraphes générés (LLM, on a le pipeline) |
| E4 | **Carrousel « Your Best Coins » + badges (Rarest/Most Valuable)** | Gamification douce, donne envie de revenir voir son top | Coffre : section hero « tes meilleures pièces » par rareté/valeur |
| E5 | **Header valeur collection en hero** (€ X · N coins · N issuers) | Le collectionneur veut voir son patrimoine grossir | Coffre : stat-bar en tête (on a la cote eBay/catalogue) |
| E6 | **Bottom sheet d'ajout riche mais progressive** (champs essentiels + « Add more info » dépliable) | N'effraie pas, mais permet la granularité (date, prix d'achat, set) | Flow « ajouter au coffre » post-scan |
| E7 | **Contenu éditorial quotidien** (Expert Picks + Coin Talk) | Rétention hors-scan, autorité, SEO/partage | Aligne avec notre stratégie growth contenu short-form viral (`project_mission_strategy`) |
| E8 | **« Your History »** distincte de la collection | Scanner ≠ posséder ; on garde trace des ID sans polluer le vault | Séparer historique de scans / coffre possédé |
| E9 | **Sets perso + assignation à l'ajout** | L'user organise sa collection à sa main | On a déjà les sets (DSL criteria) — exposer « custom set » côté user |

## 3. Ce qu'on NE copie PAS (anti-patterns / divergences)

| Anti-pattern | Raison |
|---|---|
| **Paywall à chaque session + nudges permanents** | Hostile ; notre modèle n'est pas l'abonnement-identifieur mais la marketplace |
| **Capture à shutter explicite** | Notre doctrine = scan continu QR-style sans bouton (`feedback_scan_ux`, `project_scan_single_coin`). On garde notre approche, mais on **reprend le réticule circulaire single-coin** qui est commun |
| **Grading « par photo »** vendu comme précis | Le grading visuel fiable depuis une photo est douteux ; CoinSnap le locke en premium justement parce que c'est du flou. On ne promet pas ce qu'on ne tient pas (R0/no-debt mental) |
| **Identification approximative présentée avec aplomb** | CoinSnap a sorti « Andorra 2015 » pour une Finlande 2005 sans signal de doute. Notre pipeline a déjà l'abstention par spread + gate denom — **garder l'honnêteté de confiance** est un différenciateur |
| **Compte/login mis en avant** | v1 reste vault local offline-first (`project_eurio_stack`) |

---

## 4. Lien avec le sujet « prod vs dev »

Rappel cadrage PO (2026-06-15) : l'irritant **n'est pas le build** (le split est déjà propre —
`buildTypes` debug/qa/release, flavor `cohortTest`, et tous les `features/dev/*` gatés par
`BuildConfig.DEBUG` dans le NavHost). L'irritant est le **design produit** : le proto ne
satisfait pas encore. Ce teardown alimente la **refonte du parcours prod** :

- Les pépites E1–E9 sont à instancier **d'abord dans le proto** (`admin/packages/proto/`, R1
  proto-first STRICT) avant tout Compose.
- Cela croise la refonte psycho déjà amorcée (`project_psychologie_app_pont`,
  scene-parity §Refonte psycho) — E4/E5/E7 sont exactement des leviers de pull éthique.

---

## 5. Prochaines décisions PO (ouvertes)

1. **Reveal scan** : on adopte le toggle « Yours ↔ canonique » (E1) ? Et le render 3D (E2) dès le reveal ou seulement en fiche détail ?
2. **Coffre** : on ajoute la stat-bar patrimoine (E5) + section « meilleures pièces » (E4) ? Quels axes de badge (rareté mintage / valeur / complétude set) ?
3. **Contenu éditorial** (E7) : in-app (comme CoinSnap) ou on le garde pour le canal short-form externe ?
4. **Narratifs IA** (E3) : on génère Supply/Demand par pièce via notre pipeline LLM, ou on s'en tient aux données dures (mintage + cote) pour rester factuel ?

> Pour creuser : 3 autres concurrents sont installés sur le device (`CoinIn`, `CoinDetect`,
> `Coin Identifier`) — un teardown comparatif est possible sur demande.
```
