# PLAN — de la base à la nef

> Six étapes, jouées **dans l'ordre**, une par session au plus. Chaque étape a un
> objectif, des critères de succès avec leur commande, une falsification (comment
> la faire échouer exprès), un contrat d'exécutant et un contrat de contre-relecteur.
> Les chiffres de départ portent leur requête ; ils sont à rejouer à la fermeture.

## Constat de départ (2026-09-10)

| Mesure | Valeur | Requête |
|---|---|---|
| Commits `app-android` par mois (04→09) | 16, 10, 10, 3, 5, 0 | `git log --format='%ad' --date=format:'%Y-%m' -- app-android \| sort \| uniq -c` |
| Version app | `0.1.0`, `versionCode 1` | `grep -n 'versionCode\|versionName' app-android/build.gradle.kts` |
| Signature release | `signingConfigs.getByName("debug")` | `grep -n signingConfig app-android/build.gradle.kts` |
| Dernier commit `main` | 2026-05-30 | `git log -1 --format=%ad --date=short main` |
| Avance de la branche courante sur `main` | 635 | `git rev-list --left-right --count main...HEAD` |
| Branches locales | 9 ; refs totales 26 | `git branch \| wc -l` ; `git branch -a \| wc -l` |
| CI | aucune | `ls .github/workflows` |
| `pytest` dans le devShell | **absent** | `nix develop .#mac --command python -m pytest --version` |
| Fichiers de test Python / lignes | 204 / 51 621 | `find ml -path '*/.venv' -prune -o -name 'test_*.py' -print` |
| Specs front | 8 | `find admin -name '*.spec.ts' -not -path '*/node_modules/*'` |
| Lignes de doc / dont archive | 121 863 / 64 987 | `find docs -name '*.md' \| xargs cat \| wc -l` |
| Commits docs-only sur les 300 derniers | 167 | boucle `git show --name-only` filtrée sur `docs/`, `CLAUDE.md`, `.claude/` |
| `CLAUDE.md` | 394 lignes, 20+ dates | `wc -l CLAUDE.md` ; `grep -c '2026-' CLAUDE.md` |
| Fichiers REPRENDRE/HANDOFF/SUIVI/ETAT | 29 | `find docs -iname 'REPRENDRE*' -o -iname 'HANDOFF*' -o -iname 'SUIVI*' -o -iname 'ETAT-*'` |

## Règle transverse : l'atelier est gelé (D0)

Pendant ce chantier, **aucun commit n'entre dans `ml/`, `studio-local/` ou `docs/work-in-progress/<autre chantier>/`** sauf s'il débloque un critère d'une étape ci-dessous. Les modifications non commitées d'un autre chantier (`useLotReview.ts`, `LotDetailView.vue`, specs `lot-*`) sont **laissées telles quelles** : ni intégrées, ni écartées, jusqu'à ce que leur chantier les reprenne.

## Méthode : exécutant, contre-relecteur, architecte

1. L'architecte écrit le **contrat** de l'étape dans `SUIVI.md` avant de lancer quoi que ce soit : entrées, sorties attendues, interdits.
2. L'**exécutant** (sous-agent, modèle fort) joue le contrat, commite en staging explicite par fichier, et rend un rapport : ce qu'il a fait, ce qu'il n'a pas pu faire, la sortie de chaque critère.
3. Le **contre-relecteur** (sous-agent **neuf**, contexte vide, sonnet suffit) reçoit **uniquement** la liste des critères et leurs commandes. Il ne reçoit ni le rapport ni le raisonnement de l'exécutant. Il rejoue chaque commande, colle sa sortie, conclut PASS ou FAIL par critère, et joue la **falsification** de l'étape.
4. L'architecte confronte les deux rapports. Un critère FAIL rouvre l'étape avec un nouveau contrat ciblé. Deux rapports en désaccord sont arbitrés par une **troisième commande**, jamais par l'argument.
5. Les deux rapports sont collés dans `SUIVI.md`, datés. Une étape fermée ne se rouvre que par une décision dans `DECISIONS.md`.
6. Les gestes **irréversibles** (suppression de branche distante, publication Play, réécriture d'historique) attendent le **feu vert écrit du PO** dans `DECISIONS.md`. Tout le reste avance sans lui.

**Test de succession**, à chaque fermeture : le contre-relecteur n'a eu que le dépôt et les critères. S'il a dû demander quelque chose, la doc de l'étape est incomplète et l'étape n'est pas fermée.

---

## Étape 0 — Le sol : un tronc, un nom

**Objectif.** `main` redevient la seule vérité. Le VPS la suit. Les branches mortes deviennent des tags d'archive.

**Ce qui est tranché** (D1) : pas de remaster d'historique (ADR-005 reste 🟡). On avance `main` par fast-forward sur `matrice-dino`, puisque `main` n'a pas divergé (`git rev-list --left-right --count main...HEAD` donne `0 635`).

**Critères de succès.**

| # | Critère | Commande | Attendu |
|---|---|---|---|
| 0.1 | `main` contient tout le travail | `git rev-list --count main..matrice-dino` | `0` |
| 0.2 | `main` est la branche courante et poussée | `git branch --show-current` ; `git rev-parse main github/main` | `main` ; deux SHA identiques |
| 0.3 | Les branches mortes sont archivées, pas perdues | `git tag -l 'archive/*' \| wc -l` ; `git branch \| wc -l` | ≥ 8 ; **1** (resserré le 2026-09-10 : la falsification a montré que « ≤ 2 » laissait passer une branche surnuméraire) |
| 0.4 | Le VPS suit `main` | sur le VPS : `git -C /opt/eurio rev-parse --abbrev-ref HEAD` ; `git -C /opt/eurio config branch.main.remote` | `main` ; `github` |
| 0.5 | Le remote mort ne piège plus personne | `git remote` | `github` seul ; codeberg retiré du clone local |
| 0.6 | La doc ne nomme plus `repo-cleanup` ni `matrice-dino` comme tronc | `grep -rn 'repo-cleanup\|matrice-dino' CLAUDE.md docs/work-in-progress/README.md .claude/skills` | vide, hors mention historique datée |

**Falsification.** Créer une branche `tmp-x`, y commiter, vérifier que le contre-relecteur la voit dans 0.3 comme surplus. La supprimer.

**Contrat exécutant.** Entrées : ce tableau. Interdits : `git push --force`, `git branch -D` sur une branche non taguée, toucher au VPS sans la skill `eurio-vps-deploy`. Sortie : les six critères avec sortie collée, plus la liste `branche → tag` dans `SUIVI.md`.

**Feu vert PO requis** pour : la suppression des branches distantes sur github après tagging, et le retrait du remote `codeberg`.

---

## Étape 1 — Le fil à plomb : une CI qui crie

**Objectif.** Chaque push sur `main` fait tourner ce qui peut casser en silence : `pytest` (ml), `vitest` (studio-local), `go-task tokens:check`. La compilation Android rejoint la CI à l'étape 4 (D10). Une casse volontaire la met au rouge.

**Ce qui est tranché** (D2) : GitHub Actions, puisque github est le dépôt de référence. Le job entre par `nix develop .#ci`, un devShell léger à créer dans `flake.nix`, pour que la CI et le poste de dev partagent le même toolchain (ADR-002). Pas de `pip install` ni de `brew` dans le workflow.

**Critères de succès.**

| # | Critère | Commande | Attendu |
|---|---|---|---|
| 1.1 | Le workflow existe et cible `main` | `cat .github/workflows/ci.yml \| grep -n 'branches'` | `main` |
| 1.2 | Le dernier run sur `main` est vert | `gh run list --branch main --limit 1 --json conclusion` | `success` |
| 1.3 | Les trois jobs y sont (D10 : Android attend l'étape 4) | `gh run view --json jobs -q '.jobs[].name'` | `ml`, `admin`, `tokens` |
| 1.4 | Le devShell `ci` fournit pytest | `nix develop .#ci --command python -m pytest --version` | une version |
| 1.5 | Durée raisonnable | `gh run view --json jobs -q '.jobs[] \| .name+" "+.conclusion'` et l'horodatage | < 20 min total, sinon D2 rouvert |

**Falsification.** Pousser sur une branche `ci-falsification` un test qui `assert False` et un `tokens.css` désaligné, **et ouvrir une PR en draft** : le workflow ne se déclenche sur `push` que pour `main`, c'est `pull_request` qui couvre les branches (corrigé le 2026-09-10 après que le contre-relecteur a dû le découvrir seul). Les deux jobs doivent passer au rouge. Fermer la PR, supprimer la branche.

**Contrat exécutant.** Entrées : ce tableau, `flake.nix`, `Taskfile.yml`. Interdits : désactiver un test pour passer au vert (les tests cassés sont **listés** pour l'étape 2, pas masqués) ; secrets dans le workflow. Sortie : le workflow, le devShell `ci`, la liste des tests rouges au premier run.

---

## Étape 2 — Le gabarit : une suite de tests qui dit vrai

**Objectif.** La suite passe en local et en CI, et chaque test ignoré porte sa raison. Les trois familles de pannes muettes de `eurio-verify` ont chacune un test qui les attrape.

**Critères de succès.**

| # | Critère | Commande | Attendu |
|---|---|---|---|
| 2.1 | Vert complet dans le devShell | `nix develop .#ci --command python -m pytest ml -q` | `0 failed` |
| 2.2 | Aucun skip anonyme | `grep -rn 'pytest.mark.skip\|xfail' ml --include='test_*.py' \| grep -v 'reason='` | vide |
| 2.3 | Les skips restants sont comptés et justifiés | `pytest ml -q -rs \| tail -n 30` collé dans `SUIVI.md` | chaque ligne pointe une décision |
| 2.4 | Pannes muettes couvertes | un test nommé par famille, listé dans `SUIVI.md` avec le chemin | 3 tests, chacun rouge sur mutation |
| 2.5 | Le front aussi | `pnpm --filter studio-local test` | `0 failed` |

**Falsification.** Pour chaque test de 2.4, appliquer la mutation qu'il vise (par exemple un `503` transformé en `200`) et vérifier qu'il passe au rouge. Revert.

**Contrat exécutant.** Interdits : supprimer un test, élargir un seuil pour passer, toucher au code métier au-delà de ce qu'un test rouge exige. Chaque correction de code métier est un commit séparé, nommé par le test qu'il fait passer.

---

## Étape 3 — Les préceptes : ce qui ne change pas, séparé de ce qui change

**Objectif.** `CLAUDE.md` ne contient plus que les règles intemporelles et les pointeurs. Tout ce qui est daté déménage dans `docs/architecture/ETAT.md`, qui devient la photo courante du système.

**Ce qui est tranché** (D3) : `CLAUDE.md` ≤ 150 lignes. Une règle sans ADR ni skill qui la porte est soit écrite en ADR, soit retirée.

**Critères de succès.**

| # | Critère | Commande | Attendu |
|---|---|---|---|
| 3.1 | Taille | `wc -l CLAUDE.md` | ≤ 150 |
| 3.2 | Aucune date dans les préceptes | `grep -c '2026-' CLAUDE.md` | `0` |
| 3.3 | Chaque règle R0..R3 et chaque interdiction pointe une ADR ou une skill | lecture croisée par le contre-relecteur | 100 % |
| 3.4 | L'état daté a un seul domicile | `ls docs/architecture/ETAT.md` ; `grep -c '2026-' docs/architecture/ETAT.md` | existe ; ≥ 20 |
| 3.5 | Test de succession | un agent neuf, avec `CLAUDE.md` et `docs/architecture/` seulement, répond à dix questions fixées dans `SUIVI.md` (où écrit-on, quel tronc, comment on vérifie, comment on déploie…) | 10/10 sans demander |

**Falsification.** Retirer une ligne de pointeur de `CLAUDE.md` et rejouer 3.5 : une question doit devenir sans réponse.

---

## Étape 4 — La nef : le scan dans une main qui n'est pas la tienne

**Objectif.** L'APK actuel, signé avec une vraie clé, est sur la piste de test interne du Play Store. Cinq personnes l'installent. Pendant sept jours, au moins un scan par jour vient de quelqu'un d'autre que le PO.

**Ce qui est tranché** (D4) : on publie **ce qui existe**. Pas de nouvelle feature, pas de nouveau modèle, pas de nouvel écran. Si le scan ne reconnaît pas une pièce, c'est une donnée, pas un bloqueur.

**Prérequis mesurés à l'ouverture de l'étape.**
- Le PO fait un scan bout en bout sur son téléphone avec le build de `main` et note le résultat dans `SUIVI.md`. Si l'app ne va pas jusqu'à « ajouter au coffre », l'étape s'ouvre par ce seul correctif.
- Clé de signature : générée, stockée dans `secrets/dev.env` (ADR-015), jamais ailleurs.

**Critères de succès.**

| # | Critère | Commande | Attendu |
|---|---|---|---|
| 4.1 | Build release signé reproductible | `go-task android:release` ; `apksigner verify --print-certs app-release.apk` | certificat ≠ debug |
| 4.2 | Version qui avance | `grep versionCode app-android/build.gradle.kts` | ≥ 2, `versionName 0.2.0` |
| 4.3 | Sur la piste interne | capture Play Console dans `SUIVI.md` | piste `internal`, statut disponible |
| 4.4 | Cinq testeurs | Play Console, liste des testeurs | 5 |
| 4.5 | Un scan par jour venu d'ailleurs | journal local exporté, ou compteur minimal dans l'app : à trancher en D5 | 7 jours consécutifs |
| 4.6 | Zéro crash bloquant | Play Console, vitals | 0 ANR, 0 crash sur le scan |

**Falsification.** Installer le build sur un téléphone vierge, sans compte, sans réseau. Le scan doit s'ouvrir.

**Contrat exécutant.** Le sous-agent prépare la signature, la tâche `android:release`, la montée de version, la fiche minimale Play (politique de confidentialité, icône, description). Interdits : toute modification sous `features/` autre que le correctif de prérequis, tout ajout de dépendance.

**Feu vert PO requis** pour : la mise en ligne sur la piste interne et le choix des cinq testeurs.

---

## Étape 5 — Le rite : reconstruire la doc à date fixe

**Objectif.** Une tâche `go-task docs:rite` mesure et liste ce qui doit partir. Elle est jouée une première fois, et son prochain rendez-vous est inscrit.

**Ce qui est tranché** (D6) : plafond de **1 500 lignes par chantier vivant**. Au-dessus, on scinde ou on archive. Rythme : à chaque fermeture d'étape de ce chantier, puis **tous les trimestres**.

**Critères de succès.**

| # | Critère | Commande | Attendu |
|---|---|---|---|
| 5.1 | La tâche existe et sort un rapport | `go-task docs:rite` | tableau chantier → lignes, âge, liens morts |
| 5.2 | Aucun chantier vivant au-dessus du plafond | `for d in docs/work-in-progress/*/; do cat $d*.md \| wc -l; done` | tous ≤ 1 500 |
| 5.3 | Aucun lien mort interne | sortie de `docs:rite` | `0 lien mort` |
| 5.4 | Le rite est daté | `grep -n 'Prochain rite' docs/work-in-progress/README.md` | une date à ≤ 3 mois |

**Falsification.** Ajouter un lien vers un fichier inexistant dans un chantier ; `docs:rite` doit le lister.

---

## Ce qui n'est PAS dans ce chantier

- Le choix ArcFace ou DINO à l'échelle 671 classes : reste dans `juge-et-banc`, gelé.
- Le juge du crop, la review, l'enrichissement : gelés (D0).
- Le remaster d'historique (ADR-005) : refusé pour ce chantier (D1).
- Toute nouvelle scène Android : R1 s'applique, et la nef s'ouvre avec ce qui existe (D4).
