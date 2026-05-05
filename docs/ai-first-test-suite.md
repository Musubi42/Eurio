# AI-first test suite — kickoff

> Document de cadrage pour une session future. Ne traite pas l'implémentation,
> seulement le pourquoi, la cible, et les questions à trancher avant d'attaquer.
> À reprendre quand on ouvrira le chantier.

## Pourquoi maintenant

Constat session 2026-05-05 (code review auto-validation) : 4 agents Explore
parallèles ont remonté ~70 % de faux positifs sur des questions simples
(« cet endpoint est-il appelé ? », « cette colonne est-elle écrite ? »,
« cette fonction est-elle dead ? »). Les agents avaient raison de douter,
mais aucun moyen rapide de **vérifier**.

Une suite de tests correctement structurée serait la réponse :
- L'agent (ou l'humain) qui doute lance un test ciblé. Pète → la chose
  est vivante. Passe sans rien faire → suspicion confirmée.
- Avant un changement, on capture l'état (« avant »), on patch, on relance
  (« après »). Le diff de tests est la preuve que rien n'a régressé hors
  intention.

Aujourd'hui ce n'est pas le cas :

| Couche | État |
|---|---|
| `ml/tests/` (Python) | 308 tests sur 26 fichiers — couverture inégale, pas d'organisation explicite par domaine, mélange unit / integration / API / pipeline |
| `admin/packages/web/` | **0 test** — ni unit, ni integration, ni e2e |
| `admin/packages/parity/` | Playwright/Maestro existent mais axés screenshots/parité, pas wiring |
| Cross-stack (Python ↔ front ↔ DB) | Aucun test end-to-end qui valide qu'un endpoint backend est consommé par le composable front qui le câble |

## Ce que veut dire « AI-first »

Pas « écrits par une IA », mais **lisibles et exploitables par une IA agent
sans contexte préalable**. Concrètement :

1. **Nom du test = question vérifiée.** `test_get_run_listings_returns_columns_written_by_pipeline` plutôt que
   `test_listings_endpoint`. L'agent qui lit la liste de tests apprend
   ce qui est vérifié sans ouvrir le fichier.
2. **Granularité par contrat, pas par fichier source.** Un test par couple
   (producer, consumer) plutôt qu'un test par module. Si `text_signal`
   écrit `route_decision` et `download` la lit, il existe un test qui
   échoue si l'un des deux change le contrat.
3. **Erreurs explicites.** Quand un test échoue, le message dit *quel
   contrat* est cassé (« endpoint X retourne champ Y absent du modèle
   front Z »), pas un AssertionError nu.
4. **Catégorisation découvrable.** Marqueurs pytest (`@pytest.mark.contract`,
   `@pytest.mark.wiring`, `@pytest.mark.smoke`) qui permettent de lancer
   un sous-ensemble pertinent en 30 s sans tout exécuter.
5. **Status dashboard humain.** Un tableau (généré, pas manuel) qui dit
   « 47/52 contrats couverts, 5 trous documentés ». Voir §Dashboard.

## Catégories de tests à construire

À discuter / réordonner — c'est une matière première, pas un plan figé.

### A. Wiring tests (priorité 1)

But : **prouver que chaque endpoint backend a un consommateur front, et que
le format est compatible.**

- Pour chaque route FastAPI, un test qui :
  1. Appelle l'endpoint via TestClient avec une fixture de DB minimale
  2. Lit le composable TS qui le consomme (parse statique)
  3. Vérifie que les champs Pydantic = champs lus côté TS

Outils possibles : `pydantic-to-typescript`, ou un petit script qui parse
les deux. La vraie valeur : si je supprime un endpoint, le test pète. Si
je rajoute un champ Pydantic non utilisé front, un warning lève.

Aujourd'hui ces tests **n'existent pas du tout**. C'est pile la classe
de bug que la review a (mal) cherché à détecter.

### B. Contract tests par étape pipeline (priorité 1)

But : **chaque étape `ml/sources/_base/steps/*.py` a un test qui valide son
contrat in/out.**

Forme :
```
def test_text_signal_extract_writes_route_decision_on_contradict():
    # GIVEN un source_image avec listing_title contradictoire au target
    # WHEN run_text_signal_extract(...)
    # THEN listing_text_signals row exists, source_images.route_decision='rejected_text'
```

Existe partiellement (`test_text_signal_step.py`, `test_orchestrator.py`),
pas systématique. À uniformiser : 1 fichier `test_step_<name>.py` par
étape, structure GIVEN/WHEN/THEN, fixtures partagées.

### C. End-to-end pipeline tests (priorité 2)

But : **un eurio_id donné, on lance le pipeline complet sur fixture eBay,
et on vérifie l'état final dans toutes les tables touchées.**

`test_orchestrator.py` fait un peu ça mais sur stubs. À étendre avec
fixtures eBay réalistes (snapshots de vraies réponses Browse API anonymisées).

### D. Smoke tests (priorité 2)

But : **5 secondes de tests qui vérifient que le système est branché.**

- L'API démarre
- Chaque table existe avec son schéma attendu
- Chaque source_id dans `sources_registry` a un adapter importable
- Chaque endpoint déclaré répond (même si 404 légitime)

À lancer en pre-commit ou en pre-push.

### E. Front tests (priorité 2)

But : **rattraper le retard côté admin.**

Au minimum :
- Composables (`useReviewApi`, `useDinoSuggestions`, etc.) testés avec
  `vitest` + mock fetch — couvre la sérialisation/désérialisation.
- Composants critiques (`LotDetailDrawer`, `ReviewActionBar`, `CandidateRow`)
  testés avec `@vue/test-utils` — couvre l'affichage des états
  (loading, empty, error, success).
- 0 test e2e front V1 — Playwright vit déjà dans `admin/packages/parity/`,
  pas la peine de doublonner.

### F. Tests d'invariants DB (priorité 3)

But : **détecter les data orphelines automatiquement.**

- Pour chaque colonne lue par un endpoint, un test qui vérifie qu'au
  moins un endroit du code l'écrit (script de cohérence, pas un test
  au sens classique).
- Pour chaque table, un test qui vérifie qu'elle est lue ET écrite
  quelque part dans le code.

C'est de la statique sur le code source + introspection DB. Difficile à
écrire mais immense gain en détection de dette.

## Dashboard / sortie humaine

Pas un livrable V1, mais à garder en tête :

- Un `make test-status` ou `go-task ml:test-coverage` qui sort un
  tableau Markdown dans `docs/test-status.md` (régénéré, pas édité) :

```
| Catégorie | Couverts | Trous documentés | Total |
|---|---|---|---|
| Wiring (endpoints) | 28 | 5 | 33 |
| Steps pipeline | 6 | 2 | 8 |
| E2E pipelines | 1 | — | 1 |
| Front composables | 0 | 9 | 9 |
| Smoke | 4 | — | 4 |
```

Permet à l'humain de voir d'un coup d'œil où sont les trous, et à l'agent
de prioriser les tests à écrire en premier.

## Comment ça aide pour le « avant/après »

Workflow cible :
1. Avant un changement : `go-task test:snapshot` capture l'état (résultats
   + counts par catégorie) dans `.test-snapshot.json`
2. On patch
3. `go-task test:diff` montre quoi est cassé / résolu / inchangé

Particulièrement utile pour :
- Refactos qui touchent le contrat (renommage colonne, signature step)
- Suppressions de code (vérifier qu'on n'a pas tué un consumer)
- Reviews de PR (le diff de tests = oracle de l'impact)

## Questions à trancher avant d'attaquer

1. **Outil pour Front** — vitest seul, ou vitest + storybook/histoire ?
   Storybook ajoute de la doc visuelle qui pourrait remplacer en partie
   les tests de rendu.
2. **Fixtures DB** — un dump SQLite de référence dans le repo (lourd
   mais reproductible), ou des factories en code (légères mais friables) ?
3. **Marqueurs pytest** — `slow / fast / contract / wiring / smoke` ?
   Trouver le set minimal qui n'oblige pas à mémoriser 8 tags.
4. **Couverture cible** — viser % couverture (mauvaise métrique souvent)
   ou liste explicite des « contrats critiques » (endpoint X → consumer Y)
   qu'on s'engage à toujours tester ?
5. **Génération auto vs main** — wiring tests générés depuis introspection
   des routes + parse TS, ou écrits à la main ? Auto = pérenne mais magique,
   main = clair mais laborieux.
6. **CI / pre-commit** — quels tests bloquent quoi ? Smoke en pre-commit
   semble obvious, le reste à débattre.
7. **Retro-compat avec les 308 existants** — on les réorganise ou on les
   laisse vivre tels quels et on ajoute la nouvelle couche en parallèle ?
   Mon biais : ne pas toucher l'existant, ajouter une nouvelle structure
   à côté, migrer au fil de l'eau quand on touche un domaine.

## Hors scope V1

- Mutation testing (mutpy, etc.) — overkill pour cette taille
- Property-based testing (hypothesis) sauf si déjà adopté ailleurs
- Tests de performance / load — Eurio est local, pas un service haute
  charge
- Tests de sécurité / fuzz — pas de surface attaque réelle (admin local)

## Mémoires liées

- `feedback_chunk_audit_flow` — chunks 30min-3h, livrer + attendre
- `feedback_no_debt` — pas de shortcut qui crée de la dette
- Session 2026-05-05 review auto-validation : déclencheur de ce doc

## Prochaine action quand on rouvre

Commencer par §A (wiring tests endpoints) sur le périmètre `auto-validation`
uniquement. C'est là où la dernière review a le plus saigné, donc retour
sur investissement immédiat. Si la mécanique tient, étendre aux autres
domaines.

Avant de coder : trancher les 7 questions §"Questions à trancher". 30 min
de discussion suffisent.
