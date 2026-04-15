# Phase 5 — Profil + gamification

> **Objectif** : construire la destination `Profil` avec les mécaniques de gamification "identitaires" (grade, streak, badges, stats). Le Coffre porte déjà la progression mécanique (X/Y par set, % pays) ; le Profil porte la narration long-terme (qui je suis dans l'app, où je suis dans ma progression globale).

## Dépendances

- Phase 0 à 4 complètes (toute la donnée nécessaire existe)
- Le streak existe déjà depuis Phase 1 (simple compteur) — Phase 5 le hydrate réellement

## Livrables

### 1. Écran `Profil`

`ProfileScreen.kt`, organisation verticale (scroll) :

**Section 1 — Identité**
- Avatar placeholder (grosse circle, initiales ou icône)
- Grade actuel (e.g., "Collectionneur", "Numismate", "Expert") + badge coloré
- Progress bar vers le grade suivant (`X pièces jusqu'à Y`)

**Section 2 — Streak héro**
- Grosse flamme 🔥 + nombre, typo bold, couleur accent
- Sous-titre "Jours consécutifs · meilleur streak : N jours"
- Explication "Scanne au moins une pièce chaque jour pour entretenir ton streak" (collapsable info)

**Section 3 — Stats clés** (grille 2×2 ou row de cards)
- Total pièces scannées
- Pays touchés (X/21)
- Sets complétés (X/N)
- Pièces uniques possédées

**Section 4 — Badges**
- **Débloqués** : row horizontale scrollable, chaque badge = icône + nom + date
- **Prochains à débloquer** (next-goal pattern) : list de 3 cards, chacune avec :
  - Icône badge (grisée)
  - Nom badge
  - Condition de déblocage
  - Progress bar (e.g., "8/10 pièces belges")
  - Tap → explique en détail

**Section 5 — Activité récente** (timeline)
- Derniers 10 événements : scan d'une nouvelle pièce, complétion d'un set, badge débloqué
- Tap sur un item → contexte (coin detail / set detail / badge detail)

**Section 6 — Réglages** (liste d'items)
- Langue (FR/EN)
- Mode debug (toggle manuel, en plus du 7-taps)
- Export coffre (JSON/CSV, futur)
- À propos (version, credits, licences open source)
- Reset data (dangereux, confirmation forte, dev only)

### 2. Logique Grade

Table de grades définie en dur (ou dans une `GradeEntity` de config) :

| Grade | Seuil |
|---|---|
| Débutant | 0 pièces |
| Amateur | 5 pièces |
| Collectionneur | 25 pièces |
| Numismate | 50 pièces |
| Expert | 100 pièces |
| Maître | 200 pièces |

Calcul à chaque changement du vault (observer le count), le grade courant se met à jour automatiquement. Transition de grade → déclenche un événement "grade-up" que l'on peut afficher avec un toast ou une modale (v1 : toast simple).

### 3. Badges v1 — catalogue minimal

Définir ~10-15 badges pour démarrer, tous codés en dur dans `domain/badges/BadgeDefinitions.kt` ou chargés depuis le bootstrap :

**Exemples** :
- **Premier scan** : ajouter sa 1ère pièce
- **Tour de France** : toutes les commémos françaises d'une année
- **Eurozone complète** : au moins une pièce de chaque pays eurozone
- **Streak 7** : 7 jours consécutifs
- **Streak 30** : 30 jours consécutifs
- **Série complète** : compléter une série complète (via `coin_series`)
- **10 / 50 / 100 pièces** : seuils de possession
- **Chasseur de rares** : posséder une pièce avec `mintage < 500000`

**Règle de déblocage** : chaque badge a un predicate `(VaultState) -> Boolean`. Recalcul à chaque changement du vault, persistance `unlocked_at` en local.

**Recommandation** : stocker les definitions en Kotlin (type-safe, pas de JSON à parser), persister `unlocked_at` dans une `BadgeEntity(badgeId, unlockedAt)` en Room.

### 4. Streak logic (hydratation réelle)

En Phase 1 on a posé le stub (`CatalogMetaEntity` clés `streak_*`). Phase 5 hydrate la vraie logique :

- Sur chaque `Scan.Accepted` → `StreakRepository.tick()` :
  - Si `last_day == today` → no-op
  - Si `last_day == yesterday` → `count++`, `last_day = today`, `grace_used = false`
  - Si `last_day == today - 2` ET `!grace_used` → `count` inchangé (grace), `last_day = today`, `grace_used = true`
  - Sinon → `count = 1`, `last_day = today`, `grace_used = false`
- `best_streak` maintenu en parallèle (max all time)
- Observable via Flow → top bar scan + section Profil

### 5. Repository

`ProfileRepository` :
- `observeProfileState(): Flow<ProfileState>` — combine streak, grade, stats, badges via `combine()`
- `observeRecentActivity(limit: Int): Flow<List<ActivityEntry>>` — query unifiée de la timeline
- `observeBadges(): Flow<BadgeState>` (unlocked + next candidates)

### 6. Recalcul badges

Au démarrage de l'app + après chaque modification du vault : parcourir les badges non débloqués, évaluer leur predicate, marquer débloqués ceux qui le sont. Opération rapide (10-15 badges × query simple = milliseconde).

Évite les N+1 : batcher les lectures de base (count pays, count sets, etc.) une fois puis évaluer tous les predicates sur ce state pré-calculé.

### 7. Toast "Badge débloqué"

Hors destination Profil aussi — à chaque déblocage, un Snackbar "Badge débloqué : {nom}" apparaît (au-dessus de la bottom bar, ne bloque pas le scan). Tap → navigue vers Profil scrollé sur la section badges.

## Acceptance criteria

- [ ] Profil s'ouvre et affiche toutes les sections sans crash
- [ ] Grade calculé correctement selon le vault count
- [ ] Streak affiché, incrémenté à chaque scan accepté, grace period fonctionnelle
- [ ] Stats à jour (pays, sets complétés, total scans)
- [ ] Au moins 10 badges définis, débloqués correctement selon les conditions
- [ ] Badges "prochains à débloquer" affichent progress bar live
- [ ] Timeline activité récente affiche les derniers événements
- [ ] Transition de grade ou déblocage badge → toast approprié
- [ ] Réglages langue et debug mode fonctionnent
- [ ] Streak partagé entre Profil et top bar Scan (même valeur, flow unique)

## Risques / questions ouvertes

- **Activité récente — source d'événements** : il n'existe pas de table `events` dans le schéma. Deux options : (a) créer une `ActivityEntity` alimentée à chaque ajout vault/badge/set, (b) reconstruire la timeline à la volée depuis les timestamps des `vault_entries` + `badge.unlocked_at` + `set.completed_at`. **Reco** : option (b) pour v1, suffisant tant que l'activité reste dérivable des autres tables. Option (a) si on veut stocker des événements "anonymes" (e.g. "a ouvert l'app", "a fait un scan rejeté").
- **Badges = domain model ou entity séparée** : les definitions en Kotlin (type-safe), le runtime state en Room (badge_id + unlocked_at). Cette séparation permet d'ajouter/renommer des badges sans migration Room.
- **Calcul badges à chaque changement** : potentiellement couteux si le catalogue grandit à des milliers. Pour v1 (10-15 badges, 500 coins max), aucun problème. Si ça devient un goulot, passer à un trigger Room ou un job WorkManager async.
- **i18n des noms/descriptions de grades/badges** : clés `name_fr`, `name_en` dans les definitions. Langue par défaut FR.
- **Reset data** : doit vider Room + re-bootstrapper depuis le snapshot. Très utile en dev, à garder dans les réglages avec warning clair.

## Docs de référence

- `docs/design/profile/` — specs
- `docs/app-implem-phases/research-01-scan-collect-apps.md` — rationale Duolingo streak, Untappd badges, next-goal
- `docs/app-implem-phases/research-02-nav-patterns.md` — position profil dans la nav
