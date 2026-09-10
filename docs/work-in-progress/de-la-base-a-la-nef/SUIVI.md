# SUIVI — de la base à la nef

> Journal daté. Chaque étape y dépose son contrat, le rapport de l'exécutant, le
> contre-rapport, et le verdict de l'architecte. Rien ne se ferme sans les trois.

## 2026-09-10 — Ouverture

Chantier ouvert sur le constat du même jour (`PLAN.md` §Constat). Six décisions
proposées dans `DECISIONS.md`, D5 laissée ouverte. **En attente du PO** : D0 (gel de
l'atelier) et D1 (feu vert sur la suppression des branches distantes et le retrait de
`codeberg`). L'étape 0 peut être jouée jusqu'à 0.3 inclus sans lui ; 0.4 et 0.5
attendent.

Deux faits trouvés à la vérification, absents des docs jusqu'ici :
- `pytest` n'est pas dans le devShell `mac` : `nix develop .#mac --command python -m pytest --version` → `No module named pytest`. La suite de 204 fichiers ne peut pas tourner depuis le shell du dépôt.
- Le build release signe avec la clé debug : `app-android/build.gradle.kts:57`.

## Étape 0 — Le sol

_Contrat : à écrire à l'ouverture de la session d'exécution._

### Contrat · 2026-09-10 · feu vert PO sur D0 et D1

**Faits établis avant de lancer** (requêtes rejouables) :
- Toutes les branches locales et distantes sont des ancêtres de `matrice-dino` (`git merge-base --is-ancestor <b> HEAD` → oui pour les 7). Rien ne se perd en les supprimant ; on tague pour garder les noms.
- `repo-cleanup` est un ancêtre de HEAD : le VPS peut avancer par fast-forward.
- L'arbre de travail porte des modifications **d'un autre chantier** (`Taskfile.yml`, `useLotReview.ts`, `LotDetailView.vue`, specs `lot-*`, trois docs `juge-du-crop/`, `secrets/dev.env`). Elles ne sont ni commitées ni écartées. `git checkout main` classique refuserait ; le geste est `git checkout -B main` depuis `matrice-dino`, qui ne change pas l'arbre.

**Entrées** : `PLAN.md` §Étape 0. **Sorties** : les six critères avec sortie collée, la table branche → tag, les trois docs corrigées.

**Interdits** : `push --force` ; `branch -D` sur une branche non taguée ; `git add -A` ; toucher aux fichiers modifiés de l'autre chantier ; sur le VPS, autre chose que `git fetch`, `git checkout main`, `git config` — aucun `docker compose`.
