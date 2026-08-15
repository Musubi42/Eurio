# Restauration d'Eurio

> Restaurer Eurio n'est pas « remettre des fichiers en place ». C'est rétablir **deux
> stores dans un état mutuellement cohérent**, dans un ordre imposé par les dépendances,
> puis le **prouver**.
>
> ⚠️ **Statut : procédure conçue, jamais exécutée.** Elle ne vaut rien tant que le lot 6
> n'a pas eu lieu. Ce document sera corrigé *par* le premier exercice — c'est son but.

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

- [ ] La commande exacte de restauration depuis Duplicati (interface web ou CLI ?)
- [x] ✅ **Où trouver la passphrase Duplicati sans le VPS** — résolu le 2026-08-16
      (**D-28**). `DUPLICATI_EURIO_PASSPHRASE` et `DUPLICATI_PCLOUD_AUTHID` sont dans
      `secrets/dev.env` (SOPS+age), et la passphrase est vérifiée identique à celle du
      password manager. Découverte au passage : **aucun des 11 jobs ne sauvegarde
      `/opt/eurio` ni la config Duplicati** — la clé ne vivait que sur la machine
      qu'elle est censée pouvoir remplacer.
- [ ] Le temps réel de restauration des 6,43 GiB depuis pCloud
- [ ] Les policies MinIO exactes attendues par `eurio-api` après bootstrap
- [ ] Faut-il recréer les réseaux Docker (`traefik`) à la main ?
- [ ] Le comportement de `eurio-api` au démarrage sur une base restaurée : rejoue-t-il
      des migrations ? *(`_schema_migrations` = 5 aujourd'hui)*
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
