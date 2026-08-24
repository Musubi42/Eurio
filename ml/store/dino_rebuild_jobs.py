"""État d'un rebuild de banque DINO lancé depuis l'écran — table locale.

Mêmes conventions que ``cohort_training_scans`` : helpers applicatifs
start → step → finish, le subprocess détaché possède le cycle de vie du job via
sa propre connexion. Cf. state/schema.sql §Rebuild de la banque d'ancres DINO.

⚠️ **Écrit toujours sur `store.local_state_store()`**, jamais sur le canonique :
sous Direction A ce dernier est une réplique read-only, et un job lancé depuis
l'écran ne doit pas dépendre du sens du flip pour pouvoir dire où il en est.
"""

from __future__ import annotations

import os
import sqlite3
import uuid

#: Au-delà, un job 'running' est tenu pour orphelin même si son PID paraît
#: vivant (l'OS réutilise les PID). Un rebuild + backfill complet tourne en
#: ~20 min sur MPS (12 454 assets, cf. ml/tasks.yml) ; 3 h laisse largement
#: la place à une machine lente sans laisser un mort « en cours » pour l'éternité.
MAX_RUNTIME_MIN = 180

#: Délai de grâce avant qu'un job sans PID soit considéré orphelin.
#:
#: 🔴 Trouvé en revue le 2026-08-24. `rebuild_start` insère la ligne, PUIS
#: `subprocess.Popen` tourne, PUIS `rebuild_set_pid` écrit le PID. Entre les
#: deux, `pid` est NULL — et `GET /dino/rebuild/status` faucheait le job à
#: chaque poll qui tombait dans cette fenêtre. Deux dégâts, le second pire que
#: le premier : l'écran annonçait un échec sur un job bien vivant, et la garde
#: 409 ne voyait plus de job en cours — un second clic lançait donc un DEUXIÈME
#: rebuild de vingt minutes sur la même banque.
STARTUP_GRACE_SEC = 60


def rebuild_start(
    conn: sqlite3.Connection, *, anchors_kind: str, encoder_version: str,
    log_path: str | None = None,
) -> str:
    job_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO dino_rebuild_jobs "
        "(id, anchors_kind, encoder_version, log_path) VALUES (?,?,?,?)",
        (job_id, anchors_kind, encoder_version, log_path),
    )
    conn.commit()
    return job_id


def rebuild_set_pid(conn: sqlite3.Connection, job_id: str, pid: int) -> None:
    conn.execute("UPDATE dino_rebuild_jobs SET pid=? WHERE id=?", (pid, job_id))
    conn.commit()


def rebuild_step(
    conn: sqlite3.Connection, job_id: str, *, step: str,
    build_id: str | None = None, n_anchors: int | None = None,
) -> None:
    """Passe à l'étape suivante. Écrit au fil de l'eau : c'est ce qui permet à
    l'écran de dire « ancres bâties, prédictions en cours » plutôt qu'un spinner
    indistinct pendant vingt minutes."""
    # `n_done`/`n_total` sont REMIS À ZÉRO : ils décrivent l'étape en cours, pas
    # le job. Sans ça, le passage `anchors` → `predictions` afficherait un
    # instant « 3187 / 16015 », c'est-à-dire deux étapes mélangées dans une
    # seule barre.
    conn.execute(
        "UPDATE dino_rebuild_jobs SET step=?, n_done=NULL, n_total=NULL, "
        "  build_id=COALESCE(?, build_id), n_anchors=COALESCE(?, n_anchors) "
        " WHERE id=?",
        (step, build_id, n_anchors, job_id),
    )
    conn.commit()


def rebuild_progress(
    conn: sqlite3.Connection, job_id: str, *, n_done: int, n_total: int | None = None,
) -> None:
    """Avancement de l'étape en cours. Appelé souvent — donc bon marché.

    ⚠️ **Un seul UPDATE, pas de transaction longue.** Le worker écrit ici
    pendant qu'il calcule ; tenir une transaction ouverte bloquerait la lecture
    du statut par l'API, et l'écran afficherait un chiffre figé en croyant que
    le job est bloqué — la panne qu'on essaie précisément de rendre visible.
    """
    conn.execute(
        "UPDATE dino_rebuild_jobs SET n_done = ?, n_total = COALESCE(?, n_total) "
        " WHERE id = ?",
        (n_done, n_total, job_id),
    )
    conn.commit()


def rebuild_finish(
    conn: sqlite3.Connection, job_id: str, *, status: str,
    n_predictions: int | None = None, error: str | None = None,
) -> None:
    conn.execute(
        "UPDATE dino_rebuild_jobs SET status=?, step='done', "
        "  n_predictions=COALESCE(?, n_predictions), error=?, "
        "  finished_at=datetime('now') WHERE id=?",
        (status, n_predictions, error, job_id),
    )
    conn.commit()


def latest_rebuild(
    conn: sqlite3.Connection, *, status: str | None = None
) -> sqlite3.Row | None:
    sql = "SELECT * FROM dino_rebuild_jobs"
    args: tuple = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    sql += " ORDER BY datetime(started_at) DESC LIMIT 1"
    return conn.execute(sql, args).fetchone()


def _pid_alive(pid: int | None) -> bool:
    """Le processus existe-t-il encore ? `PermissionError` = il existe mais ne
    nous appartient pas — donc vivant, et surtout pas à déclarer orphelin."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def reap_orphan_rebuilds(conn: sqlite3.Connection) -> int:
    """Marque `failed` les jobs 'running' dont le subprocess est mort.

    Sans ce filet, un `--reload` d'uvicorn au mauvais moment — ou un `kill` —
    laisse une ligne 'running' pour toujours, et la garde 409 refuse alors tout
    nouveau rebuild **définitivement**. L'écran dirait « en cours » sur un
    processus qui n'existe plus : la panne la plus difficile à diagnostiquer,
    parce qu'elle ressemble à de la patience.
    """
    n = 0
    for row in conn.execute(
        "SELECT id, pid, started_at FROM dino_rebuild_jobs WHERE status='running'"
    ).fetchall():
        age_sec = conn.execute(
            "SELECT (julianday('now') - julianday(?)) * 24 * 3600",
            (row["started_at"],),
        ).fetchone()[0] or 0.0
        # Un job sans PID est un job qui DÉMARRE, pas un orphelin — tant qu'il
        # est jeune. Sans cette grâce, tout poll de statut arrivant avant
        # `rebuild_set_pid` tuait le job et rouvrait la porte à un doublon.
        if row["pid"] is None and age_sec < STARTUP_GRACE_SEC:
            continue
        trop_vieux = age_sec > MAX_RUNTIME_MIN * 60
        if _pid_alive(row["pid"]) and not trop_vieux:
            continue
        rebuild_finish(
            conn, row["id"], status="failed",
            error="subprocess absent au démarrage de l'API (orphelin)",
        )
        n += 1
    return n
