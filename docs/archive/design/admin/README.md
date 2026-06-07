# Eurio Admin — site de gestion des sets et du référentiel éditorial

> **Statut : planifié v2 post-launch.** Non implémenté au 2026-04-15. Ce document pose le cadrage avant développement pour éviter qu'on se lance trop tôt ou qu'on parte dans la mauvaise direction.
>
> **Pourquoi ce doc maintenant ?** Parce que les sets sont une feature produit de premier plan (cf. [`../_shared/sets-architecture.md`](../_shared/sets-architecture.md)) et que les gérer à la main dans du JSON devient insoutenable au-delà de ~20 sets. On anticipe l'outil avant d'en avoir besoin, pour que le schéma Supabase et les conventions soient déjà cohérentes.

---

## 1. Objectif

Un site web d'administration, **séparé de l'app mobile**, qui permet à Raphaël (et éventuellement à une petite équipe éditoriale v2) de :

1. Créer / éditer / publier des sets d'achievement sans toucher au code
2. Visualiser le référentiel `coins` (lecture seule, pour valider un set)
3. Gérer les métadonnées éditoriales (traductions i18n, images, ordres d'affichage)
4. Auditer les changements (qui a fait quoi, quand)
5. Prévisualiser le rendu comme dans l'app mobile avant de publier

**Non-goal** : ce n'est pas un CMS générique, ni un outil d'analytics, ni un tableau de bord user. C'est un outil éditorial ciblé sets + référentiel éditorial.

---

## 2. Personas

| Persona | Fréquence d'usage | Besoins |
|---|---|---|
| **Raphaël (solo dev v1)** | Hebdomadaire | Rapidité, pas de friction, raccourcis clavier, peu de clics pour publier |
| **Éditeur numismate (v2 hypothétique)** | Mensuelle | Clarté, validation, preview avant publish, pas besoin de comprendre Supabase |
| **Relecteur/traducteur (v2 hypothétique)** | Ponctuelle | Accès en lecture + édition des champs i18n uniquement |

V1 = uniquement Raphaël. V2 = potentiellement les deux autres si Eurio grossit. Le modèle d'auth doit permettre cette évolution sans refonte.

---

## 3. Scope v1 admin (MVP)

### 3.1 Features in-scope

**CRUD sets**
- Liste paginée + filtres (par category, kind, active, country)
- Création structural / curated / parametric
- Édition inline des champs simples
- Soft delete (flag `active=false`) et hard delete avec confirmation

**Constructeur de critères visuel**
- Form visuel pour `criteria jsonb` : country multi-picker, year range slider, denomination checkboxes, issue_type radio, series/theme_code autocomplete
- Validation syntaxique (DSL figé, clés connues uniquement)
- Zéro édition de JSON à la main (sauf mode expert optionnel)

**Live preview du matching**
- Dès que les critères changent, query locale sur le référentiel → affichage `N pièces matchent` + grille de vignettes (reverse images)
- Sanity check immédiat avant publication
- Highlight si `expected_count` ne matche pas

**Gestion des membres (sets curés)**
- Search bar sur `coins` (par eurio_id, country, year, theme)
- Ajout / retrait par clic
- Drag-and-drop pour l'ordre d'affichage
- Compteur de membres en temps réel

**Metadata éditoriale**
- Champs i18n : `name_i18n`, `description_i18n` (4 langues fr/en/de/it)
- Option d'assistance traduction automatique (DeepL API) avec revue humaine obligatoire
- Picker icône (bibliothèque locale d'assets + upload)
- Slider `display_order`
- Dropdown `category`
- Éditeur JSON `reward`

**Validation avant publish**
- Hard checks : criteria syntaxiquement valide, aucun set vide, aucune référence cassée dans `set_members`, i18n non-vide au moins pour `fr` + `en`
- Soft warnings : `expected_count` vs `actual_count`, `display_order` conflit, dupe `id`
- Pas de publish si hard check échoue

**Publish**
- Push vers Supabase `sets` / `set_members`, bump `updated_at`
- Log dans `sets_audit` avec `before`/`after` JSONB et `actor` email
- Toast « Publié. Les clients récupèreront le nouveau set au prochain delta fetch. »
- Rollback possible via `sets_audit` (restore une ligne `before`)

**Preview « comme dans l'app »**
- Rendu fidèle du set card tel qu'il apparaîtra dans le profil Kotlin
- Iframe ou composant Vue qui reprend les tokens CSS du proto
- Important pour valider le rendu avant push (nom, icône, ordre des vignettes, pluralisations)

**Audit log**
- Vue `sets_audit` filtrée par set, par actor, par action
- Pas de rollback en v1 MVP (juste consultation)

### 3.2 Features out-of-scope v1

- Gestion des `coins` (le référentiel reste géré par le bootstrap Python `ml/`, admin en lecture seule)
- Gestion des utilisateurs de l'app
- A/B testing de sets
- Recommandations ML-assistées (« sets populaires à créer »)
- Export CSV / analytics
- Notifications
- Collaboration temps réel (un seul éditeur à la fois)

### 3.3 Features considérées v2 admin

- Édition des `coins` (patch metadata ponctuel sans re-run bootstrap complet)
- Recommandation de sets via clustering ArcFace (« ces 8 pièces ont une signature visuelle commune, créer un set ? »)
- Multilingue UI admin elle-même (v1 = français uniquement)
- Stats d'usage (« 73% des users ont complété ce set »)
- Workflow de review (brouillon → revue → publish)

---

## 4. Workflows clés

### 4.1 Créer un set structurel (ex: commémos €2 Italie)

1. Login → Dashboard sets → « Nouveau set »
2. Choisir `kind = structural`
3. Constructeur de critères : country=IT, issue_type=commemo-national → live preview affiche « 42 pièces matchent »
4. Remplir metadata : name_i18n (FR saisi, EN/DE/IT pré-remplis par DeepL, revue), category='country', display_order=150, reward={badge:'silver',xp:300}
5. Cliquer « Preview comme dans l'app » → valider le rendu
6. Cliquer « Publier » → validation → push Supabase → toast succès
7. Au prochain delta fetch mobile, le set apparaît chez les users

### 4.2 Créer un set curé (ex: Grande Chasse v2)

1. Nouveau set, `kind = curated`
2. Search bar coins : saisir « grace kelly » → trouve Monaco 2007 → ajouter
3. Répéter pour 15-20 pièces
4. Drag-reorder selon l'ordre narratif voulu
5. Metadata, preview, publier

### 4.3 Créer un set paramétrique (ex: millésime de naissance, v1)

1. Nouveau set, `kind = parametric`
2. `param_key = 'birth_year'`
3. Criteria : `year = <param>`
4. Validation : le preview n'affiche rien (pas de valeur de param en preview)
5. Option « preview avec param test » : saisir `1990` → preview affiche les pièces de 1990
6. Metadata, publier

### 4.4 Désactiver un set

1. Liste sets → filter `active=true` → sélection
2. Clic « Désactiver » → confirmation
3. `UPDATE sets SET active=false` → delta fetch → les clients arrêtent de l'afficher (mais conservent les `user_set_progress` locaux au cas où on le ré-active)

### 4.5 Rollback d'une erreur

1. `sets_audit` → filter par set_id → trouver le dernier bon état
2. Copier `before` → UPDATE manuel via table editor (v1 MVP, pas de bouton rollback)
3. v2 : bouton « Restaurer cet état » dans l'audit log

---

## 5. Stack technique

**Décidé le 2026-04-15** : **Vue 3 + shadcn-vue + TailwindCSS + Supabase + Vercel**.

| Couche | Choix | Raison |
|---|---|---|
| Framework | **Vue 3** (Composition API + `<script setup>`) | Préférence user, léger, typage Vue 3.4+ solide |
| UI kit | **shadcn-vue** ([shadcn-vue.com](https://www.shadcn-vue.com/)) | Port Vue du shadcn React, Radix Vue sous le capot, matche l'esthétique museum-card, ownership des composants (pas de dépendance lourde) |
| Styling | **TailwindCSS 3** | Cohérent avec l'écosystème shadcn, tokens partagés possibles avec le proto |
| Backend | **Supabase JS v2** | Client officiel, RLS, auth, realtime si besoin |
| Hosting | **Vercel** | Cohérent avec la préférence zéro-infra, CI/CD auto, free tier |
| Domaine | **`admin.eurio.app`** | Sous-domaine dédié (validé 2026-04-15) |
| Build | **Vite** | Natif Vue 3, HMR rapide, léger |
| Routing | **Vue Router 4** | Standard Vue |
| State | **Pinia** | Standard Vue 3 |
| Forms | **VeeValidate + Zod** | Validation des criteria JSONB typée, erreurs user-friendly |
| i18n | **Vue i18n** | Pour l'UI admin elle-même (v2, v1 FR only) |
| Icons | **Lucide Vue** | Cohérent avec shadcn-vue |

### 5.1 Pourquoi Vue plutôt que Next.js / SvelteKit

- **Vue** validé explicitement par Raphaël le 2026-04-15
- Écosystème shadcn-vue mature (2025+), ownership des composants identique à la version React
- Vite + Vue 3 = DX très proche de React, sans verrouillage framework

### 5.2 Structure de projet cible

```
eurio-admin/
├── src/
│   ├── app/
│   │   ├── router.ts
│   │   ├── App.vue
│   │   └── main.ts
│   ├── features/
│   │   ├── sets/
│   │   │   ├── pages/ (list, edit, create)
│   │   │   ├── components/ (CriteriaBuilder, MembersPicker, LivePreview, AppPreview)
│   │   │   ├── composables/ (useSets, useSetPreview)
│   │   │   └── types.ts
│   │   ├── coins/           -- lecture seule
│   │   ├── audit/
│   │   └── auth/
│   ├── shared/
│   │   ├── ui/              -- shadcn-vue components (ownership locale)
│   │   ├── supabase/
│   │   └── utils/
│   └── styles/
│       └── tokens.css       -- partagé avec le proto, copié ou lien symbolique
├── public/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

### 5.3 Partage de tokens avec le proto

Le site admin doit reprendre **exactement** les tokens CSS du proto navigable (`design/prototype/_shared/tokens.css`) pour que le « Preview comme dans l'app » soit fidèle. Deux options :

1. **Copier le fichier** au build (script `prebuild`) — simple, risque de drift
2. **Symlink ou monorepo** — cohérent, nécessite structure partagée

Recommandation : monorepo léger avec package `@eurio/design-tokens` partagé entre le proto, l'app Kotlin (via export tokens JSON), et l'admin. À trancher au moment du build effectif.

---

## 6. Auth model

### 6.1 v1 — un seul admin

- Compte Supabase unique (email de Raphaël)
- Provider : **Email + Magic Link** (Supabase Auth) — zéro password à gérer
- Custom claim `role='admin'` ajouté via Supabase Auth Hook ou manuellement en SQL
- RLS policies sur `sets` / `set_members` / `sets_audit` : écriture uniquement si `auth.jwt() ->> 'role' = 'admin'`
- Session durée : 30 jours glissants

### 6.2 v2 — petite équipe

- Ajout de rôles : `admin` (full), `editor` (sets CRUD), `translator` (champs i18n only), `viewer` (read only)
- RLS policies affinées par rôle
- UI masque les actions non-permises par rôle
- Invitation par email via Supabase Auth

### 6.3 Ce qui **n'est pas** dans le scope auth

- Pas d'OAuth Google / GitHub / autres (magic link suffit)
- Pas de 2FA v1 (à ajouter si risque réel)
- Pas de SSO entreprise

---

## 7. Déploiement

### 7.1 Domaine

`admin.eurio.app` — sous-domaine dédié, distinct de :
- `eurio.app` — site marketing / landing (futur)
- `api.eurio.app` — réservé si besoin (pas utilisé v1, Supabase direct)

DNS pointé sur Vercel, SSL auto.

### 7.2 CI/CD

- Push sur `main` du repo `eurio-admin` → Vercel deploy auto
- Previews sur branches / PRs (Vercel natif)
- Tests unitaires (Vitest) en pre-deploy hook
- Tests E2E (Playwright) optionnels, à considérer si le volume justifie

### 7.3 Environnements

| Env | Supabase project | Domaine |
|---|---|---|
| `dev` (local) | `eurio-dev` (branch Supabase) | `localhost:5173` |
| `staging` | `eurio-staging` (branch Supabase) | `admin-staging.eurio.app` |
| `prod` | `eurio-prod` | `admin.eurio.app` |

V1 MVP : dev + prod suffisent. Staging ajouté quand un éditeur externe rejoint (v2).

---

## 8. Sécurité

- **RLS strictes** sur toutes les tables écrites (`sets`, `set_members`, `sets_audit`) — cf. `sets-architecture.md` §4.4
- **Pas de service_role key côté client** — uniquement l'anon key + JWT user
- **CORS** : Vercel origin whitelist stricte
- **Audit log append-only** via policy RLS (pas de DELETE/UPDATE sur `sets_audit`)
- **Validation serveur** : trigger Postgres sur `INSERT/UPDATE sets` pour valider le DSL criteria (défense en profondeur au cas où le client a un bug)
- **Backup** : snapshots Supabase quotidiens (plan payant) ou export SQL hebdo manuel (plan free)

---

## 9. Roadmap

| Phase | Statut | Contenu | Effort estimé |
|---|---|---|---|
| **0 — Cadrage** | 🟢 Fait 2026-04-15 | Ce doc, schéma Supabase, DSL figé | 1 jour |
| **1 — Schéma** | 🔵 À faire | Migration Supabase `sets` / `set_members` / `sets_audit` + seed initial via bootstrap Python | 2 jours |
| **2 — MVP admin** | 🔵 À faire (v2 post-launch app) | Vue 3 + shadcn-vue, CRUD sets, constructeur visuel, live preview, publish | 5-7 jours |
| **3 — Preview comme-dans-l'app** | 🔵 À faire | Composant iframe/render fidèle aux tokens | 1 jour |
| **4 — Audit log** | 🔵 À faire | UI consultation, rollback v2 | 1 jour |
| **5 — Multi-rôles** | ⚪️ v2 | `editor`, `translator`, `viewer` + RLS par rôle | 2 jours |
| **6 — Recommandations ML** | ⚪️ v2 | Clustering ArcFace, suggestions de sets | TBD, post Phase 2B |

**Total MVP (phases 1-4)** : ~10 jours de travail solo, gated sur la stabilisation de l'app mobile v1.

---

## 10. Décisions figées (2026-04-15)

| # | Décision | Note |
|---|---|---|
| 1 | L'admin vit dans un repo séparé `eurio-admin`, pas dans le monorepo principal | Isolation, deploy indépendant, pas de blocage app mobile |
| 2 | Stack = Vue 3 + shadcn-vue + Tailwind + Supabase + Vercel | Validé user |
| 3 | Domaine = `admin.eurio.app` | Sous-domaine dédié |
| 4 | Auth v1 = magic link Supabase, un seul admin | Zéro password, suffisant solo |
| 5 | DSL criteria **figé** avec les clés de `sets-architecture.md` §3 | Ajouter une clé = PR coordonnée client + admin |
| 6 | Gestion des `coins` reste côté `ml/` Python, admin en lecture seule | Séparation des responsabilités |
| 7 | Pas de développement avant stabilisation de l'app mobile v1 | Priorité au core loop, admin est un outil de croissance |
| 8 | `sets_audit` append-only, rollback par restauration manuelle en v1 | UI rollback v2 |

---

## 11. Questions ouvertes / à trancher avant dev

- **Monorepo vs repos séparés pour les tokens CSS partagés** : à trancher au moment du build effectif. Impact : DX, complexité de setup.
- **Framework de test E2E** : Playwright ou Cypress ou rien v1 ? Recommandation : Playwright si volume justifie, sinon skip et s'appuyer sur tests unitaires + review manuelle.
- **Assistance traduction automatique** : DeepL (payant, bonne qualité) vs Google Translate (free tier, qualité moyenne) vs rien (saisie manuelle stricte) ? À trancher quand la v2 editorial devient réelle.
- **Preview fidèle à l'app Kotlin** : faut-il un vrai rendu JetPack Compose via un service backend, ou un composant Vue qui réplique le design système ? Recommandation : composant Vue (plus simple, acceptable visuellement si les tokens sont partagés).
- **Feature flag avant publish** : est-ce qu'on pousse directement en prod, ou on passe par un flag d'activation progressive ? Pour v1, publish direct suffit (pas d'enjeu de rollout progressif).

---

## 12. Voir aussi

- [`../_shared/sets-architecture.md`](../_shared/sets-architecture.md) — architecture canonique des sets (prérequis à lire avant ce doc)
- [`../_shared/data-contracts.md`](../_shared/data-contracts.md) — contrats data Room ↔ Supabase
- [`../../DECISIONS.md`](../../DECISIONS.md) — index des décisions projet
- [`../../roadmap.md`](../../roadmap.md) — photo instantanée fait/en-cours/à-faire

---

## Historique

- **2026-04-15** — Création du doc, brainstorm avec Raphaël. Stack Vue 3 + shadcn-vue + Vercel + Supabase + Tailwind validée. Domaine `admin.eurio.app` validé. Développement différé à v2 post-launch de l'app mobile.
