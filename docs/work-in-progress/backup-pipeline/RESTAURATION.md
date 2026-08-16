# Restauration d'Eurio

> Restaurer Eurio n'est pas « remettre des fichiers en place ». C'est rétablir **deux
> stores dans un état mutuellement cohérent**, dans un ordre imposé par les dépendances,
> puis le **prouver**.
>
> **Statut au 2026-08-16 : la procédure a été exécutée de bout en bout.** 6,470 GiB
> rapatriés depuis pCloud, invariants verts sur la copie (16/18, 2 avertissements
> attendus), puis **stack remontée sur la copie restaurée** (§1 étapes 2 à 7) —
> `eurio-api` et `eurio-review` servent la donnée, et un crop traverse
> DB → URL signée → MinIO restauré avec un sha256 conforme. C'est le niveau 4 de
> [`VERIFICATION.md`](./VERIFICATION.md) §2. Le harnais est rejouable :
> [`infra/backup/drill/`](../../../infra/backup/drill/README.md). Les commandes de
> récupération vivent dans
> [`README-RESTORE.md`](../../../infra/backup/README-RESTORE.md), corrigé *par*
> l'exercice — c'était son but.

## 1. Ordre de restauration

L'ordre n'est pas négociable : chaque étape dépend de la précédente.

| # | Étape | Dépend de | Piège |
|---|---|---|---|
| 1 | `git clone` → code, compose, secrets SOPS | — | La clé age SOPS doit être présente sur la machine (`~/.config/sops/age/keys.txt`) |
| 2 | **Régénérer** `infra/minio/secrets` et `infra/review/secrets` **depuis SOPS** | 1 | ✅ Plus de dépendance à Duplicati depuis le 2026-08-16 (**D-29**). Les 6 valeurs sont dans `secrets/dev.env` : le clone + la clé age suffisent |
| 3 | Démarrer MinIO **vide**, puis `infra/minio/bootstrap.sh` | 1, 2 | Crée les buckets et les policies. Restaurer des objets sans les policies donne un MinIO que l'app ne peut pas lire |
| 4 | `rclone sync staging/minio/<bucket> → minio:<bucket>` | 3 | **Le store référencé d'abord** (cf. [`DONNEES.md`](./DONNEES.md) §3) |
| 5 | Poser `eurio.db` et `review.db` dans les binds | 2 | Ne **pas** restaurer de fichiers `-wal` / `-shm` : le `VACUUM INTO` produit une base autonome et propre |
| 6 | Démarrer `eurio-api` et `eurio-review` | 4, 5 | |
| 7 | **Exécuter la suite d'invariants** | 6 | C'est le critère d'acceptation, pas une formalité |

**Étape 4 avant étape 5** est la règle miroir de celle de la sauvegarde : à la
sauvegarde on capture le référençant d'abord, à la restauration on rétablit le référencé
d'abord. Dans les deux sens, le décalage ne peut produire que des orphelins, jamais des
dangling.

## 2. L'étape 7 est le cœur du dispositif

Le critère de réussite d'une restauration est **la suite d'invariants de
[`VERIFICATION.md`](./VERIFICATION.md) §3**, la même qui tourne chaque nuit.

Conséquences voulues :

- une restauration ne peut pas être déclarée réussie « à l'œil » ;
- la suite de tests ne peut pas diverger de ce qu'elle est censée valider, puisqu'elle
  sert aux deux ;
- si un invariant est trop faible pour attraper une restauration ratée, on le découvre
  lors de l'exercice, pas le jour de l'incident.

Un invariant supplémentaire est spécifique à la restauration : **le nombre de dangling
après restauration doit être identique à celui du `manifest.json`**, pas seulement nul.
Un écart signale une restauration partielle des objets.

## 3. Ce qui manque encore à cette procédure

À compléter au lot 6, par l'exercice lui-même :

- [x] ✅ **La commande exacte de restauration** — trouvée et exécutée le 2026-08-16 :
      `duplicati-cli repair` puis `duplicati-cli restore`, destination et passphrase
      passées par `--parameters-file` (jamais dans `argv`). Détail et pièges dans
      [`README-RESTORE.md`](../../../infra/backup/README-RESTORE.md) §4 et §6.
- [x] ✅ **Où trouver la passphrase Duplicati sans le VPS** — résolu le 2026-08-16
      (**D-28**). `DUPLICATI_EURIO_PASSPHRASE` et `DUPLICATI_PCLOUD_AUTHID` sont dans
      `secrets/dev.env` (SOPS+age), et la passphrase est vérifiée identique à celle du
      password manager. Découverte au passage : **aucun des 11 jobs ne sauvegarde
      `/opt/eurio` ni la config Duplicati** — la clé ne vivait que sur la machine
      qu'elle est censée pouvoir remplacer.
- [x] ✅ **Le temps réel de restauration** — 2026-08-16 : **30 min 58 s** pour 33 957
      fichiers / 6,470 GiB, plus ~4 min de reconstruction d'index et ~1 min de lecture
      des versions. Compter ~40 min pour récupérer la donnée.
- [x] ✅ **Les policies MinIO attendues par `eurio-api`** — `eurio-app-policy` du dépôt
      suffit, vérifiée le 2026-08-16 de bout en bout : `eurio-api` a signé une URL de
      crop, l'objet a été servi, et ses octets sont ceux du fichier restauré. Deux
      gestes manuels restent nécessaires : `mc mb local/eurio-db` (bucket legacy que
      `bootstrap.sh` ne crée pas, D-20), et **écrire les objets avec le compte
      `eurio-app`, jamais le root** — sinon l'exercice valide un chemin de permissions
      que la production n'emprunte pas (D-30).
- [x] ✅ **Réseaux Docker** — un exercice n'a **pas** besoin de `traefik` : la stack
      jetable a son propre réseau, ce qui est aussi sa barrière d'isolation. En
      revanche `bootstrap.sh` exige `traefik` (il refuse de démarrer sinon) : pour une
      vraie remise en production, le réseau doit exister avant, et pour l'exercice on
      passe `MINIO_SKIP_COMPOSE=1`.
- [x] ✅ **`eurio-api` ne rejoue rien** sur une base restaurée : au démarrage,
      `db_migrate: no pending migration (5 already applied)`. La base restaurée porte
      déjà son état de migration, il n'y a pas de fenêtre où un schéma serait modifié
      sous les pieds de la restauration.
      ⚠️ Deux routers ne montent pas dans l'image de production (`referential` sans
      `PIL`, `review_queue` sans `cv2`) — pré-existant, sans rapport avec la
      restauration, mais à ne pas prendre pour un symptôme le jour J.
- [x] ✅ **`bootstrap.sh` recrée la configuration MinIO** — vérifié le 2026-08-15.
      Le miroir par API S3 capture les objets, jamais `.minio.sys/` (users IAM, service
      accounts, policies). `bootstrap.sh` reconstruit bien : buckets, `anonymous set
      download` sur `numista-canonical`, `version suspend`, utilisateur `eurio-app`,
      policy `eurio-app-policy` depuis `infra/minio/policies/`, et son attachement.
      **Sous une condition** : `infra/minio/secrets/` doit être restauré d'abord — c'est
      lui qui porte les identifiants, et `bootstrap.sh` les *régénère* s'ils sont
      absents, ce qui produirait un MinIO fonctionnel mais avec des identifiants que
      `eurio-api` ne connaît pas. Le nœud reste donc la session « secrets » (D-09).

      ⚠️ **Deux écarts entre `bootstrap.sh` et la réalité du serveur**, à connaître
      avant de restaurer :
      `bootstrap.sh` crée `model-artifacts`, qui **n'existe pas encore** sur le serveur
      (ADR-004, mécanisme livré, bascule en attente) ; et il ne crée **pas** `eurio-db`,
      qui existe et dont on miroite `transfers/` (cf. [D-20](./DECISIONS.md)). Restaurer
      ce bucket demande donc un `mc mb` manuel.

**Chaque case non cochée est une raison de plus de faire l'exercice tôt.** Une procédure
de restauration écrite mais jamais exécutée est exactement la même illusion que le
dispositif du 17 juin.

## 4. Protocole de l'exercice trimestriel

> Règle du jeu : **on n'utilise que `README-RESTORE.md`.** Pas d'historique de shell, pas
> d'assistant, pas de mémoire. Si une étape manque, c'est un bug du document, corrigé
> immédiatement.

1. Créer un répertoire jetable hors `/opt/eurio`.
2. Restaurer depuis **pCloud via Duplicati**, pas depuis le staging local — l'exercice
   doit traverser toute la chaîne, y compris le déchiffrement et le réseau.
   ⚠️ **Choisir la version : la plus récente n'est pas forcément restaurable en
   confiance.** `stage` retire `manifest.json` avant de commencer ; s'il échoue,
   Duplicati téléverse quand même un staging sans sentinelle. Vérifier la présence du
   manifeste dans la version visée (`duplicati-cli find … '*.json'`) et remonter d'un
   cran sinon. Constaté le 2026-08-16 sur la version la plus récente.
3. Dérouler les étapes 1 à 6 du §1, sur des ports et un projet compose distincts pour ne
   pas toucher la production.
4. Exécuter la suite d'invariants (étape 7) contre la stack restaurée.
5. Corriger `README-RESTORE.md` de tout ce qui a manqué ou menti.
6. Noter la date et le résultat dans [`ROADMAP.md`](./ROADMAP.md).
7. Acquitter le push monitor Kuma `eurio-drill`.
8. Détruire le répertoire jetable.

L'étape 7 n'est pas de la bureaucratie : sans elle, Kuma notifiera Discord dans ~100
jours pour signaler que l'exercice n'a pas eu lieu. C'est le mécanisme qui empêche ce
protocole de devenir la case à cocher jamais cochée de
`/opt/stacks/oim-duplicati/BACKUP_STRATEGY.md`.

## 5. Scénarios de sinistre et réponse attendue

| Scénario | Détecté par | Réponse |
|---|---|---|
| `eurio.db` corrompu ou tronqué | Invariants 1 et 3, **le jour même** | Restaurer la version J-1 depuis Duplicati (étapes 5-7) |
| Objets MinIO supprimés | Invariants 4 et 5 | Restaurer les objets manquants (étape 4), garder la base |
| Disque du VPS perdu | healthchecks.io (absence de ping) | Procédure complète, étapes 1 à 7 |
| VPS entier perdu | healthchecks.io | Idem, sur une machine neuve — c'est le cas que l'exercice simule |
| Sauvegarde corrompue en silence | Invariant 6 (échantillonnage) | Remonter dans la rétention de Duplicati |
| Le staging ne tourne plus | Kuma `eurio-staging` **+ invariant 8** (fraîcheur) | Réparer ; la dernière sauvegarde valide reste dans la rétention |
| **La destination refuse tout** (token expiré) | **Kuma `eurio-uploaded`, invariant 9** | Réparer le credential. **C'est la panne réelle des 10 autres jobs depuis le 26 mai** |

**Fenêtre de rétention : `keep-versions = 30` — 30 *versions*, pas 30 jours.** La
distinction est opérationnelle : avec un run réussi par jour, 30 versions ≈ 30 jours ;
avec des runs qui échouent, la fenêtre s'allonge (les versions ne sont pas consommées) ;
avec plusieurs runs par jour, elle se raccourcit d'autant.

Le job Eurio devra donc **fixer explicitement `keep-time`** s'il veut une garantie
temporelle. C'est cette borne temporelle, et non un compte de versions, qui définit
« combien de temps j'ai pour détecter une corruption avant qu'elle ne devienne
définitive » — et c'est elle qui rend les invariants quotidiens non optionnels.
