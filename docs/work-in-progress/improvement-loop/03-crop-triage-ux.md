# Outil « QA crops d'entraînement » par classe (le maillon INSPECT)

> Spéc de la petite amélioration UX qui ferme la boucle : voir les crops d'une
> classe d'un coup, repérer les déchets, les exclure en un clic. Date : 2026-06-30.

> ✅ **CONSTRUIT** (drawer C5 `CohortTrainingQa.vue` + backend `training-crops` /
> `training-eligible`). 🔜 **Raffinements PO demandés (2026-07-01)** — renommage en
> **« Jeu d'entraînement »**, overlay allégé, bordure verte pour les inclus, recrop
> en place + réassignation de classe (réutiliser Review), clarté du R@1 `—`. Tous
> détaillés, prêts à coder, dans le handoff dédié :
> [`04-jeu-entrainement-handoff.md`](./04-jeu-entrainement-handoff.md).

## Le problème UX (concret)

Depuis le contexte lab/cohorte — là où on voit les confusions et les stats par
classe — il n'y a **aucun moyen rapide de parcourir les crops d'une classe** pour
juger leur qualité. La galerie existante (`EnrichmentGallery.vue`) est :
- per-`eurio_id` → il faut naviguer pièce par pièce, hors de la cohorte ;
- au mauvais maille (eurio_id, pas design_group = la classe du modèle) ;
- déconnectée du signal qui dit *quelle* classe inspecter en priorité (le R@1).

Résultat : on entraîne sur des crops qu'on n'a jamais regardés en bloc.

## Principe de design

Ce n'est **pas** une galerie de plus — c'est un **cockpit de triage**. La
discipline (skill frontend-design) : un seul élément signature, le reste calme et
aligné sur les tokens studio-local existants. La signature ici =

> **chaque classe est rangée par « à inspecter en priorité », et chaque crop par
> « suspect d'abord » ; exclure un crop le fait sortir *visiblement* du pool
> d'entraînement, en direct.**

On transforme un grid plat en instrument : la santé du training-set se lit, et
l'action (exclure) a une conséquence visible immédiate (le compteur d'eligible
baisse, le crop se grise).

## Surface

Un nouveau panneau déroulant sur la page cohorte `/lab/cohorts/:id`, sous les
drawers existants : **« QA crops d'entraînement »**. Pattern « déroulant » demandé
— accordéon par classe.

```
┌─ QA crops d'entraînement ────────────────────────────  16 classes · 449 eligible ─┐
│                                                                                   │
│  ▸ it-2016-donatello          28 elig · 0 unknown · R@1 0.33 ●  ← rouge, en tête  │
│  ▸ fr-2016-mitterrand         32 elig · 13 unk    · R@1 0.50 ●                     │
│  ▾ at-2005-state-treaty       91 elig · 33 unk    · R@1 0.67 ◐                     │
│     ┌───────────────────────────────────────────────────────────────────────┐    │
│     │ [img][img][img][img][img][img][img][img]   tri : suspect ▾   ☐ tout    │    │
│     │ [img][img][img][img][img][img][img][img]                                │    │
│     │  ▲ ring orange = face unknown   ▲ ring rouge = quality bas              │    │
│     │  sélection (3) →  [ Exclure du training ]   [ Renvoyer en review ]      │    │
│     └───────────────────────────────────────────────────────────────────────┘    │
│  ▸ de-2007-mecklenburg        34 elig · 0 unk     · R@1 0.75 ◐                     │
│  ▸ ad-2014-standard           17 elig · 0 unk     · R@1 1.00 ○  ← vert, replié     │
│  …                                                                                │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### En-tête de classe (ligne repliée)

Encode l'info, pas de déco : `class_id` (maille design_group), `# eligible`,
`# face-unknown`, **badge R@1 de la dernière itération** (le couplage qui range
les classes — rouge < 0.5, ambre < 0.8, vert sinon). Tri par défaut : R@1
croissant (les pires en tête), puis #unknown décroissant. Les classes vertes
restent repliées — on ne les regarde que si on veut.

### Grille dépliée

- Réutilise le pattern `EnrichmentGallery` (flex-wrap, `<img loading="lazy">`,
  `file_url` promu via `ML_API`, status ring, multi-select, cache-bust `?v=`).
- **Tri des crops** : suspect d'abord — `face!='obverse'`, puis `quality_score`
  bas, puis `denom='not_2eur'`. Le déchet remonte en haut de grille.
- **Signaux visuels** (rings/badges, pas du texte) : ring ambre = face unknown ;
  ring rouge = quality bas / denom not_2eur ; crop déjà exclu = grisé + barré.
- **Canonique en référence** : afficher en tête de grille l'avers canonique
  (`numista-canonical`, CDN public) comme étalon « voici à quoi la classe doit
  ressembler » — repérer l'intrus devient trivial.
- Hover → agrandissement (réutiliser `CoinHoverPreview`). Clic → toggle sélection.

### Actions

- `[ Exclure du training ]` sur la sélection → `training_eligible=0`. Les crops
  se grisent, le compteur eligible de l'en-tête baisse en direct (optimistic).
  **Réversible** (`[ Restaurer ]` sur les exclus).
- `[ Renvoyer en review ]` → `reflag-needs-review` (file review classique).
- Footer cohorte : bandeau « N crops exclus depuis la dernière itération →
  [ Re-bake & ré-entraîner ] » qui lance l'itération fille (ferme la boucle 6→7→1).

## Données nécessaires

### Front
- Composable `useCohortTrainingCropsQuery(cohortId)` → par classe :
  `{class_id, member_eurio_ids[], n_eligible, n_unknown, last_r_at_1, crops[]}`
  où `crops[]` = `{asset_id, source_id, file_url, face, denom, quality_score,
  training_eligible, resolution_status}` triés suspect-first.
- Réutiliser `promoteUrl`, le grid d'`EnrichmentGallery`, les status rings.

### Backend (ML API `:8042`)
1. **Liste crops au maille design_group** (manquant) :
   `GET /lab/cohorts/{id}/training-crops` →, par classe de la cohorte, les crops
   de **tous** les `eurio_id` du design_group (réutiliser `design_group_lot_scope`
   + `COALESCE`). Joindre `last_r_at_1` depuis `per_coin` du dernier
   `benchmark_run` de la cohorte.
   - Alternative minimale : étendre `GET /coins/{eurio_id}/assets` avec un rollup
     design_group, et agréger côté front. Moins propre (N appels).
2. **Toggle eligible au niveau asset** (manquant pour les crops déjà validés hors
   file) : `POST /lab/assets/{asset_id}/training-eligible {eligible: bool}` →
   flippe `training_eligible`, pose `quality_reason='manual_triage'` si exclu,
   `NULL` si restauré. Garde `resolution_status`/`eurio_id`. Réversible.
   - Sinon réutiliser `review-queue/{id}/reject` + `restore`, mais ça force le
     passage par une row review_queue (via `reflag-needs-review`) — plus lourd.

## Découpage proposé (incrémental, testable)

1. **R0a** — backend `GET /lab/cohorts/{id}/training-crops` (rollup design_group +
   couplage R@1) + tests.
2. **R0b** — backend `POST /lab/assets/{asset_id}/training-eligible` + tests
   (idempotent, réversible).
3. **R1** — panneau accordéon `CohortTrainingQa.vue` (en-têtes + tri), réutilise
   le grid d'`EnrichmentGallery` extrait en composant partagé si besoin.
4. **R2** — actions exclure/restaurer (optimistic) + bandeau « re-bake ».
5. **R3** — canonique de référence en tête de grille + signaux rings.

## Non-objectifs (restraint)

- Pas de nouvelle lib (lightbox/masonry) — grid CSS + `<img>` natif, comme le
  reste du repo.
- Pas de proto Vue séparé requis : c'est un outil interne admin, pas une scène
  produit (R1 proto-first ne s'applique pas — cf. `parity-rules.md` §exclusions).
  À confirmer si on veut quand même une passe proto.
- Pas d'édition de crop ici (le re-crop in-place vit déjà dans `EnrichmentGallery`
  / `CircleCropEditor` — on peut lier dessus, pas dupliquer).
