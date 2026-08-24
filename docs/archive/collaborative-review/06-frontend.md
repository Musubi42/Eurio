# 06 — Front reviewer

## Périmètre

App web **minimale**, séparée du console admin, servie depuis le VPS. Pensée pour
des **non-techniques sur mobile ou desktop**. Une seule chose à faire : reviewer.

> **Proto-first ?** Non. La règle proto-first (`docs/design/_shared/parity-rules.md`
> §R1) ne concerne **que l'app Android**. Ce front est de l'outillage admin-adjacent
> → design direct avec `shared/tokens.css` + skill `frontend-design`, comme le reste
> de `admin/`. (cf. `feedback_proto_first`.)

## Écrans

### 1. Entrée / auth
- Lien `?u=Paolo42` → connexion auto, URL nettoyée.
- Sinon modale « Ton code ? ». Cf. `04-auth.md`.

### 2. Carte de review (le cœur)
Une carte à la fois, plein écran sur mobile :

```
┌──────────────────────────────┐
│           [ CROP ]           │   ← image MinIO, grande, centrée
│                              │
├──────────────────────────────┤
│  "2 € Allemagne 2008..."     │   ← listing_title (contexte)
├──────────────────────────────┤
│  Candidats (top Dino) :      │
│  [img] Belgique 2008  ✓      │   ← boutons candidats avec vignette
│  [img] France 2008           │
│  [img] Autre...              │
├──────────────────────────────┤
│  [ ❌ Pas une pièce ]  [ ⏭ Passer ] │
├──────────────────────────────┤
│            3 / 10            │   ← compteur de session
└──────────────────────────────┘
```

- **Accept** = taper un candidat (gros boutons tactiles avec vignette pour comparer).
- **Reject** = « Pas une pièce / trop floue » (→ `quality_reason`).
- **Skip** = « Passer » (je ne sais pas) → item relâché.
- Avance auto à la carte suivante après chaque action.

### 3. Félicitation (fin des 10)
```
🎉 Bien joué Paolo !
Tu as reviewé 10 pièces.  (240 au total)
   [ Encore 10 ]   [ J'arrête ]
```

## Principes UX

- **Zéro jargon** : pas de « eurio_id », « Dino sim », « lane ». Des images et des
  noms de pays/pièces.
- **Gros boutons**, tactile-friendly, une décision par écran.
- **Rapide** : pré-charger l'item suivant pendant qu'il décide.
- **Hors-ligne tolérant** : si le réseau saute, mettre en file les décisions et
  renvoyer (les 10 items du claim sont déjà chargés).
- **Tokens partagés** : couleurs/espacements via `shared/tokens.css` pour rester
  cohérent avec l'univers Eurio.

## Stack proposée

- Vue 3 + Vite (cohérent avec `admin/packages/web` et `proto`), nouveau package
  `admin/packages/review`. Build statique servi par le service review sur le VPS.
- Appelle uniquement les routes du **service review** (pas `ml/serving`, pas
  Supabase). Cf. `07-reconciliation.md` pour les routes.
