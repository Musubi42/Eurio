# ADR-004 — Artefacts binaires hors de git, fetchés au build

**Date :** 2026-08-14
**Statut :** 🟡 Proposée — principe validé par le PO, mécanisme non implémenté

## Contexte

`ml/output/` et `ml/datasets/*` sont **gitignorés** (`.gitignore` l.44 et l.57), et
pourtant ~50 Mo d'artefacts binaires y sont **trackés** : ils ont été force-ajoutés
(`git add -f`). Le commit `d1f5812 "Add .pt and .tflite for PC"` dit pourquoi sans détour :

> **git sert aujourd'hui de transport Mac→PC pour les poids.**

`docs/work-in-progress/HANDOFF-pc-full-training.md` confirme : la synchro du PC se fait
par `git fetch && git reset --hard origin/<branche>`.

Conséquences observées :
- `.git` pèse **146 Mo** après avoir été ramené de 1,3 Go à 109 Mo en juin — il a donc
  regrossi d'un tiers en six semaines, principalement par force-add
  (chiffres : [`../architecture/artifacts.md`](../architecture/artifacts.md) §Volumes) ;
- le problème n'est pas la taille absolue mais le **taux** : chaque ré-export du
  détecteur ajoute ~37 Mo **définitifs** à l'historique de **deux** remotes
  (codeberg + github), et rien ne borne le nombre de ré-exports ;
- le dernier commit a embarqué au passage 30 395 lignes d'artefacts de toolchain onnx2tf
  (`schema_generated.py`, `schema.fbs`, rapport de correspondance) — du bruit pur.

Contraintes à respecter :
- **MinIO existe déjà** (`eurio-s3.musubi.dev`) avec un cache read-through éprouvé
  (`ml/shared/storage/local_cache.py`), pensé Mac/PC dès l'origine.
- Le **versioning S3 est banni** (`infra/minio/README.md` §Anti-patterns) : le versionnage
  doit passer par la clé d'objet ou un manifeste.
- Un **précédent existe dans le repo** : `compileFilamentMaterials` (`build.gradle.kts`)
  génère des assets au build, gitignorés — et le `cohort_bundle` a déjà un
  **manifeste sha256 par fichier**, le seul mécanisme vérifié du projet.

## Décision

Sortir de git les artefacts binaires régénérables ou transportables, et les servir
depuis MinIO avec un **manifeste sha256** versionné par la clé d'objet.

Application par étapes, du plus sûr au plus risqué :

1. **Déchets purs** — aucun consommateur, aucun mécanisme requis.
   *Fait le 2026-08-14, commit `05be2dd`* : 6 variantes de quantization du détecteur,
   3 résidus onnx2tf, 2 `labels.cache`. −30 395 lignes, ~33 Mo.
2. **Modèles de l'APK** (`coin_detector.tflite`, `eurio_embedder_v1.tflite`,
   `coin_embeddings.json`, `model_meta.json`) → fetch au build Gradle, sur le modèle de
   `compileFilamentMaterials`. ⚠️ **Qualifier d'abord `test_model.tflite`** (19 Mo, non
   tracké, aucun consommateur identifié) : ne pas le porter dans le nouveau mécanisme
   sans savoir à quoi il sert.
3. **Poids et dataset de détection** (`best.pt`, les 3786 labels) → MinIO, **avec un
   remplacement du transport Mac→PC vérifié sur le PC avant tout `git rm`**.

`app_core.db` **n'est pas dans le périmètre** : `.gitignore` l.37-39 documente un choix
délibéré de le committer (« reproducible builds without Supabase access »). Le sortir
revient sur cette décision — sujet distinct.

## Alternatives considérées

| Option | Verdict |
|---|---|
| Statu quo (git comme transport) | Historique qui enfle sans borne sur 2 remotes : 109 Mo → 146 Mo en six semaines |
| Git LFS | Ajoute un service et un coût ; MinIO est déjà là et déjà utilisé pour les images |
| `ml/state/archive.py` (tarball 500 Mo–1 Go, `ml:export-state-full`) | Existe, mais manuel et grossier — tout ou rien, pas de granularité par artefact |
| **MinIO + manifeste sha256** | Réutilise le cache read-through et le pattern `cohort_bundle` existants |

## Conséquences

**Bonnes**
- Historique git borné ; les ré-exports de modèle ne coûtent plus rien à git.
- Les artefacts gagnent un **sha vérifiable**, qu'ils n'ont pas aujourd'hui.
- Le transport Mac↔PC devient explicite au lieu d'être un effet de bord de git.

**Mauvaises, à assumer**
- ⚠️ **Le premier build après un clone exigera le réseau.** Nuance importante : le cache
  de `local_path()` **est déjà persistant** (retour immédiat si `target.exists()`), donc
  le hors-ligne marche sur cache chaud. Le risque réel est ailleurs : l'**éviction LRU**
  (`_evict_if_needed()`, plafond `EURIO_CACHE_MAX_GB`) peut supprimer un artefact déjà
  téléchargé et casser un build qui fonctionnait la veille. **Décision ouverte : faut-il
  exempter les artefacts de build de l'éviction LRU, ou les stocker hors du cache MinIO ?**
- ⚠️ **Risque de casse silencieuse du PC** : si on retire les poids de git avant que le
  fetch marche, le prochain `reset --hard` les fait disparaître sans erreur ; l'échec
  n'apparaît qu'au premier appel de `ml/vision/normalize_snap.py`.
- ⚠️ **Le nouveau code de fetch ne sera pas testé par défaut** : `ml/tests/conftest.py`
  a une fixture **autouse** qui remplace le client MinIO par un `MagicMock`. Tout test du
  fetch demande un opt-out explicite.
- Sortir les fichiers de l'index ne réduit **pas** `.git` : seul un `filter-repo` ou un
  remaster le fait (cf. [ADR-005](./005-remaster-historique-git.md)).

## Références

- Inventaire complet : [`../architecture/artifacts.md`](../architecture/artifacts.md)
- Plan antérieur, jamais démarré : `docs/work-in-progress/datasets-minio-migration.md`
  (chiffres périmés : parle de 2,5 Go / 8895 fichiers, la réalité est ~50 Mo)
