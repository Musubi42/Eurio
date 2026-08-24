"""Rebuild de la banque d'ancres PUIS backfill des prédictions — un seul geste.

Lancé en subprocess détaché par ``POST /dino/rebuild`` (accueil admin), ou à la
main. Écrit sa progression dans ``dino_rebuild_jobs`` (base LOCALE) pour que
l'écran puisse dire à quelle étape on en est plutôt que d'afficher un spinner
indistinct pendant vingt minutes.

⛔ **LES DEUX ÉTAPES, TOUJOURS.** Rebâtir la banque sans recalculer les
prédictions laisse la base dans un état PIRE qu'avant : les prédictions
existantes répondent alors sur une banque qui n'existe plus, et **rien ne le
signale** — ni erreur, ni log, juste des suggestions subtilement fausses. C'est
pour ça que ce script existe au lieu de deux boutons.

⛔ **`EURIO_DB_READONLY` doit être levé.** Le build `2eur_all` TRACE sa
sélection dans `dino_class_references` : sous le flip Direction A du devShell il
refuse de démarrer. L'appelant (la route) pose l'environnement ; en ligne de
commande, c'est à toi de le faire.

    cd ml && EURIO_DB_READONLY= ./.venv/bin/python -m scripts.rebuild_dino_bank \\
        [--kind 2eur_all] [--job-id <id>]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_ML = Path(__file__).resolve().parents[1]
if str(_ML) not in sys.path:
    sys.path.insert(0, str(_ML))

from shared.verdict_scope import (  # noqa: E402
    VERDICT_ANCHORS_KIND,
    VERDICT_ENCODER_VERSION_FOR_KIND,
)
from store import local_state_store  # noqa: E402
from store.dino_rebuild_jobs import (  # noqa: E402
    rebuild_finish,
    rebuild_set_pid,
    rebuild_step,
)


#: Combien de lignes de sortie remonter dans le message d'erreur.
_CONTEXTE_ERREUR = 12


def _run(argv: list[str]) -> None:
    """Sous-processus synchrone. Une étape qui rate ARRÊTE le job.

    Surtout pas de `check=False` ici : enchaîner le backfill sur un build raté
    recalculerait 12 454 prédictions contre l'ancienne banque — du travail long,
    coûteux, et dont le résultat serait indiscernable d'un succès.

    🔴 Et l'erreur porte la CAUSE, pas seulement la commande. Le premier jet
    levait `échec (1) : … build_dino_anchors --kind 2eur_all --force`, ce qui
    s'affichait tel quel sur l'écran d'accueil : de quoi savoir QUOI a raté,
    jamais POURQUOI. Il a fallu aller ouvrir le fichier de log à la main pour
    découvrir un `RuntimeError` de deux lignes. Un job qu'on lance depuis un
    bouton doit rendre compte depuis ce bouton.
    """
    proc = subprocess.run(argv, cwd=str(_ML), capture_output=True, text=True)
    sortie = (proc.stdout or "") + (proc.stderr or "")
    # Le log garde TOUT : c'est lui qu'on relit quand la queue ne suffit pas.
    print(sortie, end="", flush=True)
    if proc.returncode == 0:
        return

    lignes = [ligne for ligne in sortie.strip().splitlines() if ligne.strip()]
    queue = "\n".join(lignes[-_CONTEXTE_ERREUR:])
    raise RuntimeError(
        f"échec ({proc.returncode}) de `{' '.join(argv[2:])}`\n{queue}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind", default=VERDICT_ANCHORS_KIND)
    ap.add_argument("--job-id", default=None,
                    help="ligne dino_rebuild_jobs à tenir à jour (optionnel)")
    args = ap.parse_args()

    encoder = VERDICT_ENCODER_VERSION_FOR_KIND[args.kind]
    conn = local_state_store()._connection() if args.job_id else None  # noqa: SLF001
    py = sys.executable

    if conn is not None:
        # 🔴 Le job enregistre SON PROPRE pid, tout de suite.
        #
        # Il était posé par l'appelant (la route, après `Popen`). Deux trous :
        # une ligne créée hors de la route n'avait jamais de pid, et même par la
        # route il existait une fenêtre. Or `reap_orphan_rebuilds` fauche les
        # jobs sans pid passé le délai de grâce — il a marqué `failed` un
        # rebuild qui tournait, pendant que la carte annonçait un échec sur un
        # processus bien vivant. Vécu le 2026-08-24.
        #
        # Le processus est le seul à savoir qu'il existe : c'est donc à lui de
        # le dire. La pose par l'appelant reste, en ceinture.
        rebuild_set_pid(conn, args.job_id, os.getpid())
        rebuild_step(conn, args.job_id, step="anchors")

    try:
        _run([py, "-m", "scripts.build_dino_anchors", "-v",
              "--kind", args.kind, "--force"])

        # Le build_id fraîchement produit, relu depuis le CANONIQUE (le build
        # vient de l'y écrire). On le stocke pour que l'écran puisse dire QUELLE
        # banque il a produite — sans ça, deux rebuilds successifs sont
        # indiscernables dans l'historique.
        build_id, n_anchors = None, None
        try:
            from store import Store, resolve_db_path

            c = Store(resolve_db_path(_ML / "state" / "eurio.db"))._connection()  # noqa: SLF001
            row = c.execute(
                "SELECT build_id, n_rows FROM dino_anchor_builds "
                " WHERE anchors_kind=? AND encoder_version=? "
                " ORDER BY datetime(built_at) DESC LIMIT 1",
                (args.kind, encoder),
            ).fetchone()
            if row is not None:
                build_id, n_anchors = row["build_id"], row["n_rows"]
        except Exception as exc:  # noqa: BLE001 — traçabilité, jamais fatale
            print(f"[rebuild] build_id non relu : {exc}", file=sys.stderr)

        if conn is not None:
            rebuild_step(conn, args.job_id, step="predictions",
                         build_id=build_id, n_anchors=n_anchors)
        _run([py, "-m", "scripts.backfill_dino_predictions", "-v",
              "--kind", args.kind, "--force"])

        if conn is not None:
            rebuild_finish(conn, args.job_id, status="done")
        print(f"[rebuild] terminé — banque {args.kind}/{encoder} "
              f"build={build_id} ancres={n_anchors}")
        return 0
    except Exception as exc:  # noqa: BLE001 — on veut la trace EN BASE
        if conn is not None:
            rebuild_finish(conn, args.job_id, status="failed", error=str(exc))
        print(f"[rebuild] ÉCHEC : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
