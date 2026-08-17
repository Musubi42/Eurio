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

| Action | Description | Tier |
|---|---|---|
| `status` | Statut du repo (branche, changements, derniers commits) | `auto` |
| `typecheck` | Typecheck du front admin (vue-tsc) | `auto` |
| `secrets-check` | Secrets sops déchiffrables et bien formés | `auto` |
| `tokens-check` | Design tokens générés à jour (garde R2) | `auto` |
| `build-front` | Build du front admin (typecheck + vite build) | `auto` |
| `ml-tests` | Suite ML **ciblée** (lab, écritures, promotion, bake) | `auto` |
| `stack-status` | Quels services locaux écoutent — `up`/`down` seulement | `auto` |
| `canonical-status` | Le canonique VPS répond-il, et combien de routes sert-il | `auto` |
| `replica-freshness` | Âge du dernier pull de la réplique locale | `auto` |

Toutes en `tier: auto` (lecture/vérification/build, rien de destructif ni de
publiant — pas de déploiement Vercel ici, la prod Eurio tourne sur le VPS et se
déploie via son propre process infra, hors du driver v1).

**Les commandes passent par `go-task`, jamais `task`** (CLAUDE.md
§Interdictions). Les deux résolvent au même binaire dans le devShell, mais la
convention du repo fait foi.

### Deux nuances qui ont failli faire déraper le principe méta

- **`ml-tests` ne lance PAS toute la suite** — il n'existe pas de tâche pour ça,
  et la suite complète a des échecs pré-existants hors-scope. L'action cible les
  fichiers du flux lab/promotion (cf. `eurio-verify`). Une action qui rendrait
  systématiquement rouge ne serait pas un check, ce serait du bruit.
- **`canonical-status` sonde l'`openapi.json`, pas `/health`** — qui n'existe pas
  au canonique (404). Elle rend un **nombre de routes servies**, pas leur
  contenu : c'est du méta (le service est-il debout et complet), pas de la donnée
  métier. La frontière est là, et elle est fine : « 125 routes servies » est du
  statut ; « 6918 items en file de review » n'en serait pas.

⚠️ **Une action se livre exécutée.** Les quatre ci-dessus ont été lancées telles
qu'écrites avant d'être commitées. Une action non testée est un piège posé à
quelqu'un qui vous fait confiance.

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
