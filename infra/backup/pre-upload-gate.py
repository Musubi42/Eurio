#!/usr/bin/env python3
"""Portier du téléversement : Duplicati refuse de partir sur un staging invalide.

**Pourquoi ce fichier existe.** `stage` (02:00 UTC), `verify` (02:30) et le job
Duplicati (03:00) sont trois planifications *indépendantes*. Le 2026-08-16,
`stage` a échoué à 02:00 ; il retire `manifest.json` **avant** de commencer,
précisément pour qu'un staging interrompu soit détectable. Une heure plus tard,
Duplicati a fidèlement téléversé ce staging sans sentinelle, et a rapporté un
succès. Constaté lors de l'exercice de restauration : **la version distante la
plus récente était invérifiable** — c'est celle qu'on aurait prise en urgence.

**Ce que ça arbitre.** Bloquer le téléversement peut faire sauter une nuit de
sauvegarde. On l'accepte, pour une raison chiffrable : la rétention est de 30
*versions*, pas de 30 jours. Une nuit sautée ne consomme aucune version et
laisse intacte la dernière bonne ; une nuit téléversée par-dessus un staging
mort en consomme une et fait passer l'archive utilisable un cran plus loin dans
l'historique. Sauter est réversible, empiler du vide l'est moins.

**Comment le silence est évité.** En refusant, on sort en code 5 : Duplicati
marque l'opération en ERREUR. Le job ne pingue son anneau 3 (`eurio-uploaded`)
qu'en cas de succès — l'absence de ping fait donc rougir Kuma. Le portier ne
notifie rien lui-même : un détecteur qui porte sa propre alerte est le défaut
que ce chantier corrige (D-06).

Codes de sortie — ce sont ceux qu'attend `--run-script-before`, pas les nôtres :

    0  OK, lancer la sauvegarde
    1  OK, ne pas la lancer (annulation silencieuse)
    2  avertissement, lancer
    3  avertissement, ne pas lancer
    4  erreur, lancer
    5  erreur, ne pas lancer   ← ce qu'on utilise pour refuser

Usage (dans le conteneur Duplicati, via l'option du job) :

    --run-script-before=/eurio-gate.py

Réglages par variables d'environnement :

    EURIO_GATE_STAGING     répertoire à contrôler   (défaut: /eurio-source)
    EURIO_GATE_MAX_AGE_H   âge maximal du manifeste (défaut: 36)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

STAGING = os.environ.get("EURIO_GATE_STAGING", "/eurio-source")
MAX_AGE_H = float(os.environ.get("EURIO_GATE_MAX_AGE_H", "36"))

REFUSE = 5  # erreur + ne pas lancer
ALLOW = 0


def refuse(reason: str) -> int:
    # stderr : Duplicati le consigne dans le journal du job, et c'est ce qu'on
    # lira le lendemain en se demandant pourquoi il n'y a pas de version.
    print(f"REFUS DU TÉLÉVERSEMENT — {reason}", file=sys.stderr)
    print(
        "  Le staging n'est pas dans un état sauvegardable. La dernière version "
        "distante valide reste intacte dans la rétention (30 versions).\n"
        "  Réparer : /opt/eurio/infra/backup/eurio-backup.sh stage puis verify.",
        file=sys.stderr,
    )
    return REFUSE


def main() -> int:
    manifest_path = os.path.join(STAGING, "manifest.json")

    if not os.path.isdir(STAGING):
        return refuse(f"répertoire de staging absent : {STAGING}")

    if not os.path.exists(manifest_path):
        return refuse(
            f"manifeste absent : {manifest_path}. "
            "`stage` le retire avant de commencer : son absence signifie qu'il "
            "a échoué en cours de route."
        )

    try:
        with open(manifest_path) as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as exc:
        return refuse(f"manifeste illisible : {exc}")

    created = manifest.get("created_utc")
    if not created:
        return refuse("manifeste sans `created_utc` — format inattendu")

    try:
        stamp = dt.datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError as exc:
        return refuse(f"`created_utc` illisible ({created}) : {exc}")

    age_h = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds() / 3600
    if age_h > MAX_AGE_H:
        return refuse(
            f"staging périmé : {age_h:.1f} h (plafond {MAX_AGE_H:.0f} h). "
            "Téléverser à nouveau le même staging figé consommerait une version "
            "de rétention sans rien apporter."
        )

    # Les fichiers que le manifeste décrit doivent être là. Un manifeste frais
    # qui décrit des fichiers absents est le pire des cas : sentinelle verte,
    # contenu manquant.
    for name in manifest.get("files", {}):
        path = os.path.join(STAGING, name)
        if not os.path.exists(path):
            return refuse(f"le manifeste décrit `{name}`, absent du staging")

    print(f"staging OK — manifeste de {created} ({age_h:.1f} h), téléversement autorisé")
    return ALLOW


if __name__ == "__main__":
    sys.exit(main())
