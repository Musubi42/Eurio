# Prompt de reprise — durcir les skills, puis finir le flux

> Écrit à la fin de la session du 2026-08-17. Colle le bloc ci-dessous dans une
> session neuve à la racine du dépôt. Il est volontairement long : il porte le
> contexte que la session précédente a payé cher.

---

Tu reprends un travail sur **Eurio** (branche `repo-cleanup`, tout est poussé sur
`github` et `codeberg`). La session précédente a fait deux choses : prouver le
parcours de données de bout en bout sur les deux machines, et découvrir que le
projet perdait un temps considérable **faute de connaissance compilée au bon
endroit**. Elle a donc écrit deux skills. Ta mission est de **durcir ce système de
connaissance**, puis de le compléter.

## Lis d'abord, dans cet ordre

1. `CLAUDE.md` — en entier. La table de routage des skills est récente.
2. `docs/work-in-progress/HANDOFF-2026-08-16.md` — surtout la section finale
   « Fin de la session du 2026-08-17 » : ce qui est livré, ce qui reste ouvert,
   les pièges d'exploitation.
3. `docs/architecture/parcours.md` §4 et §5 — les deux parcours écrits, avec leurs
   mesures et leurs pièges.
4. Les 7 skills de `.claude/skills/`.

## Mission 1 — établir une méthode pour tester une skill, puis l'appliquer

C'est le cœur de la session. Une skill vérifiée « à la lecture » ne prouve rien :
un agent en lecture seule confirme que les chemins existent, pas que la skill
**fait agir juste**. Il faut des tests réels : lancer des jobs, taper l'API,
interroger la base, et surtout **faire exécuter une tâche par un sous-agent**.

### Le test qui compte : le sous-agent

Donne à un sous-agent une tâche réelle du domaine d'une skill, en lui donnant
**la skill et rien d'autre comme documentation** (il garde évidemment le droit de
lire le code et d'explorer — c'est le fonctionnement normal).

**Critère d'évaluation — à ne pas se tromper de mesure.** Le but n'est *pas* que
le sous-agent réussisse à 100 % sans explorer : une skill ne peut pas tout dire,
et ce serait un mauvais objectif (elle deviendrait un pavé que personne ne lit).
Ce que la skill doit garantir :

1. **il évite les pièges que la skill existe pour éviter** (c'est le vrai test) ;
2. **il sait où aller lire** quand la skill s'arrête — la section « ce que cette
   skill ne couvre pas » doit avoir servi ;
3. **il ne réinvente pas** un outil que le projet possède déjà ;
4. le temps et les tokens qu'il dépense à s'orienter sont faibles.

Un échec sur (1) ou (3) = la skill est à corriger. Un échec sur un détail que la
skill n'avait pas vocation à porter = c'est normal, ne durcis pas la skill pour
autant. **Note la différence explicitement dans ton rapport.**

Tâches réelles suggérées, une par skill :

| Skill | Tâche à faire exécuter |
|---|---|
| `eurio-enrichment` | « la classe `es-2euro-juan-carlos-i-t2` est pauvre en crops vraiment siens — enrichis-la » (elle a une requête eBay peu discriminante : c'est un vrai problème ouvert) |
| `eurio-review` | « accepte en training les crops sûrs de `fr-2euro-standard-t1` » (38 candidats attendent ; le piège est de trier sur `top1_sim` seul et d'ignorer la marge) |
| `eurio-run-local` | « lance une itération de 3 epochs sur une petite cohorte » (piège : le flip, la base de calcul, ne pas écraser `eurio.work*.db`) |
| `eurio-data-writes` | « fais écrire une donnée par une route qui répond 503 » (doit comprendre que c'est une route non reroutée, pas une panne) |
| `eurio-verify` | « prouve que le correctif X marche » (doit faire rougir le test avant de conclure) |

### Ce que tu dois produire

Une **méthodologie d'écriture de skill**, tirée de ce que ces tests montrent —
pas inventée a priori. Elle a sa place dans une meta-skill ou une section de
`CLAUDE.md`, à toi de proposer. Les principes déjà observés, à confirmer ou
infirmer par les tests :

- une skill se déclenche sur un **moment de travail** (« je dois trancher des
  crops »), pas sur un sous-système — c'est la `description` qui fait le
  déclenchement, donc elle doit contenir les mots que quelqu'un emploierait ;
- elle contient des **incidents datés et mesurés** (« le 2026-08-17, la planche
  affichait 24 candidats dont 2 bons ») plutôt que des principes abstraits ;
- elle dit **ce qu'elle ne couvre pas**, avec le fichier et sa taille ;
- elle **passe la main** à la skill suivante ;
- elle est **vérifiée par un agent avant commit** — la session précédente a écrit
  5 affirmations fausses de mémoire, dont une qui envoyait vers un système
  homonyme mais différent.

## Mission 2 — compléter le système

Une fois la méthode établie et les skills existantes durcies :

1. **`eurio-cohort`** — composer une cohorte, ce que « prête à entraîner » veut
   dire, les deux garde-fous `block`/`warn`, le gel irréversible.
2. **`eurio-promote`** — la chaîne lab → `prod/current` → assets → MinIO → APK.
   Tout est mesuré dans `parcours.md` §5 : elle **remplace** au lieu d'accumuler,
   `--no-supabase` existe depuis peu, et elle n'a jamais été parcourue jusqu'au
   bout.
3. **`actions.yml`** — aujourd'hui 5 actions méta. Il gagnerait : démarrer la
   stack, santé du canonique, fraîcheur (`ml:freshness` existe et sort en 2 si
   c'est en retard), état des sauvegardes, suite de tests, tirer la réplique.
   Plus un bloc décrivant l'infra. **Contrainte** : il reste *méta* — jamais de
   donnée métier (cf. skill `eurio-driver`, « principe Photoshop »).

## Mission 3 — reprendre le travail de fond là où il s'est arrêté

Le but initial reste : **s'assurer que les parcours de données sont corrects, sans
erreur, et testés**. `docs/architecture/parcours.md` en tient le journal ; sa règle
d'écriture est *un parcours n'est écrit qu'après avoir été tracé dans le code ET
vérifié par une mesure*. Six parcours sur huit restent à écrire.

Le travail immédiat, par ordre d'utilité (détail dans le HANDOFF) :

1. **Accepter les crops** — 38 pour `fr-2euro-standard-t1`, 24 pour
   `es-2euro-juan-carlos-i-t2`, **dans le front de review**. Calibrage humain :
   ~10 % de faux à 0,855, donc passe visuelle obligatoire.
2. **Le correctif de la marge** — le triage a la bonne règle
   (`sim ≥ 0,55` **et** `spread ≥ 0,05`) ; elle ne s'applique pas partout où l'on
   propose des candidats. Test qui rougit d'abord.
3. **Cohorte d'union → itération → promotion réelle** : couvrir les 23 classes de
   production ∪ les nouvelles. Aucune classe ne serait alors perdue.
4. **84 photos de bench** échouées sous des slugs morts (47 % du golden set). À
   remapper **par preuve visuelle**, jamais par ressemblance de chaînes — et poser
   la règle manquante : tout renommage laisse une ligne dans `coin_aliases`.

## Manière de travailler

- **Mesure avant d'affirmer.** Toute affirmation chiffrée porte sa date. Les
  erreurs les plus coûteuses de la session précédente venaient de documents
  écrits de bonne foi, sans mesure.
- **Les pannes sont muettes ici** (`eurio-verify`). Un compteur à zéro n'est pas
  une preuve ; un log qui ne trace que les échecs n'est pas un bilan.
- **Le flip Direction A est le piège n°1** (`eurio-data-writes`). Le devShell
  pose `EURIO_DB_READONLY=1`.
- Ne tue jamais un process avec `pkill -f <motif>` si le motif est dans ta propre
  commande : tu te tues toi-même. Passe par le PID (`lsof -ti :8042`).
- Les jobs longs (backfill DINO : 1 h 26 ; scrape : 1 h) tournent en tâche de
  fond et ne loguent pas leur avancement — mesure dans leur base scratch.
- Commits en français, staging explicite par fichier, jamais `git add -A`.
