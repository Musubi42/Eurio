# Eurio Admin

Interface d'administration pour les sets d'achievement et le référentiel éditorial.

## Prérequis

Dev shell Nix actif (`direnv allow` depuis la racine du repo). Fournit Node 22 + pnpm.

## Secrets

Créer un fichier `.envrc` à la racine du repo (déjà dans `.gitignore`) :

```bash
# .envrc
export VITE_SUPABASE_URL=https://<project>.supabase.co
export VITE_SUPABASE_ANON_KEY=eyJhbGci...

# Puis :
direnv allow
```

Pas de `.env` file — Vite lit `VITE_*` depuis l'environnement shell.

## Démarrage

```bash
cd admin
pnpm install
pnpm dev          # → http://localhost:5173
```

## Ajouter des composants shadcn-vue

Les composants vivent dans `src/shared/ui/` (ownership local, pas de dépendance).

```bash
cd admin
pnpm dlx shadcn-vue@latest add button
pnpm dlx shadcn-vue@latest add table input dialog badge
```

## Ajouter un nouveau domaine (ex: marketplace)

1. Créer `src/features/marketplace/pages/MarketplacePage.vue`
2. Ajouter une entrée dans `src/app/nav.ts`
3. Ajouter la route dans `src/app/router.ts`

## Structure

```
src/
├── app/           router, main, App.vue, nav.ts
├── features/
│   ├── auth/      login magic link
│   ├── sets/      CRUD sets (cœur du MVP)
│   ├── coins/     lecture seule du référentiel
│   └── audit/     consultation sets_audit
└── shared/
    ├── supabase/  client + types TypeScript
    ├── ui/        composants shadcn-vue (ownership local)
    └── utils/     cn() helper
```

## Rôle admin

Pour activer le rôle admin sur ton compte Supabase :

```sql
UPDATE auth.users
SET raw_app_meta_data = raw_app_meta_data || '{"role": "admin"}'::jsonb
WHERE email = 'raphaelthi59@gmail.com';
```

À exécuter une seule fois via le Supabase Dashboard → SQL Editor.
