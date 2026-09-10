# De la base à la nef — solidifier avant d'ouvrir

> Ouvert le **2026-09-10**. Entrée : [`PLAN.md`](./PLAN.md). Journal : [`SUIVI.md`](./SUIVI.md).
> Décisions : [`DECISIONS.md`](./DECISIONS.md), toutes 🟡 PROPOSÉ tant que le PO n'a pas tranché.

## Pourquoi ce chantier

Le constat du 2026-09-10 (requêtes en tête de `PLAN.md`) : l'atelier a grossi
pendant que l'édifice reculait. Commits sur `app-android` par mois d'avril à
septembre : 16, 10, 10, 3, 5, 0. L'app est en `0.1.0`, `versionCode 1`, jamais
publiée. `main` est gelé depuis le 2026-05-30, la branche de travail a 635 commits
d'avance. Aucune CI. Un seul auteur humain. 122 000 lignes de doc pour 120 000 de
code hors tests.

Les principes retenus, et ce qu'ils imposent ici :

| Principe | Ce qu'il impose |
|---|---|
| **Une portion consacrée par génération** (cathédrale) | Rien de nouveau ne s'ouvre tant que le dernier lot n'a pas été vu par un œil humain |
| **Un seul métier** (Kongō Gumi) | L'atelier est gelé le temps du chantier : seul ce qui débloque la nef passe |
| **Le fil à plomb chaque jour** (guilde) | Une machine crie à la place de l'humain sur chaque push |
| **Une pierre de fondation** | Un seul tronc, un seul nom, le VPS le suit |
| **Survivre au fondateur** (shinise) | Chaque étape se ferme par un test de succession : un agent neuf, sans contexte, doit pouvoir la vérifier |
| **Reconstruire tous les vingt ans** (Ise) | La purge des docs devient un rite outillé, pas un événement de crise |

## La méthode

Un **architecte** (la session Claude longue) découpe, tranche et journalise. Chaque
étape est jouée par un **exécutant** (sous-agent avec un contrat fermé) puis
vérifiée par un **contre-relecteur** (sous-agent neuf, qui ne voit ni le rapport ni
le diff commenté de l'exécutant, seulement les critères et les commandes). Une étape
ne se ferme que sur un contre-rapport où **chaque critère porte la sortie de sa
commande**. Le protocole complet est dans `PLAN.md` §Méthode.

## Les six étapes, de bas en haut

| # | Étape | Ce qu'elle établit |
|---|---|---|
| 0 | **Le sol** | Un tronc unique `main`, le VPS le suit, les branches mortes archivées |
| 1 | **Le fil à plomb** | Une CI qui passe au vert sur `main` et au rouge sur une casse volontaire |
| 2 | **Le gabarit** | La suite de tests court dans le devShell et en CI, sans test muet |
| 3 | **Les préceptes** | `CLAUDE.md` réduit aux règles intemporelles ; l'état daté déménage |
| 4 | **La nef** | L'APK signé sur une piste de test interne, un scan par jour par quelqu'un d'autre |
| 5 | **Le rite** | `go-task docs:rite` mesure et purge ; joué une première fois |
