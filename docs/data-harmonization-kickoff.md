# Kickoff — Harmonisation des données Eurio

> Brief auto-suffisant pour une session dédiée à **unifier et synchroniser
> la donnée** d'Eurio, aujourd'hui éparpillée sur plusieurs stockages sans
> synchronisation systématique.
>
> Verrouillé 2026-05-22. Déclenché par une découverte du studio bench
> (voir `sources-refacto/ebay-multi-marketplace/bench-studio.md`).
>
> Lire d'abord : `research/data-referential-architecture.md` (schéma du
> référentiel), `research/referential-v2.md` (modèle V2), `DECISIONS.md`.

## Pourquoi ce chantier existe

En auditant le studio bench du theme-matcher, on a découvert que la
commémo BE 2017 « université de Gand » affichait en réalité les données
de **Liège**. Diagnostic : le catalogue a **une seule** entrée 2017
bâclée (slug Ghent + données Liège), alors que le référentiel à jour de
l'admin en a **deux** correctes (Gand + Liège).

Cause racine, dans les mots de l'admin :

> « On a fait des trainings à l'époque, mais à l'époque je n'avais pas
> bien scrappé tout Numista. Là je l'ai refait il y a quelques semaines,
> et du coup je n'ai pas tout synchronisé. »

Le bug n'est ni dans le studio ni dans le matcher : **la donnée du
catalogue est désynchronisée entre ses multiples lieux de stockage.**
Un re-scrape Numista a corrigé la source mais ne s'est pas propagé. Tant
que ce n'est pas réglé, tout ce qui consomme le catalogue (matcher,
bench, training, app) travaille sur une vérité périmée.

## Cartographie de la donnée

Cinq stockages, chacun avec un usage distinct :

| Stockage | Quoi | Format | Rôle |
|---|---|---|---|
| `ml/datasets/sources/` | HTML/JSON bruts scrapés (Numista, BCE) | fichiers | provenance, ré-extractible |
| `ml/datasets/eurio_referential.json` | référentiel canonique (~2628 entrées) | JSON | **censé être** la source de vérité |
| `ml/state/training.db` | DB de travail ML locale (coins, i18n, alias, source_images, image_assets, listings, cohortes, runs…) | SQLite | heavy lifting : scrape eBay, training, bench |
| Supabase | données de l'app en production | Postgres | lecture par l'app Android (clé anon) |
| `app-android/.../catalog_snapshot.json` | catalogue offline packagé dans l'APK | JSON | l'app, hors-ligne |

Plus deux jeux de données dérivés qui s'appuient sur le catalogue :
le **gold du bench** (`ml/state/discovery_bench/`) et les **cohortes
d'entraînement** (`experiment_cohorts` + `ml/state/cohort_csvs/`).

**`eurio_id` est la clé de jointure universelle** entre tous ces
stockages — un identifiant qui change (rename / split / merge) orpheline
mécaniquement tout ce qui en dépend.

## Les flux (tels qu'ils sont censés marcher)

```
  scrape Numista/BCE ──► eurio_referential.json  (canonique)
                              │
              ┌───────────────┼────────────────────┐
              ▼               ▼                    ▼
        bootstrap-coins   sync_to_supabase    (i18n : scrape Numista
        → training.db      → Supabase          TOR séparé → coin_names_i18n)
          .coins              │
                              ▼
                       android:snapshot
                       → catalog_snapshot.json
```

## Les ruptures constatées

1. **Pas de propagation systématique.** Un re-scrape corrige
   `eurio_referential.json` (ou Supabase), mais rien ne garantit que
   `training.db`, Supabase et le snapshot soient régénérés. Ils dérivent
   en silence. (`eurio_referential.json` est daté du 2026-04-26 ; la
   correction 2017 n'y est pas.)
2. **Pas de flux retour.** Les corrections faites côté admin atterrissent
   dans Supabase ; or le flux canonique est `JSON → Supabase`. Le
   canonique peut donc être **en retard sur ses propres dérivés**.
3. **`bootstrap-coins` ne supprime jamais** (`INSERT OR REPLACE`). Un
   eurio_id renommé/splitté laisse l'ancien en orphelin → groupes
   fantômes.
4. **`coin_names_i18n` a un cycle de vie séparé** (scrape TOR autonome) →
   peut désynchroniser de `coins`.
5. **Aucune détection de dérive** — rien ne signale que `training.db` est
   périmé vs le canonique.
6. **Les dérivés figés ne suivent pas les changements d'identité** : gold
   du bench, cohortes, `coin_aliases`, `image_assets`, `coin_embeddings`
   pointent tous des `eurio_id` — un rename/split les orpheline sans
   alerte.

## Contraintes (cadre posé par l'admin)

- **Supabase = données de l'app en production**, et rien d'autre. À
  garder léger (ce dont l'app a besoin pour lire).
- **Le heavy lifting reste sur le PC local** : scrape, training, pipeline
  eBay, traitement d'images. Futur possible : GPU cloud quand le modèle
  passera à 500+ puis des milliers de pièces (euros + centimes). **Jamais
  sur Vercel** — pas d'egress ni de compute facturé là-bas.
- **Vercel n'héberge que le code du front admin**, pas de donnée lourde.
- **Le référentiel JSON doit rester portable** — facile à exporter,
  déplacer, expédier vers un GPU cloud. C'est un atout à préserver.
- Le référentiel **grandit** (nouvelles pièces chaque année) et
  **change** (re-scrape, corrections, fix d'un scrape raté). Le système
  doit absorber ça sans tout casser.
- Les **cohortes d'entraînement** sont une autre forme de donnée :
  sélectionner N pièces → entraîner → pousser la cohorte vers une app de
  QA → juger l'état du modèle. Elles doivent cohabiter proprement.

## Le problème central

Il n'existe pas de **source de vérité unique et imposée**, assortie
d'une **régénération idempotente et documentée** de tous les dérivés. La
donnée est mutée à plusieurs endroits (le re-scrape produit du JSON ;
l'admin édite Supabase) sans réconciliation, et les changements
d'identité ne sont pas gérés.

## Pistes à explorer (à trancher en session)

- **Désigner LE canonique.** Trois candidats : le JSON, Supabase, ou
  `training.db`. Le JSON a la portabilité ; mais les corrections passent
  par l'admin → Supabase. Résoudre cette tension est le cœur du chantier.
- **Génération strictement descendante** : canonique → tous les dérivés,
  idempotente, une commande, ré-exécutable à volonté. Les dérivés ne sont
  jamais édités à la main.
- **Si les mutations se font côté admin/Supabase** : prévoir un flux
  retour explicite Supabase → canonique, OU déplacer l'édition vers le
  canonique.
- **Gérer les changements d'identité** `eurio_id` : un journal de
  migration (rename / split / merge) que les dérivés (gold, cohortes,
  alias, embeddings) rejouent — au lieu de s'orpheliner en silence.
- **Détection de dérive** : une commande / un check CI qui compare
  `training.db` et Supabase au canonique et signale l'écart.
- **Fusion re-scrape ↔ corrections manuelles** : un re-scrape ne doit pas
  écraser une correction humaine — versionner ou marquer la provenance.

## Questions ouvertes pour la session

1. Quel stockage est LE canonique — et comment les corrections faites
   dans l'admin y remontent-elles ?
2. Comment un re-scrape Numista fusionne-t-il avec les corrections
   manuelles sans les clobber ?
3. Quel mécanisme pour les changements d'identité `eurio_id` (le cas
   2017 Ghent : 1 entrée → 2 entrées) ?
4. Comment le gold du bench et les cohortes s'épinglent-ils à une
   version du catalogue, et migrent quand elle change ?
5. Faut-il une notion de **version de catalogue** explicite et estampillée
   sur chaque dérivé ?

## Premier cas concret à régler

La commémo BE 2017. L'ancien `be-2017-2eur-200-years-ghent-university`
doit devenir deux pièces :

- `be-2017-2eur-200-years-of-the-university-of-ghent`
- `be-2017-2eur-200-years-of-the-university-of-liege`

C'est le test grandeur nature du mécanisme de migration d'identité et de
re-synchronisation. Une fois réglé : re-bootstrapper, re-juger les ~28
entrées 2017 du gold (via le ré-étiquetage du studio bench, chunk 3),
re-pointer les `coin_aliases`, re-bencher.
