# Stratégie de sauvegarde du VPS — plan

> **Statut : PLAN, non implémenté.** Écrit le 2026-08-14.
> Implémentation prévue en session dédiée sur le VPS (`ssh serverOimNixDontpanic`,
> projet dans `/opt/eurio`).
>
> Remplace, en le précisant, l'existant décrit dans [`../../infra/backup/README.md`](../../infra/backup/README.md).

## 1. Le constat qui motive ce document

Le 2026-08-14, inspection du VPS. **Aucune sauvegarde ne tourne.** Vérifié par quatre
chemins indépendants :

| Vérification | Résultat |
|---|---|
| Timers systemd (`systemctl list-timers --all`) | aucune entrée |
| Cron utilisateur et système | aucune entrée |
| `rclone` | **pas installé** |
| Journal (`journalctl -g eurio-backup`) | aucune trace |
| Archives sur disque (`find /opt /var/backups /home`) | aucune |

Ce qui existe : `infra/backup/eurio-backup.sh`, sa doc, et une clé age dans
`~/.config/eurio-backup/age-key.txt` **datée du 17 juin**. Le dispositif a été préparé,
puis jamais branché.

> **La leçon est le principe directeur de ce document : un dispositif préparé n'est pas
> un dispositif qui tourne, et un dispositif qui tourne n'est pas un dispositif qui
> restaure.** Les trois doivent être vérifiés séparément.

## 2. Ce qu'il faut protéger

| Donnée | Volume | Reproductible ? | Rythme de changement |
|---|---|---|---|
| `eurio.db` (canonique SQLite, `/opt/eurio/infra/eurio-api/data/`) | 149 Mo | 🔴 **non** | souvent (writer unique) |
| MinIO `/opt/eurio/infra/minio/data` | **6,8 Go** | 🔴 non (raws scrapés, crops, canoniques) | append-only surtout |
| `review.db` | 48 ko | 🔴 non (décisions humaines) | au fil des reviews |
| Secrets | — | ✅ déjà chiffrés dans git (SOPS+age) | rare |
| Code | — | ✅ git, deux remotes | — |

**Rien de tout cela n'est dans le tarball du 2026-08-14** : celui-ci sauve le dépôt
local du Mac, pas les données du serveur.

Profils différents ⇒ rythmes différents :

- **`eurio.db` + `review.db`** : petits, changent souvent, irremplaçables → **quotidien**,
  avec rétention (garder N versions, pas juste la dernière — une corruption répliquée
  sur une seule copie détruit tout).
- **MinIO** : gros, quasi append-only → **hebdomadaire**, ou incrémental.

## 3. Règle de notification — l'inversion

Support retenu : **Discord**, salon dédié au projet, via webhook.

Le mécanisme de base : sur Discord, **éditer un message ne déclenche pas de
notification push ; poster un nouveau message si.** D'où :

| Événement | Action | Notification |
|---|---|---|
| Sauvegarde **réussie** | **édite** le message d'état épinglé | ❌ silencieux |
| Sauvegarde **échouée** | **poste un nouveau message** | ✅ push |
| **Bilan hebdomadaire** | **poste un nouveau message** | ✅ push |

### Pourquoi cette inversion

La version naïve — « j'édite tous les jours, je poste toutes les semaines » — a un angle
mort : **le silence est ambigu**. Si le job meurt entièrement (VM éteinte, script cassé,
webhook révoqué), personne n'édite rien. Et « rien n'a changé » ressemble exactement à
« tout va bien » pour quelqu'un qui ne regarde pas.

On surveille donc **l'anomalie**, pas le succès. Les échecs étant rares par nature, une
notification par échec ne saturera jamais.

### Le message d'état doit porter une preuve de vie datée

Un « ✅ OK » figé ne vieillit pas visiblement. Un horodatage, si :

```
✅ Sauvegarde Eurio — dernière réussie il y a 14 h (2026-08-14 03:00 UTC)
   eurio.db  149 Mo · sha 3f2a91… · restauration-témoin OK
   MinIO     6,8 Go · dernier full le 2026-08-11
   Série     7/7 sur les 7 derniers jours
```

### Le bilan hebdomadaire affirme le compte

C'est lui qui rattrape un job mort : `7/7 réussies` ou `⚠️ 5/7 — échecs les 12 et 14`.
Un message **attendu** chaque semaine finit par se remarquer s'il n'arrive pas, là où
l'absence d'une édition ne se remarque jamais.

## 4. Vérifier, pas seulement sauvegarder

**Une sauvegarde jamais restaurée n'est pas une sauvegarde.** Le tarball du 2026-08-14
ne vaut que parce qu'on a extrait son `.git`, relancé un `git checkout` (6094 fichiers)
et un `git fsck` (0 erreur).

Le job hebdomadaire doit inclure une **restauration-témoin** et la reporter :

1. extraire **un** fichier connu de l'archive la plus récente ;
2. comparer son sha256 à celui enregistré au moment de la sauvegarde ;
3. pour `eurio.db` : `PRAGMA integrity_check` sur la copie restaurée ;
4. reporter le résultat dans le message hebdomadaire.

Sans ça, on reproduit exactement la situation du 14 août : un dispositif, une clé age,
et la conviction que ça tourne.

## 5. Questions ouvertes — à trancher en session dédiée

| # | Question | Pistes |
|---|---|---|
| 1 | **Ordonnanceur** : systemd timer, cron, ou service NixOS déclaratif ? | Le VPS est sous NixOS → un service déclaratif survit à une réinstallation, un cron non. Cohérent avec la doctrine « deps via flake, pas d'install manuelle » |
| 2 | **Destination** : pCloud via rclone (prévu dans `infra/backup/`), ou autre ? | `rclone` n'est **pas installé** aujourd'hui. Si NixOS, l'ajouter à la config plutôt qu'à la main |
| 3 | **Rétention** : combien de versions de `eurio.db` ? | 7 quotidiennes + 4 hebdomadaires est un compromis courant. 149 Mo × 11 ≈ 1,6 Go |
| 4 | **MinIO** : full hebdomadaire (6,8 Go) ou incrémental ? | Append-only ⇒ l'incrémental est très rentable. Mais un incrémental non testé est un piège |
| 5 | **Chiffrement** : la clé age de juin est-elle encore la bonne ? Où est sa copie ? | Une sauvegarde chiffrée dont la clé n'existe qu'**sur la machine sauvegardée** ne protège de rien |
| 6 | **3-2-1** : pCloud est une copie hors site. Y en a-t-il une seconde ? | Aujourd'hui zéro copie. Une seule serait déjà un progrès décisif |
| 7 | **Espace disque** | VPS à 77 % (86 Go libres). Une archive locale de 6,8 Go avant envoi tient, mais pas avec beaucoup de marge |

## 6. Ordre d'implémentation proposé

1. **La copie la plus bête qui marche** : `eurio.db` + `review.db` copiés hors site,
   manuellement, aujourd'hui. Une sauvegarde imparfaite qui existe bat une sauvegarde
   parfaite qui n'existe pas.
2. Automatiser ce quotidien (question 1), **avec le webhook d'échec** dès le départ.
3. Ajouter la restauration-témoin (§4).
4. Ajouter MinIO (question 4).
5. Ajouter le bilan hebdomadaire.
6. **Tester une restauration complète** à blanc, et noter la date dans ce fichier.

## 7. Effet de bord : une règle à réexaminer

`infra/minio/README.md` §Anti-patterns interdit le versioning S3 :

> « Don't enable bucket versioning. **The protection model is "weekly tarball + audit"**,
> not S3 native versioning. »

La règle est saine — *un bon filet plutôt que deux moyens* — mais **sa prémisse est
fausse** : le tarball hebdomadaire n'existe pas. Elle interdit donc une protection au nom
d'une autre qui n'a jamais été tendue.

**À rediscuter une fois le §6 fait**, pas avant : quand la prémisse redevient vraie, la
question se pose dans les bons termes.

---

**Voir aussi** : [`../../infra/backup/README.md`](../../infra/backup/README.md) ·
[`../../infra/backup/README-RESTORE.md`](../../infra/backup/README-RESTORE.md) ·
[`../architecture/README.md`](../architecture/README.md) ·
[`../work-in-progress/repo-refactor/README.md`](../work-in-progress/repo-refactor/README.md)
