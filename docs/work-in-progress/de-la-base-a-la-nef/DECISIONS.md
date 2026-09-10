# Décisions — de la base à la nef

> Journal daté. 🟡 PROPOSÉ = tranché par l'architecte, en attente du PO.
> Une décision ne se réécrit pas : on en ajoute une qui supersède.

## D0 — L'atelier est gelé le temps du chantier · 2026-09-10 · ✅ PO le 2026-09-10

Aucun commit dans `ml/`, `studio-local/`, ni dans un autre chantier, sauf s'il débloque un critère du `PLAN.md`. Les modifications non commitées de `useLotReview.ts` et des specs `lot-*` restent en l'état.

**Pourquoi** : Kongō Gumi est mort en sortant de son métier. Le métier ici est le scan ; commits Android par mois 16, 10, 10, 3, 5, 0 pendant que l'atelier prenait 250 commits par mois.

**Ce que ça écarte** : « juste un petit lot » sur la review pendant qu'on attend un run CI.

## D1 — Pas de remaster d'historique ; `main` avance par fast-forward · 2026-09-10 · ✅ PO le 2026-09-10

`main` n'a pas divergé (`0 635`). On l'avance, on tague les branches mortes en `archive/<nom>`, on supprime les branches. ADR-005 reste 🟡 et n'est pas jouée ici.

**Pourquoi** : un remaster est une semaine de travail à risque pour un gain cosmétique. Le sol doit être posé en une session.

**Feu vert PO donné le 2026-09-10** : suppression des branches distantes, retrait du remote `codeberg`.

## D2 — CI sur GitHub Actions, via `nix develop .#ci` · 2026-09-10 · 🟡 PROPOSÉ

Un devShell `ci` léger dans `flake.nix` (python + pytest, node + pnpm, JDK + SDK Android, go-task). Le workflow ne contient aucun `pip install`.

**Pourquoi** : github est le dépôt de référence ; ADR-002 dit « tout par le flake ». Une CI qui installe autrement dérive du poste de dev en un mois.

**Ce que ça écarte** : Codeberg CI (remote abandonné), GitLab (migration non planifiée), un runner auto-hébergé sur le VPS (le VPS est le writer canonique, pas une machine de build).

**Réouverture** : si le run dépasse 20 minutes, on scinde `android` dans un job nocturne.

## D3 — `CLAUDE.md` ≤ 150 lignes, sans date · 2026-09-10 · 🟡 PROPOSÉ

Les préceptes restent ; l'état déménage dans `docs/architecture/ETAT.md`. Une règle sans ADR ni skill est écrite en ADR ou retirée.

**Pourquoi** : les préceptes de Kongō Gumi tiennent sur une page. Un fichier de règles qui porte « vérifié le 2026-08-17 » est un changelog.

## D4 — La nef s'ouvre avec ce qui existe · 2026-09-10 · 🟡 PROPOSÉ

Pas de feature, pas de modèle, pas d'écran nouveau avant la piste interne. Une pièce non reconnue est une donnée.

**Pourquoi** : la crypte sert au culte pendant que la tour attend. Une portion utilisable par génération.

## D5 — Comment compter « un scan venu d'ailleurs » · 2026-09-10 · ⏳ À TRANCHER

Options : (a) un compteur local exporté par les testeurs à la fin des 7 jours, (b) un ping minimal vers `eurio-api` à chaque scan, (c) le journal Play Console seul. L'architecte penche pour (a) : zéro réseau ajouté, zéro dépendance, conforme à « offline-first ».

## D6 — Plafond de 1 500 lignes par chantier vivant, rite trimestriel · 2026-09-10 · 🟡 PROPOSÉ

**Pourquoi** : Ise se reconstruit tous les vingt ans pour transmettre le geste. `juge-et-banc` fait 7 538 lignes et `scan-sans-retrain` 5 533 ; personne ne les relit.
