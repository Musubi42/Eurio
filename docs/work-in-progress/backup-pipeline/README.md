# backup-pipeline

> Chantier ouvert le **2026-08-14** : donner à Eurio une chaîne de sauvegarde et de
> restauration **qui tourne, qui se vérifie, et qui prévient un humain quand elle ne
> tourne plus**. Eurio est aujourd'hui la seule stack significative du VPS absente du
> dispositif Duplicati censé sauvegarder les 10 autres.

> ## ✅ Duplicati réparé le 2026-08-15
>
> La revue du 2026-08-14 a découvert que **les 10 jobs Duplicati n'écrivaient plus rien**
> — extinction progressive de novembre 2025 à mai 2026, jusqu'à 9 mois sans sauvegarde
> pour certains. Cause : le WebDAV en Basic Auth déclenchait la vérification d'appareil
> de pCloud, à 3 h du matin, chaque nuit.
>
> **Réparé** : les 10 jobs sont passés sur le backend pCloud natif en OAuth, et ont tous
> tourné avec succès. Détail et preuves : [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §3.
>
> ⚠️ **Le transport est réparé, l'alerting ne l'est pas.** Rien ne garantit qu'une
> rechute serait vue plus vite que la précédente. C'est l'objet du lot 5.

## Le principe directeur

> **Un dispositif préparé n'est pas un dispositif qui tourne, et un dispositif qui
> tourne n'est pas un dispositif qui restaure.** Les trois se vérifient séparément.

Ce n'est pas une formule : c'est le constat du 2026-08-14, et il s'est vérifié **cinq
fois** sur cette machine.

1. **Eurio** — le script, la clé de chiffrement, le module systemd et le token pCloud
   existaient tous et fonctionnaient tous. La dernière sauvegarde datait de deux mois,
   parce que personne n'avait importé une ligne dans `/etc/nixos/configuration.nix`.
2. **Duplicati** — 10 jobs ordonnancés qui s'exécutaient chaque nuit et échouaient chaque
   nuit, en criant dans une interface sans lecteur. Jusqu'à 9 mois sans sauvegarde.
3. **Authentik** — un `pg_dump` documenté comme procédure, jamais automatisé. Duplicati
   re-sauvegarde fidèlement, chaque nuit, un dump figé de **novembre 2025**.
4. **Beszel** — un job vert depuis toujours, sur un répertoire source **vide** : une
   faute de casse dans un chemin de montage.
5. **Traefik** — un job vert qui envoie 1 818 octets, parce que `acme.json` est exclu
   faute de permissions.

Cinq formes de la même illusion : *écrit ≠ ordonnancé ≠ exécuté ≠ arrivé ≠ complet ≠
restaurable*. Six états que le « ✅ » d'un job confond en un seul.

D'où les trois exigences non négociables de ce chantier :

1. **La sauvegarde tourne** — ordonnancée déclarativement, pas à la main.
2. **La sauvegarde est bonne** — vérifiée par des invariants **calculés**, pas par un
   code de retour. Et la suite de vérification doit prouver qu'elle sait dire *non*.
3. **Son absence se remarque** — surveillée par un système *extérieur* à elle.

## Statut

| Lot | Description | Statut |
|---|---|---|
| 0 | Copie manuelle immédiate `eurio.db` + `review.db` hors site | ✅ 2026-08-15 |
| 1 | `eurio-backup.sh stage` — VACUUM INTO ×2 + `manifest.json` | ✅ 2026-08-15 |
| 2 | Suite d'invariants (niveaux 1-2-3), autonome et testée | ✅ 2026-08-15 |
| 3 | Miroir MinIO dans le staging + invariants inter-stores | ✅ 2026-08-15 |
| 4 | Job Duplicati « Eurio » + timer NixOS | 🟡 reste le `switch` |
| **5** | Kuma ×4 + healthchecks.io | ⬜ **next** |
| 6 | Procédure de restauration + **premier exercice à froid** | ⬜ |
| 7 | Décommissionnement de l'ancien chemin pCloud | ⬜ |

Détail et critères de fin : [`ROADMAP.md`](./ROADMAP.md).

## Documents

| Doc | Rôle | Quand le lire |
|---|---|---|
| [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) | Ce qui existe réellement sur le VPS, mesuré le 2026-08-14 | En premier — c'est la base factuelle |
| [`DONNEES.md`](./DONNEES.md) | Inventaire des données, cohérence inter-stores, bugs de qualité | Avant toute décision d'architecture |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Staging, miroir, Duplicati, ordonnancement, alerting | Avant d'écrire du code |
| [`VERIFICATION.md`](./VERIFICATION.md) | Les 5 niveaux de test, les invariants, l'exercice humain | Avant d'écrire la suite de tests |
| [`RESTAURATION.md`](./RESTAURATION.md) | Ordre de restauration et procédure d'exercice | Le jour où ça brûle, et tous les trimestres |
| [`ROADMAP.md`](./ROADMAP.md) | Les 8 lots, critères de fin, suivi | Pour situer le travail courant |
| [`DECISIONS.md`](./DECISIONS.md) | Log chronologique D-01 → D-NN | Pour comprendre pourquoi c'est comme ça |
| [`HANDOFF-NEXT-SESSION.md`](./HANDOFF-NEXT-SESSION.md) | Plan d'exécution + actions humaines requises | En début de session |

## Ce que ce chantier ne traite pas

- **La récupérabilité des secrets** (clé age du backup, creds MinIO, passphrase
  Duplicati) — traitée dans une session dédiée. Voir [`DECISIONS.md`](./DECISIONS.md) D-09.
- **La généralisation aux 10 autres jobs** de l'alerting construit ici — le problème est
  plus large qu'Eurio, et Eurio sert de prototype.
- **Les trois sauvegardes qui protègent moins que leur nom** (Beszel, Traefik, Immich) —
  tickets séparés, sauf la faute de casse de Beszel qui se corrige dans la même édition
  de compose que le lot 4. Voir [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §8.
- **Les bugs de qualité de données** trouvés en chemin (sha256 non renseignés,
  chemins absolus de Mac dans la base) — tickets séparés, sauf ce qui bloque un
  invariant. Voir [`DONNEES.md`](./DONNEES.md) §4.

## Voir aussi

- [`../../operations/backup-strategy.md`](../../operations/backup-strategy.md) — le plan
  initial du 2026-08-14, **remplacé par ce chantier** (certaines de ses prémisses étaient
  fausses, cf. [`ETAT-DES-LIEUX.md`](./ETAT-DES-LIEUX.md) §1)
- [`../../../infra/backup/README.md`](../../../infra/backup/README.md) — mode d'emploi
  opérationnel de `stage` / `verify` / `test` (lots 1 et 2, livrés)
- `/opt/stacks/oim-duplicati/BACKUP_STRATEGY.md` — **hors dépôt**, sur le VPS : la
  doctrine de sauvegarde des 10 autres stacks, dont Eurio doit devenir le 11ᵉ cas
