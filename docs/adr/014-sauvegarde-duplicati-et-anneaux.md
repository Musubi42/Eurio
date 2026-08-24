# ADR-014 — Sauvegarde : Duplicati comme moteur unique, staging applicatif, et cinq anneaux

- **Statut** : ✅ Acceptée
- **Date** : 2026-08-14 · lots 0 à 4 livrés et le lot 6 clos ; **le lot 5 reste 🟡**
  (code fait, monitors à créer — cf. `backup-pipeline/ROADMAP.md`). VPS uniquement
- **Supersède** : `archive/operations/backup-strategy.md` et `archive/operations/backup-pcloud.md`
  (le chemin parallèle `eurio-backup.sh` → pCloud via `rclone crypt`, qui n'a jamais tourné)

## Contexte

Le VPS faisait déjà tourner **Duplicati avec 10 jobs quotidiens** pour les autres
stacks. Eurio en était la seule absente. La bonne question n'était donc pas « quelle
politique inventer » mais « comment y faire entrer Eurio ».

La revue d'ouverture a trouvé bien pire que l'absence d'Eurio : **les 10 jobs
existants n'écrivaient plus rien depuis 3 à 9 mois.** Ils s'exécutaient, échouaient en
`401` depuis le 26 mai, et personne ne l'a su pendant **81 jours**. Le tableau de bord
était vert.

Deux autres exemplaires de la même pathologie ont été trouvés au passage : le
`pg_dump → backup-temp/` d'Authentik est **décrit dans la doctrine mais jamais
exécuté** — aucun `run-script-before`, aucun timer — et son répertoire contient un
unique dump du 8 novembre 2025, re-sauvegardé fidèlement chaque nuit depuis.

C'est ce constat, pas un besoin théorique, qui définit le chantier : **le risque n'est
pas de ne pas sauvegarder, c'est de croire qu'on sauvegarde.**

## Décision

**Duplicati est le moteur unique.** Eurio ne fournit qu'un répertoire de staging ; le
transport, le chiffrement, la rétention et l'historique lui appartiennent.

- **Le staging est produit par du code conscient de l'application.** `eurio.db` (SQLite
  WAL) et MinIO (format objet interne) n'ont pas le système de fichiers pour surface
  valide : copier une base en WAL, c'est la corrompre ; sauvegarder `infra/minio/data`,
  c'est se rendre incapable de calculer le sha256 d'un objet sans réassembler `xl.meta`.
- **MinIO est miroité par l'API S3** (`rclone sync`), pas copié depuis le disque.
- **On capture le store référençant avant le référencé** : les bases d'abord, MinIO
  ensuite. L'ordre inverse produit des *dangling* — une corruption silencieuse à la
  restauration. À la restauration, c'est l'ordre symétrique.
- **Les invariants sont calculés, jamais lus**, et le staging est monté en lecture
  seule dans Duplicati.
- **Cinq anneaux de surveillance**, parce qu'aucun ne couvre l'angle mort du suivant :
  1. les invariants structurels sur le staging ;
  2. un invariant de **fraîcheur** distinct de la non-décroissance — un staging *figé*
     passe tous les autres sans broncher (`eurio.db` n'avait pas été écrit depuis un mois) ;
  3. la plausibilité sémantique, quotidienne et non optionnelle ;
  4. une preuve que **la destination a reçu** (`--send-http-url` de Duplicati vers un
     push monitor) — c'est exactement la panne des 10 autres jobs ;
  5. un check healthchecks.io qui s'acquitte tout seul.
- **Un anneau Push est acquitté par le SILENCE**, jamais par le contenu du ping.
- **Le critère d'acceptation d'une restauration est la suite de tests nocturne**, pas
  « le fichier est là ». Exercice humain trimestriel, surveillé comme un job.
- **Transport pCloud par backend natif OAuth**, jamais WebDAV Basic Auth.
- **Les secrets de restauration vivent dans SOPS**, pas seulement dans Duplicati —
  sinon la clé de déchiffrement est dans la chose à déchiffrer.

**Tout ceci tourne sur le VPS et nulle part ailleurs.** `go-task backup:stage`,
`backup:verify`, `backup:test` dépendent de conteneurs Docker locaux, d'un staging de
6,6 Go et de `infra/backup/notify.conf` — tous gitignorés, donc absents sur Mac/PC. Ne
pas tenter de les lancer ailleurs ni de « réparer » leur absence.

## Alternatives considérées

| Option | Verdict |
|---|---|
| Garder deux dispositifs (un pour Eurio, un pour le reste) | ❌ Deux doctrines, deux endroits à surveiller, deux occasions d'oublier. Le second n'a jamais tourné |
| Pointer Duplicati sur les binds Docker directement | ❌ Copie fichier d'une base en WAL = corruption. Répertoire MinIO = format interne non vérifiable |
| Compter le miroir MinIO local comme deuxième copie du 3-2-1 | ❌ **Faux, et corrigé le jour même** : même disque, même machine, même répertoire parent. Un disque perdu emporte les deux. C'est un tampon de vérification, pas une protection |
| Le versioning S3 de MinIO comme filet | ❌ Délibérément désactivé. Un versionnage d'artefact passe par la clé d'objet ou un manifeste sha256 |
| Se fier au tableau de bord Duplicati | ❌ **C'est précisément ce qui a échoué pendant 81 jours.** Un job vert ne prouve pas que les données sont protégées |

## Conséquences

**Bonnes.** Un moteur unique surveillé vaut mieux que deux moteurs dont aucun ne l'est.
Le quatrième anneau (« la destination a-t-elle reçu ? ») est directement réutilisable
par les 10 autres jobs : c'est le livrable le plus transférable du chantier.

**Mauvaises, et assumées.**

- **6,43 GiB de disque** pour le miroir de vérification (`/opt/eurio` passe de 9,0 à
  ~15,3 Go, sur 85 Go libres).
- ⚠️ **`infra/backup/staging/` contient 6,6 Go de DONNÉES gitignorées sur le VPS.**
  Un `git clean -xdf` les détruit.
- Le parcours d'entraînement n'est sauvegardé **qu'en partie**. Les artefacts publiés le
  sont — `model-artifacts` est dans `MIRROR_BUCKETS` (`infra/backup/eurio-backup.sh:74`),
  donc `best.pt` et le dataset de détection y entrent depuis [ADR-004](./004-artefacts-binaires-hors-git.md).
  Ce qui reste hors filet, c'est le **calcul local** : bakes, manifestes d'itération,
  logs de run, tout ce qui vit sur le disque du Mac ou du PC et n'est jamais publié.
- Anomalie ouverte : `eurio-review` tourne avec les identifiants **root** de MinIO.
- Les `403 Forbidden` du miroir MinIO sont du bruit Cloudflare — c'est écrit pour que
  personne ne les prenne pour une panne.

## Voir aussi

- **Skill `eurio-backup`** — le point d'entrée, y compris le jour J
- Les 32 décisions détaillées, chacune avec ce qu'elle écarte :
  [`../work-in-progress/backup-pipeline/DECISIONS.md`](../work-in-progress/backup-pipeline/DECISIONS.md)
- État, pièges, chiffres de référence :
  [`../work-in-progress/backup-pipeline/HANDOFF-NEXT-SESSION.md`](../work-in-progress/backup-pipeline/HANDOFF-NEXT-SESSION.md)
