# ⚠️ PROMPT CONSOMMÉ — archive

> **Cette session a eu lieu le 2026-08-22, et tout ce qu'elle demandait est
> livré** (design + lots 0-6). Ce fichier ne sert plus qu'à retrouver ce qui
> avait été demandé, et sous quelles contraintes.
>
> 👉 **Pour reprendre le travail : [`REPRENDRE-ICI.md`](REPRENDRE-ICI.md).**
>
> ⛔ Ne pas le recoller dans une nouvelle session : il ouvrirait une phase de
> design déjà close, et ses chiffres (671 classes, 4 426, 344/276…) sont
> périmés.
eurio_kDbYQguxLXf5DXWXTa6N7pzY4galdzI0vSadQX_aaJU

---

# Prompt — session design du front « besoin → review » (D6)

> À coller tel quel dans une nouvelle session Claude Code ouverte à la racine
> du dépôt. La session commence par un **brainstorm avec le PO**, pas par du
> code. Écrit le 2026-08-21.

---

Tu es l'architecte front d'une phase de **design** (pas d'implémentation) pour
l'admin Eurio. Contexte en une phrase : on veut peupler 671 classes de pièces
de 2 € avec 8 exemplaires propres chacune dans une banque d'ancres DINO, avec
le moins de temps humain et de quota eBay possible, et l'admin actuel ne
répond pas à la question « quelle classe je nourris maintenant, par quel
geste, et quand est-ce que j'arrête ».

## Ce qui se passe en parallèle — et ce que tu ne touches pas

- Le PO est **en train de trancher ~777 crops** dans le front de review
  (`/review/manual?run=…`). Chaque décision écrit au canonique
  (`eurio-api.musubi.dev`) via le front existant. **Tu n'écris rien au
  canonique, tu ne lances aucun run, aucun rebuild de banque, aucun scrape.**
- Une autre session (architecte ML) fera ensuite le rebuild de la banque
  (amorce médoïde, O6). La banque servie aujourd'hui (`365dcab2a253`) est
  donc **provisoire** : ses chiffres servent à concevoir, pas à calibrer.
- Tu peux **lire** librement la réplique `ml/state/eurio.replica.db`
  (`sqlite3 -readonly`, ou `file:…?mode=ro`) et l'API en GET avec le PAT du
  devShell (`$EURIO_API_TOKEN`). Les modules stdlib `ml/shared/class_need.py`
  et `ml/shared/class_family.py` sont le **seul** calcul du besoin : tout
  chiffre que tu affiches en vient, tu n'en recalcules aucun à ta façon.
- Tu peux lancer le front local (`go-task front:dev`, `localhost:5173`) pour
  regarder l'existant. Tu ne modifies pas `studio-local` pendant la phase
  design : les maquettes sont **jetables**, dans
  `docs/work-in-progress/pipeline-propre/design/` (HTML statique autonome ou
  Artifacts), et elles le disent en en-tête.
- Pas de prototype `proto/` à faire (décision D6 : écrans admin, R1 ne
  s'applique pas). En revanche on **conçoit avant d'intégrer**.

## À lire, dans cet ordre (1 h)

1. `CLAUDE.md` — règles du dépôt (R0 pas de dette, R0bis front unique, R2 tokens).
2. `docs/work-in-progress/pipeline-propre/DECISIONS.md` — les six décisions
   du PO (D1 cible = banque, D2 « pleine » à la cible, D3 crops **parqués**
   jamais supprimés, D4 émissions communes, D5, D6). Elles sont non
   négociables ; si une te semble fausse, tu le dis au PO, tu ne la contournes pas.
3. `docs/work-in-progress/pipeline-propre/FLOW-ADMIN.md` — les huit plaques,
   les quatre stations, le piège des deux « N par classe ».
4. `docs/work-in-progress/pipeline-propre/outils/O2-vue-classe-vers-8.md` et
   `O4-filtres-par-signaux.md` — les deux surfaces à concevoir, avec leurs
   propriétés non négociables (« elle dit quand le goulot n'est pas elle »,
   « elle ne se ment pas sur zéro », « GESTE = un lien, jamais une action directe »).
5. `docs/work-in-progress/pipeline-propre/VISION.md` §3 (les quatre vérités
   mesurées) et `JOURNAL.md` (les chiffres d'aujourd'hui, avec leurs requêtes).
6. L'existant à ne pas réinventer : `admin/packages/studio-local/src/features/review/`
   (6 écrans + la pêche `/review/peche`), `features/bench/components/BenchFunnel.vue`
   (l'entonnoir « le rétrécissement EST l'entonnoir »), `app/router.ts`
   (`meta.heavy`, `AppLayout`, `LocalOnlyNotice`), `features/lab/composables/useCohortFloor.ts`
   (comment un seuil est lu **avec sa provenance**, jamais inventé localement).
7. Les skills `eurio-review` (ce que la review sait et ne sait pas — la
   « cécité sur les standards », la marge plutôt que la similarité) et
   `eurio-banque` §2 (la maille `class_id`).
8. `docs/design/_shared/parity-rules.md` §R6 et `shared/tokens.css` — le
   vocabulaire visuel existant (tokens, pas de couleur en dur).

## Ce qu'on attend de la session

**Phase 1 — brainstorm avec le PO (avant tout livrable).** Pose-lui les
questions, une à la fois, avec ta recommandation à chaque fois. Celles qu'on
sait déjà devoir poser :

- **Le parcours d'une session de travail.** Il arrive, il voit quoi en
  premier ? Une liste de classes triée par « ce que l'action débloque » (O2)
  — ou un chiffre unique (« 4 426 exemplaires manquent, 344 classes ont de
  quoi avancer ») ? Combien de clics entre « j'ouvre l'admin » et « je
  tranche le premier crop » ?
- **« Parqué » (D3), concrètement.** Les crops des classes pleines doivent
  rester visibles et réversibles sans entrer dans les files de travail. Est-ce
  une `lane`, un statut, un simple filtre d'affichage piloté par
  `class_need` ? Que voit-on sur une classe pleine : un compte, un lien
  « voir les 305 parqués », rien ? Qui peut « déparquer », et ça écrit quoi ?
- **Les zéros qui s'expliquent (O2 §3).** Quand une classe n'a aucun
  candidat servable, l'écran doit dire pourquoi (rien scrapé / masqués par
  le filtre pays / contredits par l'ère). Comment on montre ça sans un
  paragraphe par ligne ?
- **Les filtres de la pêche (O4).** Pays auto-désarmé, ère, dénomination :
  actifs par défaut ou non, levables d'un clic, et **toujours affichés avec
  leur effet** (« 12 masqués »). Où vivent-ils à l'écran ?
- **Les deux « N par classe ».** Voie B (banque, cible 8/5, plafond 10)
  d'un côté, voie A (cohorte ArcFace, `min_real` 10) de l'autre. L'écran
  compte la voie B et le dit ; comment éviter qu'un lecteur les confonde ?
- **Les émissions communes (D4).** 87 classes où l'image ne peut pas
  trancher le pays : le titre de l'annonce doit passer au premier plan. Même
  écran avec une variante, ou un mode ?
- **L'entonnoir (O3), plus tard** : entrée par run **et** par classe, au
  grain annonce. Juste le positionner dans le flow, pas le dessiner.
- **Hébergé ou local ?** O2 est du SQL pur → accessible en hébergé (pas
  `meta.heavy`). Les gestes qu'elle propose (pêcher, scraper) sont lourds et
  se grisent tout seuls. Vérifie que le parcours tient debout en hébergé.

**Phase 2 — inspiration, rapidement et avec des sources.** Regarde comment
d'autres outils traitent « une file de travail cadrée par un besoin » et
« un entonnoir qui se lit dans les deux sens » : outils d'annotation
(Label Studio, CVAT, Encord, Roboflow Annotate — files, progression, reprise),
tri/triage (Linear, GitHub Projects — listes ordonnées par priorité avec un
verdict par ligne), analytics d'entonnoir (Mixpanel/Amplitude — plaques
cliquables), et les « active learning loops » (Lightly, Prodigy — « quoi
labelliser ensuite »). Ramène 3 à 5 idées **concrètes** (un écran, un geste),
pas un benchmark.

**Phase 3 — le design.** Livrables, dans
`docs/work-in-progress/pipeline-propre/design/` :

1. `DESIGN.md` — le parcours en une page (entrée → classe → pêche → retour),
   les états de chaque surface (vide, chargement, erreur, parqué, désarmé,
   pleine, image insuffisante), le vocabulaire (les mots exacts affichés),
   et la liste des décisions prises avec le PO. Chaque chiffre montré dans
   une maquette porte le champ `ClassNeed` d'où il vient.
2. Maquettes **jetables** (HTML statique, tokens de `shared/tokens.css`,
   données réelles tirées de la réplique via `class_need` — pas de lorem) :
   la vue « classe → 8 » (O2), la pêche avec ses filtres et leurs effets (O4),
   et la variante « émission commune ». Thème clair et sombre.
3. `QUESTIONS-OUVERTES.md` — ce que le PO n'a pas tranché, avec ta
   recommandation pour chaque point.
4. Un plan d'implémentation **en lots** (route `GET /class-need` sur
   eurio-api, page `/besoin`, extension de `build_dino_scope`), chaque lot
   avec son test de vérification et le déploiement VPS qu'il implique
   (skill `eurio-vps-deploy`). Pas de code avant validation du PO.

## Règles de la session

- **Tout chiffre porte sa requête ou son champ.** « 344 classes en review »
  se lit `all_needs(...)`, `bottleneck == 'review'`, daté.
- **Un périmètre qui rate se ferme, il ne s'ouvre pas** (cf.
  `useQueryScope.ts`) — c'est le défaut n°1 des écrans existants.
- **Aucun geste d'écriture au fil d'une lecture.** Enfiler, parquer,
  scraper sont des boutons explicites, jamais un effet de bord d'un affichage.
- Si tu t'apprêtes à inventer un mécanisme de données (statut, table, lane)
  pour servir l'écran : **arrête-toi et propose-le au PO**, c'est une
  décision à consigner dans `DECISIONS.md`, pas un détail de maquette.
- Commence par dire au PO, en dix lignes, ce que tu as compris du problème
  et la première question que tu veux lui poser.
