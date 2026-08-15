# Décisions — log chronologique

> Chaque décision porte ce qu'elle **écarte** et pourquoi. Une décision dont on ne sait
> plus ce qu'elle a écarté finit par être défaite par accident.

---

### D-01 — Duplicati est le moteur unique de sauvegarde
**2026-08-14 · PO**

Eurio rejoint le dispositif qui sauvegarde déjà les 10 autres stacks du VPS, au lieu de
maintenir un second chemin parallèle (`eurio-backup.sh` → pCloud via `rclone crypt`).

*Écarté* : garder deux dispositifs — un pour Eurio, un pour le reste.
*Pourquoi* : deux doctrines, deux endroits à surveiller, deux occasions d'oublier. La
seconde n'a d'ailleurs jamais tourné.
*Conséquence* : Duplicati porte le transport, le chiffrement, la rétention et
l'historique. Eurio ne fournit qu'un répertoire de staging.

> ✅ **Prérequis levé le 2026-08-15.** La revue a découvert que les 10 jobs n'écrivaient
> plus rien depuis 3 à 9 mois. **La décision reste valable** — Duplicati demeure le bon
> outil — et la panne a été réparée (D-18) avant d'y ajouter Eurio.
>
> Le fait que la panne ait duré si longtemps sans être vue est un **argument pour** cette
> décision, pas contre : un moteur unique surveillé vaut mieux que deux moteurs dont
> aucun ne l'est. C'est ce que corrige l'anneau 3 de D-16.

---

### D-02 — Le staging est produit par du code conscient de l'application
**2026-08-14**

Duplicati sauvegarde des chemins de fichiers. `eurio.db` (SQLite en WAL) et MinIO (format
objet interne) n'ont pas le système de fichiers pour surface valide. Un script produit
donc des artefacts cohérents dans `infra/backup/staging/`, que Duplicati ramasse.

*Écarté* : pointer Duplicati directement sur les binds.
*Pourquoi* : copie fichier d'une base en WAL = corruption ; répertoire MinIO = format
interne non vérifiable.
*Précédent invoqué* : le motif `pg_dump → backup-temp/` d'Authentik, décrit dans
`/opt/stacks/oim-duplicati/BACKUP_STRATEGY.md`.

> ⚠️ **Correction du 2026-08-14** : ce précédent est **décrit, pas appliqué**. La source
> Duplicati d'Authentik est le répertoire de stack entier, aucun `run-script-before`
> n'existe, aucun cron ni timer ne lance le `pg_dump` — et `backup-temp/` contient un
> unique dump **daté du 8 novembre 2025**, re-sauvegardé fidèlement chaque nuit depuis.
>
> Le motif *technique* reste bon et on le garde. Mais il faut cesser de le présenter
> comme une doctrine éprouvée : **c'est un des trois exemples de la pathologie qu'on
> corrige**, pas une référence à imiter. D'où D-08 (ordonnancement déclaratif) et
> D-16 (surveillance de l'exécution réelle).

---

### D-03 — MinIO est miroité par l'API S3, pas copié depuis le disque
**2026-08-14**

`rclone sync minio:<bucket> → staging/minio/<bucket>`.

*Écarté* : sauvegarder `infra/minio/data` directement.
*Pourquoi* : **on ne peut pas calculer le sha256 d'un objet sans réassembler `xl.meta`.**
Sauvegarder le répertoire brut rend la vérification impossible — soit exactement le
défaut qu'on est en train de corriger. S'y ajoute le risque de capturer un objet en
cours d'écriture.
*Coût accepté* : 6,43 GiB de disque (`/opt/eurio` 9,0 → ~15,3 Go, sur 85 Go libres).
*Gains* : vérifiabilité, surface naturelle pour Duplicati, restauration triviale.
*Correction du 2026-08-14* : la version initiale comptait le miroir comme « deuxième
copie contribuant au 3-2-1 ». **C'est faux** — même disque, même machine, même
répertoire parent que la source. Un disque perdu emporte les deux. C'est un **tampon de
vérification**, pas une protection.

---

### D-04 — On capture le store référençant avant le store référencé
**2026-08-14**

`eurio.db` et `review.db` d'abord, miroir MinIO ensuite.

*Pourquoi* : le décalage entre les deux snapshots est inévitable, mais il n'est pas
symétrique. DB puis MinIO ⇒ orphelins (bénins). MinIO puis DB ⇒ **dangling** (corruption
silencieuse à la restauration).
*Coût* : nul — c'est un ordre d'exécution.
*Réserve* : tient parce que MinIO est append-only en pratique. Le cas résiduel
(suppression entre T1 et T2) est couvert par l'invariant `dangling == 0`.
*Symétrique à la restauration* : le référencé d'abord (objets, puis bases).

---

### D-05 — La rétention et le versioning vivent chez Duplicati
**2026-08-14**

Le miroir est un point-dans-le-temps fidèle ; `rclone sync` propage les suppressions.
L'historique est la rétention Duplicati.

> ⚠️ **Correction du 2026-08-14** : la rétention mesurée est `keep-versions = 30` —
> **30 versions, pas 30 jours**. Avec des runs qui échouent, la fenêtre s'allonge ; avec
> plusieurs runs par jour, elle se raccourcit. **Le job Eurio fixera explicitement
> `keep-time`** : c'est une borne *temporelle* qui définit le délai dont on dispose pour
> détecter une corruption, pas un compte de versions.

*Écarté n°1* : `rclone copy --backup-dir` pour versionner côté miroir → doublon avec
Duplicati.
*Écarté n°2* : **rouvrir l'interdiction du versioning S3** de `infra/minio/README.md`
§Anti-patterns. Le plan initial suggérait de la rediscuter au motif que sa prémisse
(« tarball hebdomadaire ») était fausse. Elle redevient vraie autrement : l'historique
existe, chez Duplicati, **hors du disque à 78 %**. Activer le versioning S3 doublerait
l'usage disque de MinIO pour une protection qu'on a déjà. **La règle anti-patterns reste
valable telle quelle.**
*Corollaire assumé* : un wipe de MinIO se propage au miroir. Les 30 j de rétention
laissent le temps de réagir, et l'invariant de non-décroissance le détecte le jour même.

---

### D-06 — Uptime Kuma est propriétaire de l'alerte
**2026-08-14 · PO**

Les jobs poussent un battement de cœur ; Kuma détecte l'absence et notifie Discord via
le canal « Musubi Discord », déjà configuré et déjà par défaut.

*Écarté* : l'astuce « éditer le message épinglé en cas de succès, poster en cas d'échec,
plus un bilan hebdomadaire » du plan initial.
*Pourquoi* :
1. Éditer un message webhook exige de persister un `message_id` → un mode de panne
   supplémentaire **dans le chemin de notification lui-même**.
2. Un bilan hebdomadaire est un dead-man's switch faible : détecter une absence est un
   travail de machine.
3. « Les échecs sont rares donc pas de saturation » est faux quand ça compte : un token
   expiré échoue **toutes les nuits**, exactement quand on a besoin du signal. Kuma
   déduplique nativement (notification sur changement d'état).
4. `uptime.musubi.dev` est une meilleure preuve de vie datée qu'un message épinglé : il
   a l'historique.
*Gain* : Eurio apparaît au même endroit que les 13 autres monitors.

---

### D-07 — Un troisième anneau hors site : healthchecks.io
**2026-08-14 · PO**

*Pourquoi* : Kuma et ntfy tournent **sur le VPS qu'ils surveillent**. Aucun des deux ne
peut signaler la mort de cette machine, et il n'y a **qu'un seul VPS** — s'il tombe, il
n'y a plus de signal du tout, et une absence de signal est indiscernable du silence
normal.
*Mécanisme* : c'est l'**absence de ping** qui déclenche l'alerte, hors de la machine
surveillée.
*Note* : Discord reste le médium, et c'est le bon choix — c'est le seul canal **externe**
au VPS. ntfy, auto-hébergé, ne peut pas jouer ce rôle.

---

### D-08 — Ordonnancement découplé de Duplicati
**2026-08-14**

Timer systemd NixOS sur l'hôte à 02:00 / 02:30 UTC ; Duplicati ramasse le staging à
03:00 UTC et ne sait rien d'Eurio.

*Écarté* : `--run-script-before` / `--run-script-after` de Duplicati.
*Pourquoi* : ces scripts s'exécutent **dans** le conteneur `linuxserver/duplicati`.
Vérifié le 2026-08-14 : il possède `sh`, `bash`, `python3` et `curl`, mais **ni `docker`,
ni `rclone`, ni `sqlite3`, ni `mc`** ; aucun socket Docker monté, `Privileged=false`.
Faire tourner le staging dedans exigerait de lui exposer le socket Docker — couplage
fort et pleins pouvoirs sur l'hôte donnés au conteneur de sauvegarde.
*Nuance* : `curl` étant présent, faire **parler** Duplicati reste possible sans aucun
couplage — c'est exactement ce qu'exploite l'anneau 3 de D-16 (`--send-http-url`).
*Contrainte mesurée* : les jobs Duplicati démarrent à 03:00 UTC et, en régime sain
(25 mai), s'enchaînent en six minutes. Le staging doit être terminé avant 03:00.
*Bonus* : un service NixOS déclaratif survit à une réinstallation, contrairement à un
cron. `nix/eurio-vps.nix` existe déjà — il suffit de le réorienter et de l'importer.

---

### D-09 — La récupérabilité des secrets est traitée ailleurs
**2026-08-14 · PO**

Clé age du backup, passphrase Duplicati, `infra/minio/secrets`, `infra/review/secrets` —
sortis du périmètre de ce chantier, traités dans une session dédiée.

*À ne pas perdre de vue* : `infra/minio/secrets` et `infra/review/secrets` sont
**gitignorés**, donc absents d'un `git clone`. Sans eux, la restauration s'arrête à
l'étape 2 (cf. [`RESTAURATION.md`](./RESTAURATION.md) §1). Ce chantier peut être terminé
à 100 % et rester **inopérant** si cette question n'est pas résolue en parallèle.

---

### D-10 — Les invariants sont calculés, jamais lus
**2026-08-14**

*Origine* : `storage_status` vaut `'present'` sur 100 % des lignes de `image_assets` et
`source_images`, **y compris sur les 556 qui pointent vers un objet absent**. C'est le
champ vers lequel on tendrait naturellement la main pour vérifier la présence des
objets — et il est faux.
*Règle* : aucun invariant de vérification ne s'appuie sur un champ déclaratif qu'un
processus est censé maintenir. On recalcule l'état.
*Portée* : c'est la même erreur de raisonnement que « le script existe donc le backup
tourne ». Faire confiance à une déclaration au lieu de mesurer.

---

### D-11 — Le niveau 3 (plausibilité sémantique) est quotidien et non optionnel
**2026-08-14 · PO**

*Pourquoi* : `sha == sidecar` ne teste que le transport, et `PRAGMA integrity_check`
retourne `ok` sur une base **vide**. Une base tronquée, fidèlement transportée, passerait
les deux tests du plan initial et écraserait la bonne version à l'expiration de la
rétention.
*Invariant central* : la **non-décroissance** des comptages par table. Une décroissance
peut être légitime, mais elle doit **notifier et exiger un acquittement humain**.
*Cadre* : toute corruption non détectée avant l'expiration de la rétention est
définitive. Comme la rétention mesurée est en **versions** et non en jours (D-05), le
job Eurio devra fixer un `keep-time` explicite pour que ce délai soit une durée connue.
Les invariants quotidiens sont le seul mécanisme qui garantit la détection avant
expiration.

---

### D-12 — Exercice humain trimestriel, surveillé comme un job
**2026-08-14 · PO**

Restauration à froid tous les trimestres, **en n'utilisant que `README-RESTORE.md`**.
Push monitor Kuma d'intervalle ~100 jours, acquitté uniquement par le script d'exercice.

*Pourquoi un humain* : l'automatique a toujours la clé au bon endroit et les commandes
déjà connues. Il ne teste jamais si un humain qui a tout oublié peut récupérer. **C'est
exactement ce qui a échoué le 14 août** : rien n'était cassé, c'est l'étape humaine
« brancher le dispositif » qui n'a pas eu lieu.
*Pourquoi surveillé* : `/opt/stacks/oim-duplicati/BACKUP_STRATEGY.md` prescrit un
« Monthly Disaster Recovery Test » depuis novembre 2025. La case n'a jamais été cochée.
Un rituel humain non surveillé ne se fait pas. On surveille donc son absence, et cette
absence a une adresse.

---

### D-13 — Le critère d'acceptation d'une restauration est la suite de tests nocturne
**2026-08-14**

Un seul corpus de code sert à vérifier le backup chaque nuit et à valider une
restauration.

*Pourquoi* : ils ne peuvent pas diverger, et l'exercice de restauration ne peut pas
devenir du théâtre. Si un invariant est trop faible pour attraper une restauration
ratée, on le découvre pendant l'exercice, pas le jour de l'incident.

---

### D-14 — L'ancien backup pCloud n'est pas supprimé avant le lot 6
**2026-08-14**

L'archive du 17 juin (3,842 GiB, déchiffrable) reste en place jusqu'à ce que la nouvelle
chaîne ait passé un exercice de restauration complet.

*Pourquoi* : une copie périmée vaut mieux que zéro copie pendant une transition. C'est
le moment exact où la plupart des migrations de sauvegarde perdent des données.

---

### D-15 — Les bugs de qualité de données sortent en tickets séparés
**2026-08-14 · PO**

`image_assets.sha256` NULL, `storage_status` mensonger, orphelins → tickets séparés :
ils touchent le pipeline d'ingestion, pas la sauvegarde.

*Exception* : les **546 chemins absolus de Mac** dans `source_images.storage_path`.
Leur exclusion propre est un prérequis de l'invariant `dangling == 0`, sans quoi il naît
rouge. Traité dans le lot 3.

---

### D-16 — Un quatrième signal : prouver que la destination a reçu
**2026-08-14 · issu de la revue**

Un push monitor Kuma `eurio-uploaded`, alimenté par le `--send-http-url` de Duplicati
(`--send-http-level=all`).

*Angle mort corrigé* : les invariants des niveaux 1-2-3 tournent tous sur le **staging
local**. Aucun ne prouve que Duplicati a poussé quoi que ce soit. Un staging impeccable
et une destination qui refuse tout produisent exactement le même signal : vert.
*Pourquoi c'est prioritaire* : ce n'est pas un scénario théorique. **C'est la panne
réelle des 10 autres jobs** — ils s'exécutent, échouent en 401 depuis le 26 mai, et
personne ne l'a su pendant 81 jours.
*Pourquoi ça ne contredit pas D-08* : `--send-http-url` ne demande que `curl`, présent
dans le conteneur. Aucun socket Docker, aucun couplage.
*Portée* : directement réutilisable pour les 10 autres jobs. C'est le livrable le plus
transférable du chantier.

---

### D-17 — Un invariant de fraîcheur, distinct de la non-décroissance
**2026-08-14 · issu de la revue**

Comparer le `mtime` des sources au `t1` du manifeste ; échouer si le staging dépasse N
jours.

*Angle mort corrigé* : un staging **figé** passe les invariants 1 à 7 sans broncher. La
non-décroissance des comptages est vraie par construction quand plus rien ne change.
*Cas réel* : `eurio.db` n'a pas été écrit depuis le **2026-07-12**. Un mois pendant
lequel l'invariant 3 est vert et ne prouve rien.
*Conséquence* : « les comptages n'ont pas baissé » et « les données sont à jour » sont
deux propriétés distinctes. Il faut les deux.

---

### D-18 — Transport pCloud : backend natif OAuth, jamais WebDAV Basic Auth
**2026-08-15 · appliqué aux 10 jobs existants**

Destination de tous les jobs Duplicati, Eurio inclus :
`pcloud://api.pcloud.com/Applications/DuplicatiBackup/Oim/<Service>?authid=<jeton>`

*Écarté* : `webdav://webdav.pcloud.com:443/…?auth-username&auth-password&use-ssl`.
*Pourquoi* : pCloud traite chaque connexion WebDAV en Basic Auth comme une **nouvelle
ouverture de session** et, depuis une IP de datacenter, déclenche sa vérification
d'appareil — un mail valable 3 minutes, à 3 h du matin, par job. Ce n'est pas réglable :
aucun paramètre ne rend un couple identifiant/mot de passe non suspect. **Il fallait
changer de mode d'authentification, pas de valeur.**
*Le jeton* : celui de `~/.config/rclone/rclone.conf`, accepté tel quel comme `authid`.
Bearer **sans expiration** (`expiry: 0001-01-01`, aucun refresh token — modèle pCloud :
permanent jusqu'à révocation). Aucune dépendance à `oauth-service.duplicati.com`.
*Bénéfice annexe* : le WebDAV utilisait le **mot de passe du compte**. Il est remplacé
par un jeton révocable — gain de sécurité autant que de fiabilité.
*Conséquence à assumer* : rclone et Duplicati partagent désormais un credential. Une
révocation casse les deux. Acceptable, et de toute façon préférable à un mot de passe de
compte diffusé dans 10 configurations.
*Ce que ça ne règle pas* : rien ne garantit qu'une rechute serait vue plus vite que la
précédente. **Le transport est réparé, l'alerting ne l'est pas** — c'est D-16 et le lot 5.

---

### D-19 — Un job vert ne prouve pas que les données sont protégées
**2026-08-15 · issu de la réparation**

*Origine* : trois jobs verts découverts en réparant, qui protègent moins que leur nom.
**Beszel** sauvegarde un répertoire vide depuis toujours (faute de casse
`oim-Beszel`/`oim-beszel`). **Traefik** envoie 1 818 octets parce qu'`acme.json` est
exclu faute de permissions. **Immich** sauvegarde sa configuration, pas la photothèque
(ligne commentée dans le compose, données sur un stockage réseau non monté).
*Règle* : un code de retour dit que **l'outil a fait ce qu'on lui a demandé**. Il ne dit
rien de ce qu'on lui a demandé. Un job doit donc être vérifié sur **ce qu'il a réellement
capturé** — volumes, comptages, présence de fichiers attendus — pas sur son statut.
*Portée* : c'est la justification directe du niveau 3
([`VERIFICATION.md`](./VERIFICATION.md)) et de l'invariant de fraîcheur (D-17), et la
preuve que le besoin dépasse Eurio.
