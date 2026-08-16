---
name: eurio-driver
description: Actions méta du projet Eurio exposées à musu-os — statut, checks, build. À consulter pour savoir ce que le projet sait faire et comment le piloter.
---

# Driver Eurio

Le fichier `actions.yml` à la racine de ce repo est le **driver** d'Eurio pour
musu-os (l'agentic OS de Raphaël, `~/Documents/Musubi42/musu-os`). C'est
l'interface méta du projet : ce que n'importe quelle intelligence (le gateway
du Command Center, une session Claude Code sur l'OS, une session Claude Code
ouverte ici même) peut déclencher sans relire tout le code.

## Principe — le driver reste méta (« principe Photoshop »)

Windows sait lancer Photoshop, connaître son statut, l'éteindre — il ne sait
pas où en est ton calque alpha. Pareil ici : le driver expose statut, checks,
builds. Il n'expose **jamais** de donnée métier d'Eurio (liste des pièces 2 €,
scrap eBay, photos par classe, contenu de `eurio.db`…). Cette donnée vit dans
le front d'Eurio lui-même, pas dans l'OS.

## Actions exposées

| Action | Description | Tier | Commande |
|---|---|---|---|
| `status` | Statut du repo (branche, changements, derniers commits) | `auto` | `git status --short --branch && git log --oneline -5` |
| `typecheck` | Typecheck du front admin (vue-tsc) | `auto` | `task front:typecheck` |
| `secrets-check` | Vérifie que les secrets sops sont déchiffrables et bien formés | `auto` | `task secrets:check` |
| `tokens-check` | Vérifie que les design tokens générés sont à jour (CI guard) | `auto` | `task tokens:check` |
| `build-front` | Build du front admin (typecheck + vite build) | `auto` | `task front:build` |

Toutes en `tier: auto` (lecture/vérification/build, rien de destructif ni de
publiant — pas de déploiement Vercel ici, la prod Eurio tourne sur le VPS et se
déploie via son propre process infra, hors du driver v1).

Le gateway musu-os les expose sous le nom `eurio:<name>` (ex. `eurio:status`),
scanné depuis `syscalls/registry.yml` du repo musu-os qui référence ce repo.

## Ajouter une action

1. Éditer `actions.yml` à la racine du repo.
2. Chaque action déclare : `name`, `description`, `run` (commande shell, cwd =
   racine du repo), `tier` (obligatoire — `auto` / `confirm` / `never-remote`,
   pas de défaut implicite : mieux vaut expliciter que subir un défaut trop
   permissif ou trop restrictif).
3. Jamais de donnée métier dans la sortie d'une action — seulement du méta
   (statut, résultat de check, chemin d'artefact). Si la tentation existe
   d'exposer une donnée métier ici, c'est le signe qu'elle appartient au front
   d'Eurio, pas au driver.
4. Pas besoin de toucher au gateway ni au dashboard de l'OS — le scan est
   automatique dès que l'action est déclarée dans `actions.yml`.

## Lien avec musu-os

Le gateway (`syscalls/gateway/server.js` dans musu-os) relit
`syscalls/registry.yml` à chaque requête `/api/actions` (pas de cache
process) ; ce registre liste les repos à scanner (dont celui-ci). Pour chaque
repo listé, il charge `<repo>/actions.yml` s'il existe et expose ses actions
préfixées `<project>:`. L'exécution se fait avec `cwd` = ce repo, mêmes
mécanismes de logs/runs et de tiers que les actions locales de l'OS.
