# Juge et banc — savoir qui gagne, et pouvoir le prouver

> Ouvert le **2026-08-25**. Un seul but : rendre le départage ArcFace ↔ DINO
> **mesurable**. Il ne l'était pas, et la raison n'était pas celle qu'on
> croyait.
>
> ✅ **LE DÉPARTAGE EST FAIT — 2026-08-26. ArcFace gagne.** 99,2 % de r@1
> contre 98,1 % pour `dinov2_vitl14`, à **276× moins de paramètres** et **28×
> plus vite**. Indistinguable des deux gros DINO, significativement meilleur
> que `vits14` (`p = 0,00098`). Le document de pilotage, avec les deux réserves
> qui comptent, est **[`SUIVI-MATRICE.md`](./SUIVI-MATRICE.md)** — commence par
> lui, pas par ce README.
>
> 🟢 **Ce que la session du 2026-08-25 avait établi** : la fuite existait, elle
> a été coupée, et **on sait ce qu'elle valait** — +14,7 points sur les photos
> qu'elle avait vues, −4,4 sur les autres (`p = 6,1 × 10⁻⁵` d'un côté). Sept
> lots joués, du corpus retrouvé jusqu'à l'écran qui permet d'y agir. C'est ce
> que raconte la suite de ce fichier, et elle n'a pas été remise à jour depuis :
> **pour l'état courant, va au suivi.**

## L'état, lot par lot

> Mis à jour le **2026-08-25 (nuit)**, après le lot 7. Suite de tests mesurée
> le jour même, **sans pipe** :
>
> ```bash
> cd ml && ./.venv/bin/python -m pytest tests -q -p no:randomly ; echo "exit=$?"
> # 2358 passed, 40 warnings in 98.18s
> # exit=0
> ```
>
> **2358 passed, 0 failed.** Trajectoire de la session : 2258 (avant L1) → 2267
> → 2291 (L2) → 2316 (L3) → 2319 (L4) → 2344 (L5) → 2357 (L6) → **2358** (L7).
> Aucune régression à aucun palier.

| Lot | Ce qu'il a fait | État |
|---|---|---|
| **L0** — [corpus device](./LOT0-CORPUS-DEVICE.md) · [réplication](./LOT0-REPLICATION.md) | Retrouver le corpus (337 photos dans `debug_pull/20260601_154135/`, jamais 2 264), puis le publier | ✅ **joué et PUBLIÉ.** 3 objets dans `model-artifacts`, **130,2 Mo** — donc dans `MIRROR_BUCKETS`, donc dans la sauvegarde |
| **L1** — [conception](./LOT1-CONCEPTION.md) · [import](./LOT1-IMPORT.md) | Le dossier technique de la séparation, puis peupler `scan_corpus.db` | ✅ **joué.** **451 captures** (114 + 337), 2 protocoles étiquetés, manifeste committé sans une seule prédiction |
| **L2** — [fuites](./LOT2-FUITES.md) | Couper les **trois** fuites : centroïdes, split `val`, garde mort | ✅ **joué.** `--val-source` obligatoire en mode lab, `--centroid-source` toujours passé, garde élargi à 3 racines + garde de **contenu** sur `val/`. 4 mutations collées |
| **L3** — [juge](./LOT3-JUGE.md) | Rendre le juge exécutable (`--iteration`), et lisible | ✅ **joué.** `label_space`, `r_at_1_on_covered`, bloc `errors`, refus de comparer deux espaces de labels. 6 mutations |
| **L4** — [préparation](./LOT4-PREPARATION.md) · [résultats](./LOT4-RESULTATS.md) | Deux runs jumeaux, un avec la fuite, un sans | ✅ **joué et MESURÉ.** `027254937193` (A) vs `11b7a626c57a` (B) — **le même réseau au bit près**, donc l'écart est *exactement* la fuite de centroïdes |
| **L5** — [front](./LOT5-FRONT.md) | Voir les photos qui jugent, et pouvoir les remapper / écarter | ✅ **joué**, et **branché au juge** : écarter une photo change le chiffre *et* `corpus_version` |
| **L6** — [quality](./LOT6-QUALITY.md) | `quality_score`, gelée à 5,6 % du parc depuis le 5 juin | ⚠️ **écrit, NON DÉPLOYÉ.** La route `/ingest/quality-scores` n'existe pas encore côté VPS ; la passe réelle n'a pas pu partir |
| **L7** — ce README | Consigner la session, fermer trois gardes cassés | ✅ **joué.** Les deux imports de `ml:augment-textures-check` corrigés, le message de `describe_auto_source` corrigé, le catalogue `eurio-verify` enrichi de 9 entrées |

### Le chiffre du chantier

**La fuite de centroïdes valait +14,7 points sur ce qu'elle avait vu, et −4,4 sur
le reste.** Le global rendait **+0,24 point, `p = 1,0`** — c'est-à-dire « pas de
fuite ».

| Sous-ensemble du juge | frames | A (avec) | B (sans) | A − B | McNemar `b`/`c` | `p` |
|---|---:|---:|---:|---:|---:|---:|
| **avril** — *les photos qui ont fuité* | 102 | **0,9706** | 0,8235 | **+0,1471** | **15 / 0** | **6,1 × 10⁻⁵** |
| **juin** — *jamais vues* | 317 | 0,5804 | **0,6246** | −0,0442 | 29 / 43 | 0,125 |
| **corpus entier** | 419 | 0,6754 | 0,6730 | +0,0024 | 44 / 43 | **1,0** |

⚠️ **Le nombre qui trahit la moyenne est `87 discordantes`** : deux modèles qui
répondent différemment 87 fois sur 451 ne font pas « la même chose ». Détail et
réserves : [`LOT4-RESULTATS.md`](./LOT4-RESULTATS.md).

⚠️ **Ces `r@1` ne sont pas des performances** — 8 epochs dont 3 dégelés, une
couche d'augmentation inerte, un bake différent de celui du 2026-08-16. Ni A ni
B ne doit être promu. Ils prouvent un **mécanisme**.

## Par où commencer

**[`PROBLEME.md`](./PROBLEME.md)** — le défaut posé : le corpus device servait de
split de validation *et* de juge, et les centroïdes contre lesquels il était noté
étaient la moyenne de ses propres photos. Les 6 questions Q1..Q6 y sont listées ;
**Q6 a reçu sa réponse partielle** au lot 4.

**[`MATRICE.md`](./MATRICE.md)** — tout tester : DINOv2 s/b/l, les 18 DINOv3 de
timm, ArcFace, croisés avec fp32/fp16/int8. Poids mesurés, colonnes de schéma
manquantes, spec de la page dédiée. **Rien n'y est encore implémenté** — sa
précondition (un juge propre) vient seulement d'être remplie.

## Ce que la session a fermé, et ce qu'elle a trouvé en chemin

Une dizaine de défauts **muets**, tous vérifiés au code, aucun visible depuis
l'écran. Ils sont entrés au catalogue de la skill
[`eurio-verify`](../../../.claude/skills/eurio-verify/SKILL.md) — c'est là qu'il
faut les relire, pas ici.

1. **Fuite de centroïdes** — le prototype d'une classe était la moyenne de ses photos de test (`pipeline.py` ne passait jamais `--centroid-source`). ✅ fermée (L2), **et chiffrée** (L4).
2. **Fuite de split** — le corpus device remplissait `val/` par défaut implicite. ✅ fermée (L2).
3. **Le garde qui ne gardait rien** — `REAL_PHOTOS_DIR` pointait un répertoire **inexistant**, et ses deux tests fabriquaient leurs chemins sous ce dossier mort. ✅ fermé (L2).
4. **`sync_eval_real` : deux boucles divergentes**, chacune la moitié du contrat — 7 dossiers sur 19 nommés par membre au lieu de leur classe.
5. **`parse_filename` illisible sur le corpus device** — 9 noms d'étape sur 11 rendaient `None`, donc la ventilation `per_condition` du benchmark était vide.
6. **Un paramètre non transporté** — la route acceptait `augmentations_seed` et le runner tirait au hasard. **La scorecard n'affiche pas la graine** : l'expérience aurait été fausse sans trace. ✅ corrigé (L4).
7. **`launch-training` répond `HTTP 200`** en laissant mourir le job sur `readonly database`. ⚠️ **non corrigé** — contourné en mode compute.
8. **Deux pièges SQLite opposés** — `-readonly` échoue en `error 14` sur une base WAL sans `-shm` ; `immutable=1` rend un instantané **périmé** dès qu'un écrivain tourne, `exit=0`, sans message. ✅ consignés ensemble.
9. **La `mtime` du `.db` ment** quand le `-wal` est actif : `.db` à 01:31, `-wal` à 17:21 — seize heures d'écart.
10. **`ml:augment-textures-check` n'a JAMAIS pu garder** — mauvais chemin d'import dans **deux** fichiers. ✅ corrigé (L7).
11. **`pnpm --filter studio-local` ne matche rien** (le paquet s'appelle `eurio-studio-local`) et sort en **succès**.

Et **quatre normaliseurs** cohabitent dans les crops stockés (`hough_tight` 113,
`hough_relaxed` 1, `hough_strict` 280, `hough_loose` 57). `hough_loose` couvre
17 % du pull de juin : noter en `--path fast` mélangerait une différence de prise
de vue et une différence de code. **`--path full` est une condition de validité,
pas une option de performance.**

## ⛔ Ce qui attend le PO

| # | Décision | Où c'est instruit |
|---|---|---|
| 1 | **Les 4 lignes d'`EXTRA_MAPPING`** — mesurées et reproductibles, **jamais validées à l'œil** comme la méthode du remap l'exige. L'écran du L5 est l'outil pour les trancher sur la photo | [`LOT1-IMPORT.md`](./LOT1-IMPORT.md) §6.a, [`LOT5-FRONT.md`](./LOT5-FRONT.md) §8 |
| 2 | **Déployer `eurio-api`** sur le VPS — sans ça `/ingest/quality-scores` n'existe pas et le backfill de 17 678 crops ne peut pas partir | [`LOT6-QUALITY.md`](./LOT6-QUALITY.md) §7 |
| 3 | **Générer les textures d'overlay** — `ml/training/data/overlays/` n'existe pas et n'a jamais été versionné ; la recette `test-3` déclare 3 couches et n'en applique que 2. **Ne pas la jouer à l'aveugle** : elle change le bake | ci-dessous, mesuré |
| 4 | **Supprimer (ou non) les routes `/benchmark/photos/*`** — elles lisent `ml/data/real_photos`, répertoire inexistant, et aucun front ne les consomme. **Non supprimées**, faute de ratification | [`LOT5-FRONT.md`](./LOT5-FRONT.md) §8 |
| 5 | **Q1..Q5 de `PROBLEME.md`** — où marquer le rôle, critère du juge-proxy, prélèvement figé ou rejouable, sort du split `val`, un juge par tâche | [`PROBLEME.md`](./PROBLEME.md) §5, [`LOT1-CONCEPTION.md`](./LOT1-CONCEPTION.md) §8 |
| 6 | **Committer la session** — rien n'a été commité ni poussé, sur aucun lot | `git status --porcelain` |

### Sur le point 3 — la couche d'augmentation inerte, mesurée

⛔ **Les textures n'ont PAS été générées** (le faire hors expérience ferait
diverger un futur run de A et B). Voici l'état, avec sa mesure du 2026-08-25,
code de sortie lu **sans pipe** :

```bash
ls ml/training/data/overlays              # No such file or directory
git log --all -- 'ml/training/data/overlays/*'   # aucun commit

go-task ml:augment-textures-check ; echo "exit=$?"
# | patina       | 0 | missing-dir |
# | dust         | 0 | missing-dir |
# | scratches    | 0 | missing-dir |
# | fingerprints | 0 | missing-dir |
# Total textures: 0
# exit=201     (go-task masque le 1 rendu par sanity_check_textures)
```

**Le répertoire n'existe pas, n'a jamais été versionné, et les 4 familles sont à
0 en `missing-dir`.** La recette `test-3` (`3e022c8bb17a`) déclare trois couches
(`perspective`, `relighting`, `overlays`) ; **seules deux se sont appliquées**,
et le bake l'a dit 36 fois — dans un log de job détaché, où personne ne le lit.

Le remède est une commande (`go-task ml:augment-textures-generate`), **et c'est
au PO de décider quand** : la jouer change le bake, donc rend tout run ultérieur
non comparable à A et à B. Portée pour L4 : A et B ont subi **exactement la même
privation**, la comparaison interne tient.

⚠️ **Ce qui n'est pas établi** : si le PC disposait de ses textures le
2026-08-16, alors son bake n'est pas celui-ci et le `92,4 %` de référence n'est
comparable à rien de ce qui a été produit ici. Non vérifiable depuis le Mac.

## Ce qui a déclenché ce chantier

Le PO voulait un entraînement ArcFace rapide sur un maximum de classes, pour
l'opposer à DINO sur des pipelines comparables. La cohorte s'est composée sans
difficulté — **68 classes prêtes sans un seul geste de review**
(`rich10-68c` = `773ce86bdad2`, préflight `ready=True`, 0 block / 0 warn ; état
au 2026-08-25 : `status=draft`, **0 itération**, mesuré
`SELECT COUNT(*) FROM experiment_iterations WHERE cohort_id='773ce86bdad2'`).
C'est en vérifiant comment le corpus device était consommé que le défaut est
apparu : `prepare_dataset.py:242` en fait le split de validation, et
`benchmark_runs` le juge. Le match était truqué avant d'avoir commencé, sans
que personne l'ait voulu.

## Les livrables attendus

| # | Livrable | État |
|---|---|---|
| 1 | Rôle explicite par image (`train` / `val` / `judge`), respecté par les **deux** voies | 🟡 **conçu, non implémenté** — DDL vérifié pour les deux options, Q1 non tranchée ([`LOT1-CONCEPTION.md`](./LOT1-CONCEPTION.md) §2) |
| 2 | Juge-proxy issu des crops eBay, sous plancher | 🟡 **décidé et différé** ([`PROBLEME.md`](./PROBLEME.md) §3bis) |
| 3 | `encoder_bench_runs` + `quantization` + `eval_corpus` | ⏸️ non commencé ([`MATRICE.md`](./MATRICE.md) §4) |
| 4 | Page matrice dans `studio-local`, `heavy`, DINO **et** ArcFace | ⏸️ non commencé ([`MATRICE.md`](./MATRICE.md) §5) |
| 5 | **Section « images d'évaluation » sur la page coin details** — les voir, **et pouvoir les remapper** | ✅ **livré** (L5), avec le remap, l'avis garder/écarter, et le journal |
| 6 | Entraînement ArcFace sur `rich10-68c`, noté contre un juge propre | ⏸️ non joué — la cohorte reste **non gelée**, aucune itération créée |

⚠️ Le livrable 5 dépendait du livrable 1 « pour ne pas montrer des crops
d'entraînement en les appelant évaluation ». Il a été livré **avant**, et sans le
défaut : il ne montre pas des `image_assets`, il montre `scan_corpus` — un store
qui ne contient **que** des frames de scan. La dépendance était sur la mauvaise
table.

## Les chiffres arbitraires, listés comme tels

Pour qu'on sache lesquels ré-arbitrer quand on aura des mesures.

| Valeur | D'où elle vient | Ce qu'elle vaut |
|---|---|---|
| **≥ 10 crops** pour entrer dans `rich10-68c` | choix du PO, 2026-08-25 | arbitraire assumé — coïncide avec `MIN_REAL` du préflight, ce qui rend la cohorte propre par construction |
| **≥ 15 crops** pour pouvoir céder au juge | choix du PO, 2026-08-25 | arbitraire. Écarte 8 classes de la cohorte. **À raisonner sur le reste, pas sur le prélèvement** (`PROBLEME.md` §4) |
| **5 crops** prélevés par classe | choix du PO, 2026-08-25 | arbitraire. 300 crops au total, ~13 % de la matière d'entraînement |
| **E = 8 epochs** pour les runs A et B | contrainte de budget (90 min sur un M3), mesurée au lot 4 | assumé : les deux runs sont **sous-entraînés**. Établit le signe de l'écart, pas son amplitude à convergence |

## Voisinage

- [ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md) — les deux
  voies, et le D4 : *« le juge unique est le corpus de scan »*. Ce chantier est
  la condition pour que ce D4 veuille dire quelque chose. ⚠️ Son D3 (« les deux
  voies filtrent sur la même condition ») est **à corriger** : elles partagent
  une condition *nécessaire*, `training_eligible = 1`, et divergent sur tout le
  reste — intersection 2888, ArcFace seul 79, DINO seul 1
  ([`LOT1-CONCEPTION.md`](./LOT1-CONCEPTION.md) §1.a).
- [`../scan-sans-retrain/`](../scan-sans-retrain/PREREQUIS.md) — la voie B, le
  banc d'encodeurs existant, et le registre de dette (`FINDINGS.md`).
- [`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md)
  — ✅ **plus bloquant pour le lot 0** : le corpus est répliqué. Son compte a été
  corrigé le 2026-08-25 (**492 frames caméra uniques**, pas 2 264).
- [`../scan-quality/corpus-spec.md`](../scan-quality/corpus-spec.md) — le
  contrat du store et de la scorecard (§8ter : espace de labels et `errors`).
- [`../giga-cohorte/PLAN.md`](../giga-cohorte/PLAN.md) — la cohorte
  `giga-40-vague1`, laissée intacte en `draft`.
- Skills : `eurio-cohort`, `eurio-banque`, `eurio-review`, `eurio-verify`,
  `eurio-data-writes`.
