# App Android — Phases d'implémentation

> Planification du chantier "câbler l'app Android autour du prototype, du scan, des sets et du catalogue". Session du 2026-04-15.
>
> Ces docs sont le **plan de travail** pour la Phase 1 produit (passage du MainActivity mono-écran scan à une vraie app multi-écrans). Elles référencent les docs design existantes dans `docs/design/` sans les dupliquer.

## État de départ

- `app-android/` = MainActivity unique, pipeline scan YOLO+Hough+ArcFace+consensus fonctionnelle (voir `docs/research/detection-pipeline-unified.md`), Supabase câblé pour fetch un coin par `eurio_id`.
- Pas de navigation, pas de vault local, pas de vues sets/coins, pas de gamification.
- Prototype HTML fonctionnel dans `docs/design/prototype/` (4 onglets, scenes, router hash-based) — référence UX.
- Schéma Supabase riche : `coins`, `coin_series`, `sets`, `set_members`, `coin_embeddings` (voir `supabase/migrations/20260415_cleanup_and_coin_series.sql`).
- Admin Vue (`admin/`) = référence d'implémentation pour la gestion coins/sets côté web.

## Décisions UX actées (2026-04-15)

| # | Décision | Rationale |
|---|---|---|
| 1 | **Navigation Material 3** : `BottomAppBar` avec **FAB `centerDocked`** pour le scan. 2 items aujourd'hui (`Coffre`, `Profil`), FAB central scalable à 4 items plus tard (+`Series`, +`Marketplace`) sans réorganisation visuelle. | Pattern canonique M3. Découple la hero-action du nombre d'onglets. Évite le problème Strava de tap accidentel (FAB physiquement détaché). |
| 2 | **Nav toujours visible**, pas de scroll-hide. | Accessibilité, cohérence avec le proto. |
| 3 | **Scan = écran d'accueil** de l'app (viewfinder plein écran avec bottom bar en overlay). | Cohérent avec la mémoire `feedback_scan_ux` (QR-scanner style). Shazam/CoinSnap convergent là-dessus. |
| 4 | **Coffre = 3 sous-vues** via segmented control : `Mes pièces`, `Sets`, `Catalogue`. | Les 3 surfaces (vault perso / sets structurés / catalogue complet) vivent au même endroit sans être fusionnées (pattern Vivino/Pocket/CoinSnap). |
| 5 | **Catalogue = carte eurozone interactive** comme vue par défaut (21 pays, fill par % owned, drill-down par pays). | Axe de progression unique au domaine numismatique. CoinSnap le fait avec le monde ; nous on l'a naturellement avec l'eurozone. Différenciateur fort. |
| 6 | **Profil = gamification identitaire** : grade, streak (même valeur qu'au top du scan), badges, stats, réglages. | Séparation Duolingo : Coffre = progression mécanique (X/Y par set), Profil = identité long-terme. |
| 7 | **Post-scan adaptive** : si nouveau → card overlay pleine avec CTA `Détail` + `Ajouter au coffre` ; si déjà possédé → toast léger bas + scan continue. | Célébration proportionnelle à l'enjeu. Ne tue pas le flow "scan enchaîné". |
| 8 | **Streak 🔥 toujours visible** en top bar du scan. Règle v1 : 1 scan (n'importe lequel) / jour, permissive au début (grace period de 2 jours). | Retention hook #1 selon recherche (Duolingo : 7-day streak users 3.6× retained). |
| 9 | **Debug mode** scoped au scan uniquement. 7 taps sur badge version → toggles YOLO/ArcFace + bouton CAPTURE + overlay bboxes. | Déjà en place dans MainActivity, on le migre tel quel dans la destination Scan. |
| 10 | **Set completion = grille silhouette** (pas progress bar). Slot vide visible, rempli quand la pièce est scannée. Highlight visuel sur complétion v1, cérémonie audiovisuelle prévue plus tard. | Pattern Pokémon Pocket. La silhouette pointe explicitement la prochaine pièce à viser. |
| 11 | **Stockage local = Room** dès v1 (pas de JSON shortcut). | Respect de `feedback_no_debt`. Le vault sera queriable proprement dès le premier commit. |
| 12 | **Pas d'auth Supabase** pour v1. Clé API statique via `BuildConfig`. Supabase = DB de référence en lecture. | Dev only, on ne crée pas d'utilisateur cloud tant que le produit n'en a pas besoin. |
| 13 | **Bootstrap catalogue packagé dans l'APK** : chaque build release embarque un snapshot JSON du catalogue (`coins`, `sets`, `set_members`, métadonnées hors images). L'app est utilisable à l'install sans connexion. Sync delta au premier démarrage si version packagée < version Supabase. | UX install→use sans latence. Couvre le cas avion / première ouverture. |
| 14 | **Marketplace = hors v1**. Ne touche ni à la nav (prévue extensible), ni aux écrans actuels. | Priorité : boucle scan→vault→sets→progression. |

## Framework UX (résumé visuel)

```
┌─────────────────────────────┐
│ v0.1.0            🔥 7      │  ← top bar (version + streak)
│                             │
│                             │
│       VIEWFINDER            │  ← Scan plein écran par défaut
│       (caméra)              │
│                             │
│       [card detection]      │  ← overlay quand pièce détectée
│                             │
├─────────────────────────────┤
│  [Coffre]   ( 📷 )   [Profil] │  ← BottomAppBar M3 + FAB centerDocked
└─────────────────────────────┘
```

**Coffre** (3 sous-vues, segmented control en haut) :
1. **Mes pièces** — grille de ce qui est scanné, filtres (pays/année/type/valeur), tri
2. **Sets** — liste des sets, mini-silhouette + `X/Y`, drill-down = grille complète silhouette
3. **Catalogue** — carte eurozone interactive, drill-down par pays = liste avec silhouettes pour non-scannées

**Profil** :
- Grade / niveau
- Streak (même valeur qu'au top scan)
- Badges débloqués + prochains
- Stats (total scans, pays touchés, sets complétés)
- Réglages (langue, debug log, à propos)

## Phases d'implémentation

Chaque phase est un lot cohérent, testable, mergeable. Ordre = ordre de dev.

| Phase | Nom | Doc | Durée estimée |
|---|---|---|---|
| 0 | Fondations (nav shell + Room + bootstrap) | [phase-0-foundations.md](phase-0-foundations.md) | 2-3 jours |
| 1 | Scan câblé dans sa destination + card post-scan | [phase-1-scan.md](phase-1-scan.md) | 2 jours |
| 2 | Coffre — Mes pièces + Coin detail + ajout vault | [phase-2-vault.md](phase-2-vault.md) | 2-3 jours |
| 3 | Coffre — Sets browser + grille silhouette | [phase-3-sets.md](phase-3-sets.md) | 2-3 jours |
| 4 | Coffre — Catalogue + carte eurozone | [phase-4-catalog-map.md](phase-4-catalog-map.md) | 3-4 jours |
| 5 | Profil + gamification (streak, grade, badges) | [phase-5-profile-gamification.md](phase-5-profile-gamification.md) | 2-3 jours |

**Total estimé** : 13-18 jours de dev focalisé.

## Recherches consignées (session planification)

- [research-01-scan-collect-apps.md](research-01-scan-collect-apps.md) — Comparatif UX d'apps scan-centric (Vivino, Untappd, Pokémon Pocket, Shazam, CoinSnap, Duolingo)
- [research-02-nav-patterns.md](research-02-nav-patterns.md) — Material 3 BottomAppBar+FAB, patterns d'évolution 3→4 onglets

## Docs de référence à lire (design pré-existant)

| Doc | À lire avant la phase… |
|---|---|
| `docs/design/_shared/sets-architecture.md` | Phase 3 (DSL criteria, 3 kinds de sets) |
| `docs/design/_shared/data-contracts.md` | Phase 0 (schéma local Room) |
| `docs/design/_shared/offline-first.md` | Phase 0 (bootstrap + sync) |
| `docs/design/scan/README.md` | Phase 1 (flow détaillé) |
| `docs/design/scan/ml-pipeline.md` | Phase 1 (rappel pipeline) |
| `docs/design/scan/debug-overlay.md` | Phase 1 (debug mode) |
| `docs/design/vault/` | Phase 2 |
| `docs/design/coin-detail/` | Phase 2 |
| `docs/design/profile/` | Phase 5 |
| `docs/research/detection-pipeline-unified.md` | Phase 1 (état actuel pipeline) |
