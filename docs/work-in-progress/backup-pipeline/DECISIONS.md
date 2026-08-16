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

---

### D-20 — Le bucket `eurio-db` est miroité, sauf sa copie de `eurio.db`
**2026-08-15 · lot 3**

Le miroir garde `eurio-db/transfers/` (artefacts ML, 105 Mo) et **exclut**
`eurio.db` / `eurio.db.*` (104 Mo, figés au 2026-06-29).

*Contexte* : ce bucket est legacy —
[`data-layer-unification`](../data-layer-unification/README.md) phase 5 prévoit sa
suppression, et `infra/minio/bootstrap.sh` ne le recrée pas (il crée
`numista-canonical`, `enrichment-raws`, `enrichment-crops` et `model-artifacts`).
*Pourquoi garder `transfers/`* : ce sont des poids issus de runs d'entraînement.
Reproductibles en théorie, très chers en pratique.
*Pourquoi exclure `eurio.db`* : c'est un doublon **périmé** de ce que le staging
capture déjà en frais par `VACUUM INTO`. Deux `eurio.db` dans une même sauvegarde,
datés de deux mois d'écart, sont un **piège de restauration** — exactement la classe de
problème des deux `review.db` du VPS (ETAT-DES-LIEUX §1). Économie annexe : 104 Mo.
*À revoir* : quand la phase 5 tuera le bucket, l'entrée disparaît d'elle-même. Si
`transfers/` doit survivre, il faudra lui trouver un domicile — probablement
`model-artifacts` (ADR-004).

---

### D-21 — Le miroir n'est pas une copie, et le dire est un invariant
**2026-08-15 · lot 3**

`rclone sync` (et non `copy`) : le miroir est un point-dans-le-temps **fidèle**, y
compris pour les suppressions.

*Conséquence assumée* : un wipe de MinIO se propage au miroir. Le miroir seul ne peut
donc **pas** s'en apercevoir — il refléterait fidèlement le vide.
*Ce qui l'attrape* : la comparaison à la référence (invariant 5, objets par bucket non
décroissants), au même titre que les comptages de tables. Et la rétention Duplicati
laisse le temps de remonter à la version d'avant.
*Écarté* : un miroir cumulatif (`copy` sans suppression). Il divergerait de la source,
rendrait l'invariant d'orphelins muet, et ferait doublon avec l'historique Duplicati.

---

### D-22 — Le module NixOS s'importe par un input flake, jamais par chemin absolu
**2026-08-15 · lot 4**

Dans `/etc/nixos/flake.nix` :

```nix
inputs.eurio-nix = { url = "path:/opt/eurio/nix"; flake = false; };
modules = [ … "${eurio-nix}/eurio-vps.nix" ];
```

*Écarté* : `imports = [ /opt/eurio/nix/eurio-vps.nix ]`, la méthode que le module
documentait lui-même depuis juin.
*Pourquoi* : elle **ne peut pas fonctionner** sur ce système. Le VPS est construit par
un flake, et un flake est hermétique — vérifié en le tentant :
`error: access to absolute path '/opt/eurio/nix/eurio-vps.nix' is forbidden in pure
evaluation mode`. C'est une raison de plus pour laquelle l'ordonnancement n'avait jamais
été branché : la procédure écrite était inapplicable, et personne ne l'avait tentée.
*Écarté aussi* : `--impure` (défait la reproductibilité du système entier pour un
fichier de 150 lignes) et copier le module dans `/etc/nixos` (duplication qui dérive).
*Pourquoi `/opt/eurio/nix` et non `/opt/eurio`* : un input `path:` copie l'arborescence
dans le store. La racine du dépôt pèse **plusieurs Go**, staging de sauvegarde compris.
Cibler le sous-dossier ne copie que quelques Ko.
*Friction acceptée* : modifier le module exige `nix flake update eurio-nix`. Pour un
ordonnanceur de sauvegardes en production, une modification qui laisse une trace dans
`flake.lock` est un avantage, pas une gêne.

---

### D-23 — Le staging est monté en LECTURE SEULE dans Duplicati
**2026-08-15 · lot 4**

`- /opt/eurio/infra/backup/staging:/eurio-source:ro`

*Pourquoi* : un outil de sauvegarde n'a aucune raison de pouvoir écrire dans les données
qu'il sauvegarde. Le montage en lecture seule coûte deux caractères et retire
définitivement une classe entière d'accidents.
*Contexte* : les 14 autres montages de ce conteneur sont en lecture-écriture. On ne les
change pas ici — ce n'est pas le périmètre de ce chantier — mais c'est un candidat
évident pour le durcissement des 10 autres jobs.

---

### D-24 — Un anneau Push est acquitté par le SILENCE, jamais par le contenu du ping
**2026-08-16 · lot 5**

`send-http-level = Success` sur le job Duplicati 17, et non `all` comme le prévoyait le
plan initial. Idem pour healthchecks.io, pingé uniquement si les 18 invariants passent.

*Écarté* : `all`, qui paraissait plus informatif — « on saura tout ce qui se passe ».
*Pourquoi* : un monitor Push passe au vert **dès qu'il reçoit une requête**, quel qu'en
soit le contenu. Avec `all`, Duplicati pingerait aussi après un échec : Kuma afficherait
vert sur une sauvegarde ratée. Le contenu du ping n'est lu par personne ; seule son
**arrivée** est un signal.
*Conséquence* : c'est l'absence de ping qui alerte, au dépassement des 25 h. Un run
terminé en *Warning* ne pinge pas non plus et déclenche donc une alerte — bon défaut :
mieux vaut regarder un avertissement de trop que manquer une sauvegarde partielle.

---

### D-25 — Chaque anneau a un DIALECTE explicite, jamais une URL générique
**2026-08-16 · lot 5**

`notify()` prend un 5e paramètre : `kuma` (état en paramètre de requête) ou `hc`
(état dans le chemin — `<url>` = succès, `<url>/fail` = échec).

*Écarté* : une fonction unique envoyant `?status=up|down` à toutes les destinations.
*Pourquoi* : **healthchecks.io ignore les paramètres de requête**. Un `?status=down`
envoyé à l'URL de base y enregistrait un *succès* — l'anneau annonçait « tout va bien »
au moment précis où tout allait mal, et `notify-test` affichait un vert rassurant.
*Contexte* : trouvé en branchant l'anneau pour de vrai, pas par les 20 cas du test
négatif — qui n'appellent aucun endpoint réel et ne pouvaient donc pas connaître le
dialecte du destinataire. **Un anneau ne se valide qu'en le débranchant réellement.**
*Voir aussi* : le même jour, `stage_rc` en `local` faisait partir un statut **vide**
depuis le trap `EXIT` (exécuté après la disparition des locales, `set -u`) — que Kuma lit
comme un succès. Deux bugs distincts, une seule signature : *le détecteur ment dans le
sens rassurant*.

---

### D-26 — L'anneau `eurio-drill` ne vivra pas dans Kuma
**2026-08-16 · lot 5, à exécuter au lot 6**

Kuma plafonne l'intervalle de heartbeat à **2 073 600 s (24 jours)**. L'exercice de
restauration étant trimestriel (~90 j, cf. D-12), un monitor Push y serait **rouge en
permanence** entre deux exercices.

*Écarté* : (a) laisser le monitor rouge « en attendant » ; (b) ramener l'exercice à une
cadence de 24 j pour tenir dans l'outil.
*Pourquoi* : (a) un monitor perpétuellement rouge **apprend à ignorer les alertes** —
c'est la pathologie même que ce chantier corrige, et la raison pour laquelle 924
notifications Duplicati n'étaient pas acquittées. (b) laisser l'outil dicter la cadence
d'un rituel, plutôt que l'inverse.
*Décision* : porter l'anneau 5 sur **healthchecks.io** (périodes jusqu'à 365 j), qui est
de toute façon hors site. En attendant le lot 6, le monitor `eurio-drill` est **en
pause** dans Kuma ; sa Push URL reste dans `notify.conf`, rien à recréer.

---

### D-27 — Les `403 Forbidden` du miroir MinIO sont du bruit Cloudflare, et on le dit
**2026-08-16 · lot 5**

Pendant `stage`, rclone émet quelques `NOTICE: Failed to read metadata: HeadObject
403` (une poignée sur 33 953 objets). **Aucun impact sur l'intégrité** — vérifié
objet par objet :

| Contrôle | Résultat |
|---|---|
| `sha256` local ≡ `sha256` distant (GET) | identiques |
| Taille annoncée par LIST ≡ taille locale | 3 488 o = 3 488 o |
| `mtime` distant préservé localement | 2026-06-14 22:35:38 des deux côtés |

*Cause* : `eurio-s3.musubi.dev` est derrière Cloudflare (2 edges). Les 403 n'apparaissent
que sur les HEAD **signés**, **sous rafale** (`--transfers 8`) : en séquence alternée
pendant un burst, puis 8/8 OK au repos. Un HEAD non authentifié renvoie 200 depuis le
cache CDN sur les deux edges. C'est donc du **rate-limiting / WAF**, pas une permission
manquante — cousin du `v2_auth` déjà nécessaire ici *(cf. mémoire projet Cloudflare)*.
*Pourquoi c'est bénin* : `rclone sync` construit son plan depuis **LIST**, qui porte déjà
taille et `mtime`. Le HEAD n'est qu'un complément de métadonnées ; son échec ne retire
aucun objet du transfert.
*Écarté* : `--s3-no-head-object`, qui **supprimerait le message**. On ne fait pas taire
un avertissement pour retrouver une sortie propre — c'est exactement ainsi qu'on cesse de
voir les vrais. Le message reste bruyant et documenté ici.
*Reste à faire (lot 6)* : l'invariant [6] ne re-vérifie que **20 objets sur 13 989**.
Ce n'est pas ce 403 qui l'exige, mais l'échantillon est mince pour un miroir de 6,6 Go —
à rediscuter avec le coût d'un échantillon plus large ou tournant.

---

### D-28 — Les secrets de RESTAURATION vivent dans SOPS, pas seulement dans Duplicati
**2026-08-16 · lot 6, étape 0**

`DUPLICATI_EURIO_PASSPHRASE` et `DUPLICATI_PCLOUD_AUTHID` sont désormais dans
`secrets/dev.env` (SOPS+age), donc versionnés chiffrés et présents sur toute machine
autorisée.

*Découverte qui l'impose* : **aucun des 11 jobs Duplicati ne sauvegarde `/opt/eurio` ni
`/opt/stacks/oim-duplicati/`.** Les sources sont `/oim-<stack>-source/` pour les 10
autres, et `/eurio-source/` (le staging seul) pour Eurio. La passphrase et le jeton
pCloud ne vivaient donc **que** dans la configuration Duplicati du VPS.

*Conséquence si on n'avait rien fait* : le VPS meurt ⇒ 5,61 Gio d'archive chiffrée,
vérifiée, hors site… et aucune clé pour l'ouvrir. **Une sauvegarde indéchiffrable n'est
pas une sauvegarde.** Et c'est invisible : tous les anneaux du lot 5 restent verts dans
ce scénario, puisqu'ils prouvent l'écriture, jamais la lecture.

*Écarté* : se reposer sur le seul password manager. Il reste le recours hors ligne — et
la passphrase y a été **vérifiée identique le 2026-08-16**, par comparaison d'empreintes
salées, sans qu'aucune valeur ne transite en clair. Mais un secret que seul un humain
peut aller chercher ne peut pas être utilisé par un script d'exercice (D-12).
*Écarté aussi* : sauvegarder la configuration Duplicati elle-même. C'est souhaitable et
ça fait l'objet d'un ticket, mais ça ne remplace pas ceci — restaurer la config Duplicati
depuis une archive Duplicati exige déjà la passphrase. **La circularité est le piège** :
la clé ne doit jamais être uniquement à l'intérieur de ce qu'elle ouvre.

*Chaîne de survie après cette décision*, chaque maillon hors du VPS :

| Maillon | Où | Survit à la perte du VPS ? |
|---|---|---|
| Code + `secrets/dev.env` chiffré | Codeberg (+ GitHub) | ✅ |
| Clé privée age | password manager | ✅ |
| Passphrase + `authid` | dans SOPS **et** password manager | ✅ |
| Archive chiffrée | pCloud | ✅ |

*Reste à couvrir* : `infra/minio/secrets` et `infra/review/secrets`, gitignorés et dans
aucun job — sans eux, `bootstrap.sh` régénère des identifiants MinIO que `eurio-api` ne
sait plus lire (cf. Pièges du HANDOFF). À traiter avant le drill de l'étape 2.

---

### D-29 — Les secrets d'infrastructure vont dans SOPS, pas dans l'archive
**2026-08-16 · lot 6, étape 0 (suite)**

Les 6 secrets de `infra/minio/secrets/` et `infra/review/secrets/` sont désormais dans
`secrets/dev.env`. Trois y ont été ajoutés (`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`,
`REVIEW_SESSION_SECRET`) ; les trois autres y étaient déjà et ont été **vérifiés
identiques** aux fichiers, par empreinte salée.

*Écarté* : ajouter `/opt/eurio` aux sources du job Duplicati 17.
*Pourquoi* : (a) les secrets n'y seraient protégés que par le chiffrement Duplicati, pas
par age ; (b) ça élargit un job dont le périmètre était volontairement « le staging, rien
d'autre » (D-01) ; (c) surtout, **c'est circulaire** — les identifiants MinIO servent à
remonter l'infrastructure qui héberge les données que l'archive contient. Même piège que
D-28 : la clé ne doit pas être uniquement dans ce qu'elle ouvre.
*Conséquence voulue* : **le clone devient auto-suffisant.** `git clone` + clé age =
tout le nécessaire hors données. C'est ce qui rend le drill réalisable ailleurs que sur
le VPS — sur le Mac, par exemple, ce qui est le seul exercice qui teste vraiment « la
machine a brûlé ».
*Note d'implémentation* : les fichiers `infra/*/secrets/*` restent la surface consommée
par `docker compose` (pattern `*_FILE`). SOPS en est la **source**, eux la projection.
Les régénérer depuis SOPS est l'étape 2 de `RESTAURATION.md` ; le script du lot 6 doit
le faire, et non les restaurer depuis l'archive.

---

### D-30 — `eurio-review` tourne avec les identifiants ROOT de MinIO *(anomalie, à corriger)*
**2026-08-16 · découvert au lot 6**

En cartographiant les secrets, les empreintes ont révélé que
`infra/review/secrets/minio_access_key` et `minio_secret_key` sont **exactement**
`minio_root_user` et `minio_root_password`.

`eurio-review` dispose donc des pleins pouvoirs sur MinIO — création et suppression de
buckets, gestion des politiques et des utilisateurs — alors qu'il n'a besoin que de lire
et écrire quelques préfixes. Le compte applicatif restreint `eurio-app` existe pourtant
déjà (créé par `bootstrap.sh`, politique dans `infra/minio/policies/`), et c'est celui
qu'utilise `eurio-api`.

*Ce n'est pas un défaut de sauvegarde* — d'où une décision distincte plutôt qu'un
élargissement du lot 6. Mais ça a une conséquence directe sur la restauration : un drill
qui remonte MinIO avec des identifiants root **ne teste pas** le chemin de permissions
réel de la production. Le drill doit donc utiliser les comptes applicatifs.

*À faire, hors chantier sauvegarde* : donner à `eurio-review` son propre compte MinIO
scopé, puis **rotater le mot de passe root** — il a fuité dans la surface de deux
services. Ticket ouvert dans le HANDOFF (§découvertes, n° 10).

---

### D-31 — Duplicati refuse de téléverser un staging sans manifeste
**2026-08-16 · lot 6, après l'exercice**

`stage` (02:00 UTC), `verify` (02:30) et le job Duplicati (03:00) sont trois
planifications **indépendantes**. Le 16 août, `stage` a échoué ; il retire
`manifest.json` avant de commencer, précisément pour qu'un staging interrompu soit
détectable. Une heure plus tard, Duplicati a téléversé ce staging sans sentinelle et a
rapporté un succès. **L'exercice de restauration l'a constaté depuis l'autre bout :** la
version distante la plus récente n'avait pas de manifeste, donc était invérifiable —
c'est celle qu'on aurait prise en urgence.

*Écarté* : (a) laisser les trois planifications indépendantes et « faire attention » ;
(b) fusionner stage+verify+upload en une seule unité ; (c) faire échouer `verify` plus
fort.
*Pourquoi* : (a) c'est ce qui a produit la panne, et personne ne l'a vue pendant
neuf mois de jobs morts ; (b) ça remettrait le transport dans notre script alors que
Duplicati est le moteur unique (D-01) ; (c) `verify` criait déjà correctement — le
problème n'est pas la détection, c'est que le téléversement ne l'écoute pas.
*Décision* : un **portier** (`infra/backup/pre-upload-gate.py`) monté en lecture seule
dans le conteneur Duplicati, câblé sur le job via `--run-script-before`. Il sort en
**code 5** (erreur + ne pas lancer) si le manifeste est absent, illisible, vieux de plus
de 36 h, ou s'il décrit un fichier absent.

*L'arbitrage, explicitement* : bloquer peut faire sauter une nuit de sauvegarde. On
l'accepte parce que la rétention se compte en **30 versions, pas en 30 jours**. Une nuit
sautée ne consomme aucune version et laisse intacte la dernière bonne ; une nuit
téléversée par-dessus un staging mort en consomme une et repousse l'archive utilisable
d'un cran dans l'historique. Sauter est réversible, empiler du vide l'est moins.

*Comment on l'apprend* : le portier ne notifie **rien**. En sortant en erreur, il empêche
le job de réussir, donc d'émettre son ping de succès — et c'est l'absence de ping qui
fait rougir l'anneau 3 `eurio-uploaded`. Un détecteur qui porte sa propre alerte est le
défaut que ce chantier corrige (D-06).

---

### D-32 — L'anneau 5 est un check healthchecks.io, et il s'acquitte tout seul
**2026-08-16 · lot 6, exécution de D-26**

Exécution de la décision D-26, plus une correction : le monitor Kuma `eurio-drill`
n'était pas « en pause », il **n'existait plus** — son URL répondait
`404 Monitor not found or not active`. L'anneau 5 était donc doublement inopérant :
mauvais outil, et plus de destination.

*Décision* : `DRILL_URL` (healthchecks.io, Period 90 j / Grace 30 j) remplace
`KUMA_DRILL_URL`, qui reste accepté en repli pour ne pas casser une conf existante.
L'acquittement est une sous-commande, `eurio-backup.sh drill-ack`, appelée par
`infra/backup/drill/smoke.sh` **uniquement quand tous ses contrôles passent** — jamais à
la main.

*Pourquoi le conditionner au résultat* : un acquittement manuel transformerait l'anneau
en case à cocher, c'est-à-dire en la chose exacte qu'il remplace (la case « Monthly DR
Test » de `BACKUP_STRATEGY.md`, jamais cochée depuis novembre 2025). Un exercice raté
laisse l'anneau silencieux, et ce silence alerte au trimestre suivant.
