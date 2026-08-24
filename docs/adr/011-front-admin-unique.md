# ADR-011 — Un seul front admin, deux cibles de build ; le lourd se grise

- **Statut** : ✅ Acceptée
- **Date** : 2026-06-29 (décision) · fusion livrée et QA navigateur validée le 2026-06-30
- **Supersède** : le split dual-front `studio-local` / `admin-vps` décidé le 2026-06-19,
  abandonné dix jours plus tard. `admin-vps` a été supprimé

## Contexte

Le navigateur **interdit** à une page servie en HTTPS (`eurio-admin.musubi.dev`) de
faire des XHR vers `http://127.0.0.1:8042` — c'est du mixed content. Or les features
lourdes d'Eurio (crops, scrape, entraînement, lab, bench) tapent précisément cette API
ML locale, qui n'existe que sur le Mac et le PC.

La première réponse (2026-06-19) a été de **couper le front en deux** : `studio-local`
riche en local avec PAT, `admin-vps` léger et hébergé avec cookie OIDC. Dix jours plus
tard, le coût était visible : deux `AppShell`, deux systèmes de nav, deux clients d'API,
deux jeux de composants — pour deux applications qui montrent **la même donnée** et
dont seule une poignée d'écrans diffère réellement.

Le mixed content interdit d'**appeler** `:8042` depuis l'hébergé. Il n'interdit pas de
**servir le même code** aux deux endroits.

## Décision

**Il n'y a qu'un front : `admin/packages/studio-local`**, servi à deux endroits via un
seul réglage de build, `VITE_DEPLOY_TARGET`.

| | `local` (défaut) | `hosted` |
|---|---|---|
| Où | Mac/PC, `pnpm dev` sur `:5173` | VPS, `https://eurio-admin.musubi.dev` |
| Auth | Bearer PAT depuis `.env.local` | Cookie OIDC posé par `eurio-api` |
| ML lourd `:8042` | actif | **grisé + notice**, jamais appelé |
| Features légères | toutes | toutes |
| Mobile | non | oui |

- `shared/api/eurio-api.ts` choisit Bearer ou cookie (`credentials:'include'`) selon
  `AUTH_MODE`, dérivé de `VITE_DEPLOY_TARGET`.
- `stores/capabilities.ts` porte `hasLocalMlApi` (baseline `deploy-target` + ping
  `:8042/health` en local).
- **Ajouter une feature lourde = deux drapeaux** : `meta: { heavy: true }` sur la route
  et `heavy: true` sur l'item de nav. `AppLayout` grise la nav et rend `LocalOnlyNotice`
  à la place. Rien d'autre à gérer.
- **Aucune feature n'est interdite par mode.** Le lourd se grise tout seul.

**La nav a deux axes orthogonaux, jamais un seul** (amendement du 2026-08-23) :
`heavy` répond à « *cette machine* peut-elle ? », `scope` répond à « *cette personne*
a-t-elle le droit ? ». Les confondre gelait des routes review hébergées dont
l'essentiel était pourtant déjà servi par le VPS.

Corollaires : plus de Vercel pour l'admin (seul `packages/proto/` y reste déployé),
et le déploiement hébergé est un nginx statique derrière Traefik (`infra/eurio-admin/`).

## Alternatives considérées

| Option | Verdict |
|---|---|
| Deux packages front (le pivot du 2026-06-19) | ❌ Deux shells, deux navs, deux clients d'API pour la même donnée. Toute feature légère s'écrit deux fois ou n'existe qu'à un endroit |
| Un tunnel / proxy HTTPS devant `:8042` | ❌ Résout le mixed content en exposant une API de calcul non authentifiée depuis Internet, ou en ajoutant une chaîne TLS locale à maintenir. Beaucoup de surface pour un problème d'affichage |
| Tout faire tourner sur le VPS | ❌ Le VPS n'a pas de GPU et pas de swap. Un batch DINO ou un entraînement OOM-kill la VM |
| Front hébergé seul, local abandonné | ❌ Le lourd est le cœur du travail quotidien du PO |

## Conséquences

**Bonnes.** Une feature légère s'écrit une fois et apparaît aux deux endroits. Le
reviewer distant et le PO en local voient littéralement la même application. La
suppression d'`admin-vps` a retiré un shell entier du dépôt.

**Mauvaises, et assumées.**

- Le bundle hébergé embarque du code qu'il n'exécutera jamais (les vues lourdes sont
  routées mais grisées). Coût mesuré négligeable, non optimisé.
- **Oublier un drapeau `heavy` produit une panne muette** : la page s'ouvre en hébergé
  et l'appel `:8042` échoue en silence côté navigateur. C'est la règle R0bis de
  `CLAUDE.md`, pas une suggestion.
- Un seul réglage de build sépare deux modes d'auth : se tromper de
  `VITE_DEPLOY_TARGET` donne un front qui n'authentifie rien.

## Voir aussi

- Règle opérationnelle : `CLAUDE.md` §R0bis
- Auth des deux modes : [ADR-010](./010-authentik-oidc-et-pat.md)
- Raisonnement du pivot puis de la fusion, conservés :
  [`../archive/auth-redesign/ARCHITECTURE.md`](../archive/auth-redesign/ARCHITECTURE.md),
  [`../archive/model-b/`](../archive/model-b/)
