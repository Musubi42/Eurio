# Cohort capture flow — workflow utilisateur

> Comment piloter une session de capture device depuis l'admin web.
> Pour le design / les décisions techniques, voir `design.md`.

## Préalable

- ML API up : `go-task ml:api` (ou `cd ml && python -m api.server`)
- Front admin up : `cd admin/packages/web && pnpm dev`
- Téléphone branché en USB, debug ADB activé, app Eurio installée
  (`go-task -t app-android/Taskfile.yml install`)

## Workflow

### 1. Sélectionner les pièces

Ouvre `/coins`, filtre, coche les checkbox des pièces voulues. Clique
**"Nouveau cohort Lab"** dans la barre du bas.

Une modal propose deux options :
- **Créer un nouveau cohort** → pré-remplit `/lab/cohorts/new` avec ta sélection
- **Ajouter à un cohort existant** → liste des cohorts en `status='draft'`,
  ajoute la sélection au cohort choisi

### 2. Page de pilotage du cohort

Sur `/lab/cohorts/<id>`, la page est structurée en sections :

- **§1 Pièces** : liste éditable tant que le cohort est `draft`.
  ✕ pour retirer, **+ Ajouter** te renvoie dans `/coins`.
- **§2 Captures** : couverture canonique par pièce (✅/⚠/❌).
- **§3 Recipe** : sélection de la recette d'augmentation (existing).
- **§4 Run** : bouton "Nouvelle itération" — déclenche l'auto-freeze
  du cohort.

### 3. Capturer les pièces manquantes

Dans **§2 Captures** :

1. Vérifie le delta (X coins manquants / partiels).
2. Clique **"Générer CSV de capture (delta)"** — écrit
   `ml/state/cohort_csvs/<cohort>.csv`.
3. Copie + exécute la commande `adb push` affichée. Elle pousse le CSV
   à `/sdcard/Android/data/com.musubi.eurio/files/Documents/eurio_capture/cohort.csv`
   et force-stop l'app pour qu'elle re-lise au prochain démarrage.
   (Ou utilise `go-task -t app-android/Taskfile.yml push-capture-csv CSV=<path>`.)
4. Sur le téléphone : ouvre l'app, lance le mode capture, suis le protocole
   (6 angles × N pièces).
5. Reviens à l'ordi : `go-task -t app-android/Taskfile.yml pull-debug` —
   pull les fichiers dans `debug_pull/<ts>/`.
6. Dans le front, clique **"Synchroniser"** — le backend lance
   `scan.sync_eval_real --also-write-captures`, dispatche les fichiers
   normalisés vers `ml/datasets/<numista_id>/captures/` et
   `ml/datasets/eval_real_norm/<eurio_id>/`.

Le bandeau §2 se rafraîchit : les badges passent en ✅.

### 4. Lancer l'itération

§4 → **Nouvelle itération**. Au premier launch réussi :
- Le cohort passe `draft → frozen` (irréversible).
- §1 Pièces devient read-only.
- Un bouton **"Cloner"** apparaît dans le header pour créer un nouveau
  cohort en draft à partir de celui-ci.

## Avertissements

> ⚠ **Captures canoniques par pièce.** Une fois prises, elles sont
> réutilisées par tous les cohorts contenant cette pièce. Pas de versioning
> v1 — modifier le protocole (angles, normalize device, hardware phone)
> brise tous les benchmarks passés. Migration vers un capture-set versionné
> = sprint futur.

## Endpoints exposés

| Endpoint | Effet |
|---|---|
| `GET /lab/cohorts?status=draft` | Liste des cohorts éditables (filtre status) |
| `POST /lab/cohorts/{id}/coins` | Ajoute des coins (draft only) |
| `DELETE /lab/cohorts/{id}/coins/{eurio_id}` | Retire un coin (draft only) |
| `POST /lab/cohorts/{id}/clone` | Crée un nouveau cohort en draft à partir d'un existant |
| `GET /lab/cohorts/{id}/captures/status` | Couverture FS-derived par coin |
| `POST /lab/cohorts/{id}/captures/csv` | Génère le CSV delta + écrit sur disque |
| `POST /lab/cohorts/{id}/captures/sync` | Dispatche un `debug_pull/<ts>/` vers `captures/` |

## Migration future

Le rename `ml/datasets/<numista_id>/` → `ml/datasets/coins/<numista_id>/`
reste deferred — voir `design.md` §10 et la mémoire utilisateur
"Coin catalog convention".
