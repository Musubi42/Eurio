# PLAY-INTERNE — mettre Eurio 0.2.0 dans une main qui n'est pas la tienne

> Étape 4 « la nef » de [`PLAN.md`](./PLAN.md), sous D4 : **on publie ce qui
> existe**. Pas de feature, pas de modèle, pas d'écran nouveau. Une pièce non
> reconnue est une donnée, pas un bloqueur.
>
> Ce document sépare ce qui est **prêt** (fait par la machine, vérifiable ici)
> de ce qui reste **au PO** (compte Google, décisions, clics dans la console).
> Les critères 4.3 à 4.6 du plan sont tous dans la seconde colonne.

## 0. Ce qui est prêt

| Artefact | Où | Commande |
|---|---|---|
| **AAB signé** (ce que la Play Console exige) | `app-android/build/outputs/bundle/fullRelease/app-android-full-release.aab` | `go-task android:bundle` |
| **APK signé** (installation directe par `adb`) | `app-android/build/outputs/apk/full/release/app-android-full-release.apk` | `go-task android:release` |
| **Clé de signature** | `secrets/dev.env` (SOPS + age, ADR-015), quatre variables `ANDROID_RELEASE_*` | `go-task secrets:list \| grep ANDROID_RELEASE` |
| **Version** | `versionCode 2`, `versionName 0.2.0` | `grep -n 'versionCode\|versionName' app-android/build.gradle.kts` |
| **Icône** | `app-android/src/main/res/mipmap-*/ic_launcher*` (adaptative, toutes densités) | — |
| **Nom affiché** | `Eurio` (`res/values/strings.xml`) | — |
| **Journal des scans (D5)** | table Room `scan_events`, aucune UI | cf. §6 |

Le keystore lui-même n'existe **nulle part** en clair : il est encodé en base64
dans `secrets/dev.env` et matérialisé sous `app-android/build/release-signing/`
au moment du build, dans un répertoire gitignoré. Une machine sans la clé age ne
peut pas produire de build release — elle échoue avec un message qui dit quoi
faire, pas avec un APK non signé.

**Le certificat de cette clé** (à comparer si un jour on doute d'un artefact) :

```
Signer #1 certificate DN: CN=Eurio, OU=Musubi42, O=Musubi42, L=Lille, ST=Hauts-de-France, C=FR
Signer #1 certificate SHA-256 digest: b43cbdc8e3d20ffae0462e68d86927e72ff35c28c0925afa10bd4116b7b43c85
Signer #1 certificate SHA-1 digest:   6c14f0387a14609f302c49a9f4a33e440bd7c66d
```

⚠️ **Perdre cette clé, c'est perdre l'app.** Elle vit dans `secrets/dev.env`,
donc dans la chaîne de sauvegarde du dépôt et dans le password manager via la
clé age (`~/.config/sops/age/keys.txt`). Vérifie que la clé age est bien
sauvegardée **avant** le premier téléversement, pas après.

## 1. Le compte développeur — au PO

- Compte Google Play Console : **25 $ US une fois**, pas d'abonnement.
- Vérification d'identité obligatoire (pièce d'identité ; pour un compte
  *organisation*, en plus un numéro D-U-N-S). Compter **quelques jours**, c'est
  le seul délai incompressible de toute l'étape — à lancer en premier.
- Type de compte : **personnel** suffit pour une piste interne.

> 🪤 Le piège connu : depuis novembre 2023, un compte **personnel** créé
> récemment doit, **pour passer en production**, avoir fait tourner un test
> **fermé** avec au moins 12 testeurs pendant 14 jours consécutifs. La piste
> **interne** n'y est pas soumise — donc rien ne bloque l'étape 4. Mais si la
> suite du chemin est le Play Store public, ces 12 testeurs / 14 jours arrivent
> après, et le test **interne** ne compte pas pour les satisfaire.

## 2. Créer l'application

Play Console → *Créer une application*.

| Champ | Valeur |
|---|---|
| Nom de l'application | `Eurio` |
| Langue par défaut | Français (France) |
| Application ou jeu | Application |
| Gratuite ou payante | **Gratuite** (irréversible — une app gratuite ne peut jamais devenir payante) |
| `applicationId` | `com.musubi.eurio` (fixé par l'APK, non modifiable après le premier téléversement) |

## 3. Les déclarations « Contenu de l'application » — ce qui bloque réellement

Play refuse la publication tant que ces cases ne sont pas cochées, y compris
pour une piste interne. Dans l'ordre de la console :

1. **Politique de confidentialité** — une URL publique. Texte proposé au §4.
2. **Accès à l'application** — « Toutes les fonctionnalités sont disponibles
   sans restriction d'accès » : Eurio n'a pas de compte utilisateur, le coffre
   est 100 % local (Room). Rien à fournir comme identifiants de test.
3. **Annonces** — **non**, l'app ne contient pas de publicité.
4. **Classification du contenu** — questionnaire IARC, ~5 minutes. Eurio est un
   utilitaire de collection : aucune violence, aucun contenu sensible, aucun
   achat. Résultat attendu : **PEGI 3 / Tout public**.
5. **Public cible** — 18 ans et plus (ou 13+), et **non** conçue pour les
   enfants : cela évite d'entrer dans les obligations « Familles ».
6. **Sécurité des données** (le formulaire le plus long, et le plus simple ici) :
   - collecte de données : **aucune** ;
   - partage avec des tiers : **aucun** ;
   - données stockées sur l'appareil uniquement, non transmises ;
   - suppression : désinstaller l'application suffit.

   ⚠️ Une seule nuance à ne pas escamoter : l'app déclare la permission
   `INTERNET` et embarque un client Supabase. En 0.2.0 le catalogue est
   **packagé dans l'APK** (`app_core.db`) et le scan tourne **sur l'appareil** —
   aucune donnée personnelle ne part. Si un jour une synchronisation de coffre
   arrive, ce formulaire est le **premier** à rouvrir.
7. **Applications gouvernementales / financières** — non.

## 4. Politique de confidentialité — texte proposé

À publier telle quelle sur une URL stable (une page de `musubi.dev` suffit ;
un Gist public fait l'affaire pour la piste interne), puis coller l'URL dans la
console.

> **Politique de confidentialité — Eurio**
> Dernière mise à jour : 11 septembre 2026.
>
> Eurio est une application de collection de pièces en euros qui fonctionne
> hors ligne. Elle ne demande aucun compte, aucune inscription et aucune
> adresse e-mail.
>
> **Ce qui est collecté : rien.** Eurio ne collecte, ne transmet et ne vend
> aucune donnée personnelle. Aucun outil d'analyse d'audience, aucun traceur
> publicitaire et aucun réseau publicitaire n'y est intégré.
>
> **Ce qui reste sur votre téléphone.** Les photos prises pendant un scan, les
> pièces ajoutées à votre coffre et la date de vos scans sont enregistrées dans
> la mémoire privée de l'application, sur votre appareil uniquement. La
> reconnaissance des pièces s'exécute localement : aucune image ne quitte le
> téléphone.
>
> **Permissions demandées.** L'appareil photo, pour scanner une pièce. L'accès
> réseau, déclaré pour de futures fonctions optionnelles, n'est pas utilisé pour
> transmettre vos données dans cette version.
>
> **Suppression.** Désinstaller Eurio efface définitivement toutes les données
> qu'elle a créées. Aucune copie n'existe ailleurs.
>
> **Contact.** raphaelthi59@gmail.com

## 5. Fiche du Store et téléversement

**Fiche minimale** (obligatoire avant de publier une version, même interne) :

| Élément | Contrainte Play | État |
|---|---|---|
| Description courte | ≤ 80 caractères | à écrire — proposition : *« Scannez vos pièces en euros et suivez votre collection, hors ligne. »* (76 car.) |
| Description complète | ≤ 4 000 caractères | à écrire |
| Icône | PNG 32 bits, 512 × 512, ≤ 1 Mo | **à exporter** depuis `ic_launcher` — la console n'accepte pas les WEBP de l'APK |
| Image de présentation | JPG/PNG 1024 × 500 | à produire |
| Captures téléphone | 2 à 8, 16:9 ou 9:16, côté 320–3 840 px | **à prendre sur l'appareil du PO** : le scan, le coffre, le profil |
| Catégorie | Style de vie, ou Outils | au choix du PO |

**Téléversement** : *Test* → *Test interne* → *Créer une version* →
téléverser `app-android-full-release.aab`.

> 🪤 Au premier téléversement, Google propose la **signature d'application Play**
> (*Play App Signing*). L'accepter — c'est la voie par défaut et elle protège
> d'une perte de clé. Conséquence à connaître : notre clé devient la **clé de
> téléversement**, et Google en génère une autre pour signer ce que les
> utilisateurs installent. Les empreintes affichées dans la console ne
> correspondront donc **pas** au SHA-256 collé au §0 — ce n'est pas une anomalie.

## 6. Les testeurs, et la mesure des sept jours

- Piste interne : jusqu'à **100 testeurs**, ajoutés par **adresse e-mail Google**
  (créer une liste dans *Test interne → Testeurs*). Le plan en demande cinq.
- La version est disponible pour eux en **quelques minutes** — la piste interne
  ne passe pas par la revue éditoriale.
- Chaque testeur doit **accepter l'invitation** via le lien d'opt-in, puis
  installer depuis le Play Store. Sans l'opt-in, il ne voit rien.
- Falsification à jouer (PLAN §Étape 4) : installer sur un téléphone vierge,
  **sans compte, sans réseau**, et vérifier que le scan s'ouvre.

### Lire le compteur (D5)

Un scan qui aboutit au coffre écrit une ligne dans la table Room `scan_events`
(`eurio_id`, `occurred_at` en millisecondes). Aucun écran ne l'affiche : R1
interdit d'inventer une scène Android sans équivalent proto, et le geste
d'export n'est pas encore tranché.

Sur une machine de dev, avec un **build debug** :

```bash
go-task android:install   # build debug
adb shell am broadcast -a com.musubi.eurio.DUMP_SCAN_JOURNAL \
  -n com.musubi.eurio/com.musubi.eurio.debug.ScanJournalDumpReceiver
adb logcat -d ScanJournal:I '*:S'
```

Sortie : le total, le nombre de jours distincts (en fuseau **local**), la plus
longue série consécutive, puis la liste des jours.

Toujours en debug, la base elle-même :

```bash
adb shell run-as com.musubi.eurio \
  sqlite3 databases/eurio.db "SELECT date(occurred_at/1000,'unixepoch','localtime') AS jour, COUNT(*) FROM scan_events GROUP BY jour ORDER BY jour;"
```

### ⛔ Ce qui manque, et qu'il ne faut pas croire acquis

**Le compteur d'un testeur n'est aujourd'hui pas lisible.** Les deux commandes
ci-dessus ne marchent que sur un build **debug** : `run-as` exige une
application débogable, et le receiver de dump n'est compilé que dans
`src/debug/` — il est absent de l'AAB livré. Ce n'est pas un oubli, c'est le
refus d'exporter un canal de dump dans le build du Play Store.

Le critère 4.5 (« un scan par jour venu d'ailleurs, sept jours de suite »)
**ne peut donc pas encore être mesuré à distance**. Il manque un geste d'export
côté utilisateur — un bouton « partager mon activité » depuis le Profil, qui
produirait un petit fichier que le testeur renvoie. C'est un **écran nouveau** :
R1 impose de le dessiner d'abord dans le proto (`admin/packages/proto/`,
scène `profile/`) et de l'inscrire dans `scene-parity.md` avant la moindre ligne
de Compose. D4 gèle toute nouveauté jusqu'à la piste interne : le geste est
donc à trancher par le PO **après** l'ouverture de la piste, pas avant.

En attendant, la trace **existe et s'accumule** sur les téléphones des testeurs
depuis la 0.2.0 : rien n'est perdu, seule la lecture manque.

## 7. Après la publication — critère 4.6

*Qualité → Android vitals* donne les plantages et les ANR, agrégés sur les
appareils opt-in. Attendu : **0 ANR, 0 plantage sur le scan**. La remontée met
quelques heures à apparaître, et une piste interne à cinq testeurs produit peu
de volume — l'absence de plantage y vaut donc moins qu'une observation directe.
Le PO complète avec ce que les cinq lui disent.

## 8. Ordre d'exécution, pour le PO

1. Créer le compte développeur et lancer la vérification d'identité (délai).
2. Vérifier que `~/.config/sops/age/keys.txt` est sauvegardé hors machine.
3. Publier la politique de confidentialité sur une URL stable.
4. Exporter l'icône 512 × 512 et prendre 2 à 8 captures.
5. Créer l'app, remplir « Contenu de l'application » (§3) et la fiche (§5).
6. `go-task android:bundle`, téléverser l'AAB, accepter Play App Signing.
7. Créer la liste des cinq testeurs, publier sur la piste interne.
8. Jouer la falsification : téléphone vierge, sans compte, sans réseau.
9. Coller dans `SUIVI.md` : la capture de la console (4.3), la liste des
   testeurs (4.4), et ce que les cinq rapportent jour par jour (4.5).
