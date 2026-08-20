# Le corpus de scan doit survivre à la machine qui le produit

> Écrit le 2026-08-20. **Rien n'est implémenté.** Ce doc pose un problème
> soulevé par le PO — « des photos sur device j'en ai déjà fait énormément, si
> tu me dis qu'il y en a 0 c'est qu'on les a perdues » — et le corrige sur un
> point : **elles ne sont pas perdues, elles sont non protégées.**
>
> Voisins : [`corpus-spec.md`](corpus-spec.md) (le store),
> [`../scan-sans-retrain/PROTOCOLE-CAPTURE.md`](../scan-sans-retrain/PROTOCOLE-CAPTURE.md)
> (le plan de prise de vue), [`../backup-pipeline/`](../backup-pipeline/) (la
> chaîne de sauvegarde existante).

## 1. Ce qui existe réellement, mesuré le 2026-08-20

```bash
find ml/datasets/eval_real_norm -type f \( -name '*.jpg' -o -name '*.png' \) | wc -l
# 114          (19 classes, 2,5 Mo)

find debug_pull -type f -name '*.jpg' | wc -l
# 2150         (+ 812 .json, 80 Mo au total)

ls -la ml/state/scan_corpus.db
# 0 octet      ← le store dédié, vide
```

**2 264 images device existent sur ce Mac.** Le « 0 photo » que je répétais
depuis hier désignait le **store versionné** (`scan_corpus.db`), pas la matière
première. C'était juste sur la lettre et faux sur le fond : la matière existe,
elle n'est simplement ni labellisée ni versionnée ni protégée.

### Ce qu'elles valent, et ce qui leur manque

| Jeu | Volume | Labellisé ? | Conditions tracées ? |
|---|---:|---|---|
| `eval_real_norm` | 114 img / 19 classes | oui (par dossier de classe) | non |
| `debug_pull` | 2 150 frames | **non** — les `capture_*.txt` portent la *prédiction* du modèle, pas la vérité | non |
| `scan_corpus.db` | 0 | — | le schéma les prévoit (`glare`, `inhand`, …) |

Les 2 150 frames de `debug_pull` sont le gisement intéressant : ce sont de
**vraies frames de caméra en conditions réelles**, celles-là mêmes qui ont servi
à débugger le pipeline de détection. Elles ne demandent qu'une annotation pour
devenir un corpus. ⚠️ **estimation** : leur diversité de classes et de
conditions n'a pas été mesurée — une bonne part vient probablement d'un petit
nombre de pièces posées sur un bureau.

## 2. Le vrai problème : rien de tout ça n'est protégé

```bash
git check-ignore -v ml/datasets/eval_real_norm debug_pull
# .gitignore:54   ml/datasets/*    ml/datasets/eval_real_norm
# .gitignore:221  debug_pull/      debug_pull
```

Les deux sont **gitignorés** — à raison, ce sont des données binaires. Mais :

- **elles ne sont sur aucun MinIO** (aucune tâche `publish`/`upload` ne les
  vise, vérifié sur `Taskfile.yml` et `ml/tasks.yml`) ;
- **la chaîne de sauvegarde ne les voit pas** : `CLAUDE.md` est explicite —
  `backup:stage` / `verify` / `test` **ne tournent que sur le VPS** et
  dépendent de conteneurs locaux au VPS. Tout ce qui vit sur le Mac est hors
  périmètre ;
- et `CLAUDE.md` porte déjà l'avertissement qui décrit exactement le risque :
  *« un `git clean -xdf` les détruit »*.

**Conclusion : la seule copie de 2 264 images device est sur un disque de
portable, sans réplique.** Un `git clean -xdf`, un disque mort, un `rm` mal
visé, et le travail est à refaire. C'est ce que le PO redoute, et il a raison
de le redouter avant d'en produire 985 de plus.

Le futur `ml/state/scan_corpus/frames/` aura exactement le même statut — le
store est décrit comme « PC-only, totalement isolé, gitignoré ». Isolé du
pipeline canonique, oui. Isolé de la sauvegarde aussi.

## 3. Ce que le projet sait déjà faire, et qu'il suffit de brancher

Rien n'est à inventer. Trois mécanismes existent :

1. **MinIO** (`eurio-s3.musubi.dev`) est déjà le domicile des images du projet —
   raws, crops, canoniques, artefacts de modèle. Un bucket de plus n'est pas un
   chantier.
2. **Le patron `ml:assets:publish` / `ml:assets:fetch`** : publier au bucket,
   épingler les sha256 dans un manifeste committé (`shared/model-assets.json`),
   re-télécharger au besoin. C'est exactement la forme dont un corpus a besoin —
   **les octets dehors, l'inventaire vérifiable dans git.**
3. **La chaîne de sauvegarde du VPS** (chantier `backup-pipeline`, lots 0 à 5
   livrés) couvre déjà MinIO. Un corpus **dans** MinIO hérite de la sauvegarde ;
   un corpus sur le Mac n'héritera jamais de rien.

C'est le point qui rend ce chantier petit : **il n'y a pas de sauvegarde
Mac à construire. Il y a un chemin à emprunter — MinIO — et la sauvegarde suit.**

## 4. La règle à graver

> **Une capture qui n'est pas dans MinIO n'existe pas.**

Corollaire de conception : l'upload doit être **dans le geste de capture**, pas
une étape « à faire plus tard ». Une étape séparée sera oubliée un soir de
fatigue, précisément après la session la plus longue.

## 5. Les questions à trancher dans la session dédiée

- **Le point d'upload.** Au moment de l'import du bundle cohort-test dans
  `scan_corpus` (une seule porte, facile à verrouiller), ou directement depuis
  le téléphone (plus robuste à la perte du Mac, mais nouveau chemin réseau à
  écrire côté Android) ?
- **Le manifeste.** Committer un inventaire `capture_id → sha256 → clé MinIO`
  sur le patron de `model-assets.json` ? Ça donne une vérification d'intégrité
  et un moyen de reconstituer le corpus sur une autre machine. Le
  `capture_id` est déjà `sha256(raw_bytes)[:16]` — le contenu est donc **déjà
  adressable par son hash**, la moitié du travail est faite.
- **Le sort de `debug_pull`.** 2 150 frames non labellisées : on les annote et
  on les verse au corpus, ou on les archive brutes en attendant ? Mesurer
  d'abord leur diversité réelle (classes distinctes, conditions) — si elles
  couvrent 5 pièces sur un bureau, elles ne valent pas l'annotation ; si elles
  couvrent 30 classes en conditions variées, c'est plusieurs sessions de
  capture déjà faites.
- **Le sort de `eval_real_norm`.** 114 images labellisées par classe : à verser
  au corpus avec `condition` inconnue, ou à re-capturer proprement ? Elles ont
  servi de jeu d'éval historique (les « 317 snaps » cités dans `VISION.md`
  désignent un comptage antérieur, non reproduit ici — écart non expliqué).
- **La rétention.** Un corpus est append-only et ne se purge pas. Vérifier que
  la politique de cycle de vie MinIO ne s'appliquera pas à ce bucket.

## 6. Ce que ça change pour le plan de capture

Le [`PROTOCOLE-CAPTURE.md`](../scan-sans-retrain/PROTOCOLE-CAPTURE.md) prévoit
**985 captures sur 80 classes en 11 sessions**. Deux conséquences :

- **Ne pas lancer la campagne avant que le chemin de durabilité existe.** Le
  contrôle bloquant du protocole (`sampled=False`, 400 tests, 80 classes) doit
  gagner une quatrième ligne : *les captures de la session précédente sont-elles
  dans MinIO ?*
- **La première session sert aussi à tester le chemin.** Trois sessions
  (~290 captures) donnent déjà un signal et attrapent une erreur de protocole
  tant qu'elle est réparable — c'est aussi le bon moment pour vérifier que
  l'aller-retour MinIO fonctionne, sur 96 images plutôt que sur 985.

## 7. Une correction à porter ailleurs

J'ai écrit et répété que le corpus de scan valait « 0 photo ». C'est vrai du
store versionné et faux de la matière : **2 264 images device existent**. La
formulation juste est *« 0 capture versionnée, 2 264 images non protégées »*.
À corriger dans [`../scan-sans-retrain/PREREQUIS.md`](../scan-sans-retrain/PREREQUIS.md)
§P5 lors de la prochaine passe de doc.
