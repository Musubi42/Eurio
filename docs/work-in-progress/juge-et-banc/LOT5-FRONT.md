# Lot 5 — voir les photos qui jugent, et se faire un avis dessus

> Fait le **2026-08-25** sur le Mac (`Musubi42s-MacBook-Air-Oim`), branche
> `repo-cleanup`. Chaque chiffre porte sa commande. Aucun commit, aucun push,
> rien sur le VPS ni MinIO.
>
> 🟢 **Le fait en une ligne** : la fiche pièce de `studio-local` montre
> désormais les captures device qui **notent** la classe, et on peut agir sur
> chacune — la **remapper** vers la bonne pièce, ou la **garder / écarter**
> pour l'évaluation. Les deux gestes sont journalisés.
>
> ✅ **Branché au juge le même jour** (validation PO) : `replay_corpus` cesse de
> noter les captures écartées, `corpus_version` porte l'ensemble **réellement
> noté**, et la scorecard dit combien ont été écartées et pourquoi. Cf. §9.

---

## 1. Le recadrage du PO, et ce qu'il a défait

La mission initiale demandait d'**étiqueter** chaque vignette par protocole
(`bundle_source`), « deux protocoles cumulés, jamais confondus ». Le PO a
corrigé en cours de lot : *« une photo de val pour une classe, c'est une
photo »*. Les 451 captures forment **un seul pool mélangé**.

Ce qui a été défait : rien de codé — le recadrage est arrivé avant la première
ligne de front. Ce qui a changé dans le plan :

| Prévu | Livré |
|---|---|
| Groupement / filtre par `bundle_source` mis en avant | **Aucun groupement.** `bundle_source` est rendu en détail sous la vignette, comme provenance |
| L'étiquette de protocole comme axe de lecture | L'axe de lecture est l'**avis par photo** (garder / écarter / remap) |
| Une colonne (`class_level_only`) | **Deux familles de colonnes** : le FAIT (`class_level_only`) et l'AVIS (`eval_decision*`) — les confondre ferait écarter des photos exploitables |

Le découpage avril/juin reste **écrit dans `LOT4-RESULTATS.md`** : c'est
l'archive de la mesure de fuite, il y est justifié. Il n'est pas rejoué ici.

---

## 2. Le trou comblé d'abord — `class_level_only`

`remap_bench_golden_set.MAPPING` marque `be-2008-2eur-standard`
`class_level_only=True` : la photo montre une pièce **datée 2011** que le
référentiel ne possède pas. `scan_corpus` n'avait **aucune colonne** pour le
dire. Un écran qui permet de remapper l'aurait fait remapper à l'aveugle.

Migration du store `scan_corpus` (pas du canonique), idempotente
(`ScanCorpusStore._migrate`, lecture de `PRAGMA table_info` — pas d'exception
avalée). Renseignée à l'import, exposée par l'API, affichée sur la vignette.

```bash
cd ml && ./.venv/bin/python -m scripts.import_device_pull \
  --pull ../debug_pull/20260429_170852 --bundle-source device_pull_20260429 --execute
#   be-2008-2eur-standard → be-2008-…-2nd-portrait   [MAPPING (à l'œil)]  🔴 juste à la CLASSE, faux à la PIÈCE
#   🔴 6 capture(s) class_level_only : le label vaut à la classe, pas à la pièce
# seen=114 inserted=0 updated=114 duplicate_bytes=0 no_crop=0 unknown_eurio_id=0

sqlite3 -readonly "file:ml/state/scan_corpus.db?immutable=1" \
  "SELECT class_level_only, COUNT(*) FROM scan_corpus GROUP BY 1;"
# 0|445
# 1|6
```

⚠️ **`sqlite3 -readonly` sans `immutable=1` échoue** sur cette base (WAL,
`error 14`) et le message invite à conclure « base vide ». Forme robuste
ci-dessus. C'est le piège de `LOT1-IMPORT` §1, toujours vrai.

---

## 3. L'avis humain — une colonne, un journal

| Colonne | Nature | Qui l'écrit |
|---|---|---|
| `class_level_only` | **FAIT** sur le label (le référentiel n'a pas la pièce montrée) | l'import, depuis `MAPPING` |
| `eval_decision` (`NULL` / `keep` / `exclude`) | **AVIS** sur l'exploitabilité de la photo | l'humain, par l'écran |
| `eval_decision_by` / `_at` / `_reason` | la trace de l'avis | idem |

Plus une table `scan_corpus_decisions` : `capture_id`, `kind`
(`remap` \| `eval_decision`), `old_value → new_value`, `reason`, `decided_by`,
`decided_at`. **Un remap sans trace est irrattrapable** — c'est le point.

⛔ Un **ré-import n'efface pas l'avis** : `upsert_capture` met à jour les
métadonnées mais laisse `eval_decision*` intact
(`test_reimport_n_efface_pas_l_avis_humain`). Sans ça, rejouer l'import
effacerait en silence le tri du PO.

---

## 4. L'API — `ml/serving/scan_corpus_routes.py`

Montée dans `server.py` à côté de `benchmark_routes`. **Ne joint jamais
`eurio.db` en écriture** ; sa seule lecture du référentiel est le garde-fou.

| Route | Ce qu'elle fait |
|---|---|
| `GET /scan-corpus/captures/{eurio_id}` | Les captures de la **classe**, avec `scope` / `class_kind` / `is_exact_match` |
| `GET /scan-corpus/thumbnail/{capture_id}` | Vignette 256 px (`?kind=raw` pour la photo brute) |
| `POST /scan-corpus/captures/{capture_id}/remap` | Réattribue, refuse un `eurio_id` hors référentiel, journalise |
| `POST /scan-corpus/captures/{capture_id}/eval-decision` | Garde / écarte / rouvre, journalise |

### La maille est **dite**, jamais devinée

```bash
curl -s localhost:8043/scan-corpus/captures/fr-2018-2eur-simone-veil
# scope=coin · class_kind=eurio_id · n_captures=26 · n_exact_match=26
# bundle_source : {device_pull_20260601: 20, device_pull_20260429: 6}

curl -s localhost:8043/scan-corpus/captures/fr-1999-2eur-standard-1st-map
# scope=design_group · class_id=fr-2euro-standard-t1 · n_captures=6 · n_exact_match=0
# « Ces photos jugent le GROUPE DE DESSIN … certaines montrent une autre pièce du groupe. »
```

**6 captures, 0 de la pièce demandée.** Sans ce bandeau, l'écran aurait montré
les photos de la 2ᵉ carte sous le nom de la 1ʳᵉ.

### Extraction, pas copie (R0)

Le triptyque `_thumbnail_path` / `_ensure_thumbnail` /
`cleanup_expired_thumbnails` de `benchmark_routes.py` est extrait vers
**`ml/serving/thumbnails.py`** (`ThumbnailCache` paramétré par sa racine +
`safe_child`). `benchmark_routes` délègue, `server.py` nettoie les **deux**
caches au boot. Le copier aurait laissé deux TTL diverger et un seul cache
nettoyé.

---

## 5. Les gardes, et leur mutation

Chaque garde a été **désarmé** pour vérifier qu'un test rougit.

### Garde-fou référentiel (même garde qu'à l'import)

```bash
curl -s -X POST localhost:8044/scan-corpus/captures/06b1bd1a53902893/remap \
  -H 'Content-Type: application/json' -d '{"eurio_id":"xx-9999-2eur-inexistante"}'
# {"detail":"eurio_id absent du référentiel: xx-9999-2eur-inexistante"}   HTTP 400
```

Mutation — la vérification `resolver.for_eurio(new_id) is None` retirée :

```
FAILED tests/test_scan_corpus_routes.py::test_remap_refuse_un_eurio_id_absent_du_referentiel
E   assert 200 == 400
1 failed, 17 passed
```

Référentiel injoignable → **503**, pas une écriture à l'aveugle.

### Traversée de chemin — ⚠️ le 400 attendu n'arrive pas par le chemin annoncé

La mission attendait
`curl .../scan-corpus/thumbnail/../../etc/passwd` → **400**. Mesuré :

```bash
curl -s -o /dev/null -w '%{http_code}\n' --path-as-is "localhost:8043/scan-corpus/thumbnail/../../etc/passwd"   # 404
curl -s -o /dev/null -w '%{http_code}\n'              "localhost:8043/scan-corpus/thumbnail/..%2F..%2Fetc%2Fpasswd" # 404
curl -s -o /dev/null -w '%{http_code}\n' --path-as-is "localhost:8043/scan-corpus/thumbnail/.."                  # 400
```

**404, pas 400 — et ce n'est pas un défaut.** Starlette n'apparie
`{capture_id}` que sur **un** segment : un `../..` multi-segment n'atteint
jamais le handler, il n'y a pas de route. Le garde est éprouvé sur ce qui
l'atteint vraiment — un `..` nu → **400**. Deuxième garde, indépendant :
`safe_child` sur le chemin **stocké en base** (une ligne au `raw_path` sortant
de `frames_root` ne sert rien).

Mutation — le test `".." in capture_id` retiré de `_sanitize_capture_id` :

```
FAILED tests/test_scan_corpus_routes.py::test_thumbnail_refuse_la_traversee
E   Failed: DID NOT RAISE <class 'fastapi.exceptions.HTTPException'>
1 failed, 17 passed
```

### Le drapeau `class_level_only` à l'import

Mutation — `class_level_only=f.class_level_only` retiré de l'`ScanCapture` :

```
FAILED tests/test_import_device_pull.py::test_import_pose_le_drapeau_sur_les_captures_concernees
1 failed, 9 passed
```

### Le reste

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8043/scan-corpus/captures/inexistant   # 404
curl -s -o /dev/null -w '%{http_code}\n' localhost:8043/scan-corpus/thumbnail/06b1bd1a53902893  # 200
```

---

## 6. Le front — gating au COMPOSANT, jamais à la route

| Fichier | Rôle |
|---|---|
| `components/EvalImagesSection.vue` | **Gate + fetch.** `<section v-if="HAS_LOCAL_ML_API">` |
| `components/EvalImagesVue.vue` | Le **rendu**, sans réseau — c'est lui que monte la maquette |
| `composables/useScanCorpus.ts` | Types + fetchers, promotion des URL vers `:8042` |
| `fixtures/eval-images.mock.ts` | 6 états, dont les 3 qui ne se commandent pas en base |
| `pages/EvalImagesMaquettePage.vue` | `/coins/eval-images/maquette`, **hors nav**, sans réseau |

🔴 **La route `coins/:eurio_id` n'est PAS `meta: { heavy: true }`** et ne doit
pas le devenir : elle griserait **toute** la fiche pièce en mode hébergé, alors
que seule cette section tape `:8042`. Le gating est au composant.

Point d'accroche : `pages/CoinDetailPage.vue`, juste après
`<DinoReferencesSection>`.

Sur chaque vignette : la **condition** en surimpression, l'avis (gardée /
écartée), le fait (`⚠ classe seule`, `autre pièce du groupe`), et la
**provenance** en pied (`device_pull_20260601 · hough_strict` + date). Clic sur
l'image = bascule crop ↔ raw. Couleurs par tokens (`var(--success)`,
`var(--danger)`, `var(--warning)`) — aucune couleur en dur (R2).

Les 6 états de la maquette : classe fournie · groupe de dessin (0 photo de la
pièce) · classe seule (le cas belge) · vide · chargement · erreur.

### Le filet, tel qu'il est

⚠️ **Il n'existe aucun test unitaire dans `studio-local`**, et
`admin/packages/parity/` ne fait que des screenshots sans assertions. Le filet
est `vue-tsc --noEmit` + **l'œil du PO**. Rien n'a été fabriqué pour en faire
croire davantage.

```bash
cd admin && pnpm -C packages/studio-local build ; echo "exit=$?"
# ✓ built in 4.12s
# exit=0
```

⚠️ `pnpm --filter studio-local build` **ne matche rien** : le paquet s'appelle
`eurio-studio-local`. Utiliser `pnpm -C packages/studio-local build` (ou
`--filter eurio-studio-local`).

---

## 7. La suite complète

```bash
cd ml && ./.venv/bin/python -m pytest tests -q -p no:randomly ; echo "exit=$?"
# 2339 passed, 40 warnings in 96.45s      ← après le front + les routes
# 2344 passed, 40 warnings in 108.81s     ← après le branchement au juge (§9)
# exit=0
```

Baseline annoncée : **2319**. +25 = 18 tests neufs
(`tests/test_scan_corpus_routes.py`) + 2 ajoutés à
`tests/test_import_device_pull.py` + 5 ajoutés à
`tests/test_replay_corpus.py`. **0 failed.**

---

## 8. Reste-à-faire, et ce qui attend le PO

### ✅ Le juge filtre — levé le 2026-08-25 (cf. §9)

`scripts/replay_corpus.py` n'ignore plus `eval_decision`. Écarter une photo à
l'écran change désormais le chiffre — et fait changer `corpus_version`.

### 🔴 Décision PO en attente (héritée de `LOT1-IMPORT` §6.a)

Les 4 lignes d'`EXTRA_MAPPING` restent **mesurées, pas validées à l'œil**.
L'écran livré ici est précisément l'outil qui permet de les trancher sur la
photo. Les valider = les déplacer vers `MAPPING` avec leur `reason`.

### ⚠️ Routes mortes signalées, non supprimées

`GET /benchmark/photos/*` (`ml/serving/benchmark_routes.py:266,301` avant
extraction) lisent `ml/data/real_photos`, **répertoire inexistant**, et aucun
front ne les consomme. **Non supprimées** — le PO ne l'a pas ratifié. Elles
partagent maintenant le cache de vignettes extrait, donc leur suppression sera
un geste local.

### ⚠️ Le juge et la maille

`scope=design_group` veut dire que la notation à la **pièce** de cette classe
est impossible avec ces photos. Les 6 captures `class_level_only` sont dans le
même cas. Rien ne le refuse aujourd'hui côté juge.

### Vérification faite sur des instances jetables

L'API `:8042` du poste **n'a pas été redémarrée** (elle tourne en mode normal,
réplique read-only, sans `--reload`). Les vérifications ont tourné sur
`:8043` (lecture) et `:8044` (écritures, sur une **copie** de
`scan_corpus.db`), toutes deux arrêtées ensuite. **La base réelle est
inchangée** hors le backfill de `class_level_only` :

```bash
sqlite3 -readonly "file:ml/state/scan_corpus.db?immutable=1" \
  "SELECT COUNT(*) FROM scan_corpus; SELECT COUNT(*) FROM scan_corpus_decisions;"
# 451
# 0
```

➡️ **Pour voir l'écran branché, il faut relancer `:8042`** (le router n'y est
pas chargé). La maquette, elle, marche sans API :
`/coins/eval-images/maquette`.


---

## 9. L'exclusion branchée au juge — et le piège qu'elle ouvre

> Ajouté le **2026-08-25** après validation du PO : *« sans ça, l'écran donne
> l'illusion d'agir »*.

### 9.1 🔴 Ce que brancher l'exclusion casse, si on n'y prend pas garde

Exclure des captures rend le jeu noté **dépendant d'une décision humaine
mutable**. Deux runs à deux jours d'écart peuvent noter des ensembles
différents. C'est **exactement** le défaut que `review.bench_gold` a été écrit
pour tuer : *« deux runs à deux semaines d'écart ne mesuraient pas la même
chose, et rien ne le signalait »*.

**Donc `corpus_version` est calculée sur l'ensemble RÉELLEMENT noté**, après
exclusion — jamais sur le pool brut. Sinon deux scorecards porteraient la même
version en ayant noté des jeux différents, et ce serait **indétectable**.

Vérifié par la mesure, sur le corpus réel, candidat `caf98145032c`, `--path
full` :

```bash
cd ml && direnv exec .. ./.venv/bin/python -m scripts.replay_corpus \
  --iteration caf98145032c --path full --conditions close_plain --out <out>
# Corpus : 19 frames (version 8632e59be288) — chemin full

curl -s -X POST localhost:8042/scan-corpus/captures/69d3a5f8698ac502/eval-decision \
  -H 'Content-Type: application/json' \
  -d '{"decision":"exclude","reason":"L5 : demonstration de la mutabilite du juge"}'

# … même commande de replay …
# Corpus : 18 frames (version c27caad52f6d)
# ⚖️  Écartées à la main : 1 capture(s), NON notées.
#       1× L5 : demonstration de la mutabilite du juge
```

| Run | `corpus_version` | `n_frames` | `excluded` |
|---|---|---:|---|
| avant | `8632e59be288` | 19 | `active:true, n:0` |
| après exclusion | **`c27caad52f6d`** | 18 | `active:true, n:1, by_reason:{…:1}` |
| `--include-rejected` | `8632e59be288` | 19 | `active:false, n:1` |

**La version a bougé, et elle revient à l'identique** quand on remet la capture
dans le jeu : c'est une fonction de l'ensemble noté, pas un compteur qui
avance.

Puis l'avis a été **rouvert**, et le journal porte les deux gestes :

```
2026-08-25T21:06:28+00:00 | eval_decision | None → exclude | agent-L5 | L5 : demonstration de la mutabilite du juge
2026-08-25T21:06:55+00:00 | eval_decision | exclude → None | agent-L5 | L5 : demonstration terminee, avis rouvert
```

Le corpus est revenu à son état de départ : **451 captures, 0 `eval_decision`
posée**, 2 lignes de journal (la trace, elle, ne s'efface pas).

### 9.2 Conception

- **Défaut = exclusion ACTIVE.** `--include-rejected` existe pour le
  diagnostic ; l'inverse n'existe pas. Une photo que le PO a écartée ne doit
  pas juger — c'est le sens de son geste.
- **Le prédicat vit dans le SQL du store, et nulle part ailleurs.**
  `replay_corpus` fait **deux** lectures du même filtre (`list_captures(...)` et
  `list_captures(..., exclude_rejected=True)`) et **dérive** la différence. Le
  ré-implémenter en Python le ferait diverger le jour où `eval_decision` gagne
  une troisième valeur.
- **La scorecard le dit** : bloc `excluded {active, n, by_reason, capture_ids}`
  à côté de `label_space`, plus `filter.include_rejected`. Un `n` qui baisse
  sans explication est un `n` qui inquiète. Le bloc reste rendu quand le filtre
  est désarmé (`active: false`) — c'est justement là qu'il faut le voir.
- **Tout écarter échoue franchement** au lieu de rendre un r@1 sur zéro frame,
  et le message dit pourquoi le corpus est vide.

### 9.3 Mutations

```
# captures = pool  (l'exclusion rendue inopérante)
FAILED tests/test_replay_corpus.py::test_juge_ne_note_pas_les_captures_ecartees
FAILED tests/test_replay_corpus.py::test_corpus_version_porte_l_ensemble_REELLEMENT_note
FAILED tests/test_replay_corpus.py::test_include_rejected_remet_la_capture_et_le_dit
FAILED tests/test_replay_corpus.py::test_tout_ecarter_echoue_franchement
4 failed, 13 passed

# version = corpus_version([... for c in pool])  (version sur le POOL BRUT)
FAILED tests/test_replay_corpus.py::test_corpus_version_porte_l_ensemble_REELLEMENT_note
FAILED tests/test_replay_corpus.py::test_include_rejected_remet_la_capture_et_le_dit
2 failed, 15 passed
```

### 9.4 🔴 Piège de vérification neuf : `immutable=1` **ignore le WAL**

`LOT1-IMPORT` §1 recommande `sqlite3 -readonly "file:…?immutable=1"` — c'était
juste tant que **personne n'écrivait**. Depuis que l'API `:8042` écrit dans
`scan_corpus.db`, cette forme lit le fichier principal **sans son `-wal`** et
sous-compte en silence :

```bash
sqlite3 -readonly "file:ml/state/scan_corpus.db?immutable=1" \
  "SELECT COUNT(*) FROM scan_corpus_decisions;"
# 0        ← FAUX, exit=0
sqlite3 "file:ml/state/scan_corpus.db?mode=ro" \
  "SELECT COUNT(*) FROM scan_corpus_decisions;"
# 2        ← le vrai compte, exit=0
```

**Deux zéros également plausibles, aucun message, exit 0 des deux côtés.** La
règle devient :

| Situation | Forme à utiliser |
|---|---|
| Aucun écrivain (base au repos, pas de `-shm`) | `-readonly "file:…?immutable=1"` |
| Un écrivain possible (`:8042` tourne) | `"file:…?mode=ro"` — lit le WAL |

Le symptôme est **muet au sens de `eurio-verify`** : il ne dit pas « je n'ai
pas lu le WAL », il rend un nombre.
