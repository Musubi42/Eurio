"""L'écart DINO servi à l'accueil, et le job qui le referme.

Trois choses sont verrouillées ici, et chacune casserait SANS ERREUR :

1. **L'écart se compare en `datetime()`, jamais en chaînes.** Trois formats
   d'horodatage cohabitent dans la base ; une comparaison de chaînes classe
   toute prédiction comme antérieure à tout build du même jour. Le piège a déjà
   coûté 12 454 faux « périmés » en août 2026 (`store/encoder_bench.py`).
2. **Une mesure impossible ne se lit pas « tout va bien ».** Table absente ⇒
   409, pas un écart de zéro.
3. **Le geste est lourd, le chiffre ne l'est pas.** La route de lecture doit
   vivre sur les DEUX apps, celle qui lance le rebuild sur la workstation
   seulement — sinon le VPS expose un bouton qui ne peut pas marcher, ou
   l'accueil perd son chiffre dès que le Mac est éteint.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from store import Store
from store.dino_drift import DriftNotMeasurable, dino_drift

KIND, ENCODER = "2eur_all", "dinov2-vitl14"


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    c.row_factory = sqlite3.Row
    return c


def _build(c, built_at: str, build_id: str = "b1") -> None:
    c.execute(
        "INSERT INTO dino_anchor_builds (build_id, anchors_kind, encoder_version, "
        " built_at, n_classes, n_rows, n_canonical, n_exemplars, n_no_canonical) "
        "VALUES (?,?,?,?,10,20,10,10,0)",
        (build_id, KIND, ENCODER, built_at))
    c.commit()


def _asset(c, aid: str, *, eurio_id: str | None = None, eligible: int = 0) -> None:
    c.execute("INSERT OR IGNORE INTO source_images (id, source, source_ref, "
              " storage_path) VALUES ('SI','ebay','r1','raw.jpg')")
    c.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, storage_path, "
        " storage_status, eurio_id, training_eligible, resolution_status) "
        "VALUES (?, 'SI', 0, ?, 'present', ?, ?, 'needs_review')",
        (aid, f"{aid}.png", eurio_id, eligible))
    c.commit()


def _prediction(c, aid: str, computed_at: str) -> None:
    c.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
        " anchors_kind, anchors_count, top_k_json, computed_at) "
        "VALUES (?,?,?,1,'[]',?)",
        (aid, ENCODER, KIND, computed_at))
    c.commit()


def test_une_prediction_du_meme_jour_n_est_pas_declaree_perimee(conn):
    """Le piège des trois formats d'horodatage, verrouillé.

    Le build est écrit en ISO avec un `T` (`2026-08-22T18:06:22+00:00`), la
    prédiction avec un espace (`2026-08-22 18:14:50`) — et elle lui est
    POSTÉRIEURE de huit minutes. Comparées comme des chaînes, `' '` (0x20) passe
    avant `'T'` (0x54) : la prédiction paraît antérieure, et l'écran réclame un
    backfill de 20 minutes qui ne sert à rien.
    """
    _build(conn, "2026-08-22T18:06:22+00:00")
    _asset(conn, "A1")
    _prediction(conn, "A1", "2026-08-22 18:14:50")

    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_predictions_stale == 0
    assert d.n_assets_without_prediction == 0


def test_une_prediction_anterieure_au_build_est_bien_perimee(conn):
    """Le contrôle inverse — sans lui, le test précédent passerait aussi avec
    un compteur câblé à zéro."""
    _build(conn, "2026-08-22T18:06:22+00:00")
    _asset(conn, "A1")
    _prediction(conn, "A1", "2026-08-21 09:00:00")

    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_predictions_stale == 1
    assert d.is_stale


def test_un_crop_sans_prediction_compte_dans_l_ecart(conn):
    _build(conn, "2026-08-22T18:06:22+00:00")
    _asset(conn, "A1")
    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_assets_without_prediction == 1
    assert d.is_stale


def test_une_banque_jamais_batie_est_perimee_pas_a_jour(conn):
    """Zéro écart et « jamais bâtie » ne doivent pas avoir la même tête.

    C'est l'état où un écart nul serait le plus trompeur : rien à rattraper
    parce que rien n'existe.
    """
    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.built_at is None
    assert d.is_stale, "aucune banque n'est le PIRE état, pas un état neutre"


def test_une_table_absente_leve_au_lieu_de_rendre_zero(tmp_path):
    c = sqlite3.connect(tmp_path / "vide.db")
    c.row_factory = sqlite3.Row
    with pytest.raises(DriftNotMeasurable):
        dino_drift(c, anchors_kind=KIND, encoder_version=ENCODER)


def test_le_chiffre_vit_sur_les_deux_apps_le_bouton_sur_une_seule():
    """La lecture partout, le geste sur la machine de calcul.

    Monter le rebuild sur le lean donnerait au VPS un bouton qui ne peut pas
    marcher (ni torch ni banque) ; ne pas monter l'écart sur le lean ferait
    disparaître le chiffre dès que le Mac est éteint — or savoir ce qui manque
    n'a pas à dépendre d'une machine allumée.
    """
    lean = (ML_DIR / "serving/server_serve.py").read_text()
    full = (ML_DIR / "serving/server.py").read_text()

    assert "dino_drift_router" in lean and "dino_drift_router" in full
    assert "dino_rebuild_router" in full
    assert "dino_rebuild_router" not in lean, (
        "le VPS n'a ni torch ni banque : ce bouton y serait un mensonge")


def test_un_job_orphelin_ne_bloque_pas_les_suivants(conn):
    """Un `running` dont le processus est mort doit être fauché.

    Sans ce filet, la garde 409 refuse TOUT rebuild ultérieur, définitivement,
    et l'écran affiche « en cours » sur un processus qui n'existe plus. Cette
    panne-là ressemble à de la patience — c'est ce qui la rend coûteuse.
    """
    from store.dino_rebuild_jobs import (
        latest_rebuild, reap_orphan_rebuilds, rebuild_set_pid, rebuild_start,
    )

    job_id = rebuild_start(conn, anchors_kind=KIND, encoder_version=ENCODER)
    rebuild_set_pid(conn, job_id, 2_147_483_600)  # PID qui n'existe pas
    assert reap_orphan_rebuilds(conn) == 1

    row = latest_rebuild(conn)
    assert row["status"] == "failed" and row["error"]
    assert latest_rebuild(conn, status="running") is None


def test_la_route_d_ecart_repond_par_HTTP(conn, tmp_path):
    """Le câblage, pas seulement le calcul : dépendances, modèle, 409.

    Le test de montage ci-dessus ne dit que « le chemin existe ». Une dépendance
    mal typée ou un `response_model` incompatible le passe et rend 500 en
    production — sur une carte d'accueil que personne ne surveille. Le même
    trou, sur la route de recadrage, cachait un 500 depuis toujours (garde
    `if asset_id is None` sur une fonction qui lève au lieu de rendre None).
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from serving.auth_principal import Principal, require_principal
    from serving.deps import db_connection
    from serving import dino_drift_routes

    _build(conn, "2026-08-22T18:06:22+00:00")
    _asset(conn, "A1")
    _prediction(conn, "A1", "2026-08-22 18:14:50")

    app = FastAPI()
    app.include_router(dino_drift_routes.router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="t", email="t@test.local", roles=["admin"],
        scopes={"lab:read"}, auth_method="api_token",
    )
    app.dependency_overrides[db_connection] = lambda: conn
    client = TestClient(app)

    r = client.get("/dino/drift")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["anchors_kind"] == KIND
    assert body["n_predictions_stale"] == 0
    assert body["build_id"] == "b1"
    assert body["is_stale"] is False

    # Une banque qui n'existe pas ne lève pas : elle rend l'aveu qu'elle n'a
    # jamais été bâtie. C'est la vérité, et c'est actionnable.
    r = client.get("/dino/drift?anchors_kind=nexistepas&encoder_version=x")
    assert r.status_code == 200, r.text
    assert r.json()["built_at"] is None and r.json()["is_stale"] is True


def test_un_job_qui_demarre_n_est_pas_fauche_avant_d_avoir_son_pid(conn):
    """La course entre l'INSERT et l'écriture du PID.

    🔴 Trouvée en revue le 2026-08-24. `rebuild_start` insère la ligne, puis
    `Popen` tourne, puis `rebuild_set_pid` écrit le PID. `GET .../status`
    faucheait tout job à `pid IS NULL` — donc, si un poll tombait dans cette
    fenêtre : l'écran annonçait un échec sur un job bien vivant, ET la garde 409
    ne voyait plus de job en cours, si bien qu'un second clic lançait un
    DEUXIÈME rebuild de vingt minutes sur la même banque.
    """
    from store.dino_rebuild_jobs import (
        latest_rebuild, reap_orphan_rebuilds, rebuild_start,
    )

    job_id = rebuild_start(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert reap_orphan_rebuilds(conn) == 0, "un job qui démarre n'est pas orphelin"

    row = latest_rebuild(conn, status="running")
    assert row is not None and row["id"] == job_id, (
        "la garde 409 doit encore voir ce job — sinon un second clic double le travail")


def test_le_geste_lourd_n_exige_pas_de_principal(conn):
    """Les routes `:8042` sont appelées en `fetch` NU par le front.

    🔴 Corrigé en revue le 2026-08-24 : elles portaient
    `require_scope("review:arbitrate")`. Or cette API-ci n'a pas de session, et
    le PAT que détient le front vaut pour le CANONIQUE. Le bouton rendait donc
    401 à chaque clic et le statut restait nul — un bouton mort. Ce qui protège
    est ailleurs : l'API n'écoute que la machine de l'opérateur, et le bouton
    n'est dessiné que pour un arbitre (`showHeavyGesture`).
    """
    from serving.auth_principal import Principal
    from serving import dino_rebuild_routes as m

    for route in m.router.routes:
        annotations = getattr(route.endpoint, "__annotations__", {})
        principals = [n for n, t in annotations.items() if t is Principal]
        assert not principals, (
            f"{route.path} exige {principals} — le front appelle :8042 en "
            "`fetch` nu, la route serait inatteignable")


def test_les_classes_gagnantes_se_comptent_a_la_maille_classe(conn):
    """La banque indexe une COURANTE sous le représentant de son groupe.

    🔴 Corrigé en revue le 2026-08-24. Comparer `image_assets.eurio_id` à
    `class_id` classait toute courante non-représentante comme « gagnerait une
    photo », **à jamais** : aucun rebuild ne pouvait faire baisser le compteur,
    puisque rien ne l'y ferait entrer sous ce nom-là. Mesuré sur la réplique le
    jour même : 25 classes annoncées, 16 réelles.
    """
    _build(conn, "2026-08-22T18:06:22+00:00")
    conn.execute(
        "INSERT OR IGNORE INTO design_groups (id, designation) "
        "VALUES ('fr-2euro-standard-t1', 'France 2 € courante, 1er type')")
    # Un groupe de dessin : le représentant est le millésime le plus ancien.
    for eid, year in (("fr-1999-2eur-standard", 1999), ("fr-2007-2eur-standard", 2007)):
        conn.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, "
            " is_commemorative, design_group_id) "
            "VALUES (?, 'FR', ?, 2.0, 0, 'fr-2euro-standard-t1')", (eid, year))
    # La banque ne connaît QUE le représentant — c'est le cas nominal.
    conn.execute(
        "INSERT INTO dino_class_references (anchors_kind, class_id, eurio_id, "
        " method, encoder_version) VALUES (?, 'fr-1999-2eur-standard', "
        " 'fr-1999-2eur-standard', 'fps', ?)", (KIND, ENCODER))
    # Un crop validé sur le MEMBRE, pas sur le représentant.
    _asset(conn, "A1", eurio_id="fr-2007-2eur-standard", eligible=1)
    conn.commit()

    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_classes_would_gain_anchor == 0, (
        "sa classe A un exemplaire — sous le nom du représentant")


def test_un_crop_que_le_build_a_deja_refuse_ne_compte_plus(conn):
    """D15 — sans cette porte, le compteur ne peut pas retomber à zéro.

    Un crop éligible au SQL que le build servi n'a PAS pris a été refusé
    (plancher `floor_sim`, plafond de la classe, ou FPS qui ne l'a pas choisi).
    Le prochain build le refusera pareil, sur la même donnée : le compter, c'est
    réclamer éternellement une heure de calcul sans effet.
    """
    _build(conn, "2026-08-24T20:41:15+00:00")
    conn.execute("INSERT INTO coins (eurio_id, country, year, face_value, "
                 " is_commemorative) VALUES ('fr-2017-rodin','FR',2017,2.0,1)")
    _asset(conn, "A9", eurio_id="fr-2017-rodin", eligible=1)
    conn.execute("UPDATE image_assets SET face='obverse', "
                 " resolution_status='manual', "
                 " resolved_at='2026-08-24T09:00:00Z', "
                 " fetched_at='2026-08-23 17:13:42' WHERE id='A9'")
    conn.commit()
    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_classes_would_gain_anchor == 0, "le build l'a déjà refusé"

    # Le même crop, tranché APRÈS le build : aucun build ne l'a vu, il compte.
    conn.execute("UPDATE image_assets SET resolved_at='2026-08-24T21:00:00Z' "
                 " WHERE id='A9'")
    conn.commit()
    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_classes_would_gain_anchor == 1


def test_le_job_n_efface_pas_le_flip_direction_a():
    """`EURIO_DB_READONLY` ne doit PAS être vidé par la route.

    🔴 Vécu depuis l'écran le 2026-08-24, quatre minutes après le déploiement.
    Le premier jet le vidait, en croyant lever un garde-fou : `ml/tasks.yml`
    prévient que le build « refuse de démarrer » sous le flip. Vidé, `Store`
    tente d'ouvrir la RÉPLIQUE en écriture et la refuse pour la raison
    INVERSE — `RuntimeError: Refus d'ouvrir la réplique en écriture`. Le job
    mourait en une seconde.

    La vérité : sous Direction A ce build n'a besoin d'AUCUNE base inscriptible.
    `preflight_db_traceability` voit que le push est actif et envoie la trace au
    canonique (`POST /ingest/dino-references`). La note de `tasks.yml` est
    antérieure à ce chemin — un avertissement périmé qui a coûté un aller-retour.
    """
    src = (ML_DIR / "serving/dino_rebuild_routes.py").read_text()
    for ligne in src.splitlines():
        nu = ligne.strip()
        if nu.startswith("#"):
            continue
        assert "EURIO_DB_READONLY" not in nu, (
            f"la route ne doit pas toucher au flip : {nu!r}")


def test_une_etape_ratee_remonte_sa_CAUSE_pas_sa_commande(tmp_path, monkeypatch):
    """L'erreur affichée sur l'accueil doit dire POURQUOI.

    Le premier jet levait `échec (1) : … build_dino_anchors --kind 2eur_all`,
    affiché tel quel : de quoi savoir QUOI a raté, jamais pourquoi. Il a fallu
    ouvrir le fichier de log à la main. Un job qu'on lance depuis un bouton doit
    rendre compte depuis ce bouton.
    """
    import sys

    from scripts.rebuild_dino_bank import _run

    script = tmp_path / "rate.py"
    script.write_text(
        "import sys\n"
        "print('bruit de contexte')\n"
        "print('RuntimeError: la réplique est read-only', file=sys.stderr)\n"
        "sys.exit(3)\n"
    )

    with pytest.raises(RuntimeError) as exc:
        _run([sys.executable, str(script)])

    message = str(exc.value)
    assert "la réplique est read-only" in message, (
        "la cause doit voyager avec l'échec, pas rester dans un fichier de log")
    assert "(3)" in message, "le code de sortie reste utile pour trier"


def test_la_sortie_est_streamee_pendant_l_execution(tmp_path, capfd):
    """Le journal doit vivre PENDANT le job, pas seulement après.

    🔴 Le premier correctif de l'échec muet utilisait `capture_output=True` :
    la cause arrivait bien dans l'erreur, mais toute la sortie était retenue
    jusqu'à la fin du sous-processus. Sur un backfill de dix-huit minutes, le
    journal restait vide tout du long — impossible de distinguer « ça avance »
    de « c'est bloqué ». Gagner le POURQUOI en perdant le PENDANT n'est pas un
    progrès : un job lancé depuis un bouton doit rendre compte des deux.
    """
    import sys

    from scripts.rebuild_dino_bank import _run

    script = tmp_path / "lent.py"
    script.write_text(
        "import sys, time\n"
        "for i in range(3):\n"
        "    print(f'étape {i}', flush=True)\n"
        "    time.sleep(0.05)\n"
    )
    _run([sys.executable, str(script)])

    sortie = capfd.readouterr().out
    assert "étape 0" in sortie and "étape 2" in sortie, (
        "chaque ligne doit atteindre le journal")


def test_le_job_enregistre_son_propre_pid(tmp_path, monkeypatch):
    """Le processus est le seul à savoir qu'il existe — donc c'est à lui de le dire.

    🔴 Vécu le 2026-08-24. Le pid était posé par l'APPELANT (la route, après
    `Popen`). Une ligne de job créée autrement n'en avait donc jamais, et
    `reap_orphan_rebuilds` l'a marquée `failed` passé le délai de grâce —
    pendant que le rebuild tournait toujours. La carte annonçait un échec sur un
    processus bien vivant, et la garde 409 rouvrait la porte à un doublon.

    Le correctif ne consiste pas à allonger la grâce (ça ne fait que déplacer la
    fenêtre) mais à supprimer la dépendance : le runner écrit `os.getpid()` dès
    qu'on lui donne un `--job-id`.
    """
    import ast

    src = (ML_DIR / "scripts/rebuild_dino_bank.py").read_text()
    arbre = ast.parse(src)
    appels = [
        n for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "rebuild_set_pid"
    ]
    assert appels, "le runner doit enregistrer son propre pid"
    assert any(
        isinstance(a, ast.Call) and getattr(a.func, "attr", "") == "getpid"
        for appel in appels for a in appel.args
    ), "le pid enregistré doit être CELUI DU RUNNER (os.getpid()), pas un argument"


def test_le_build_id_est_relu_au_CANONIQUE_pas_dans_la_replique():
    """Sous Direction A, la trace d'un build ne passe pas par la base locale.

    🔴 Mesuré le 2026-08-24 sur le premier vrai rebuild. Le runner relisait
    `dino_anchor_builds` via `resolve_db_path` — donc dans la RÉPLIQUE, que le
    devShell désigne. Mais la trace part au canonique par
    `POST /ingest/dino-references` et n'y redescend qu'au prochain
    `pull-replica` : le job a enregistré `a55e6594 / 1909 ancres` pendant que le
    canonique portait `53d22c38 / 2062`. La carte aurait annoncé « rebuild OK »
    en citant la banque d'AVANT — un chiffre plausible, stable, et faux.

    C'est le piège n°1 du dépôt (`eurio-data-writes`) sous une forme LECTURE :
    on lit le miroir en croyant lire la source.
    """
    import ast

    arbre = ast.parse((ML_DIR / "scripts/rebuild_dino_bank.py").read_text())
    noms = {
        n.func.id for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    } | {
        n.func.attr for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "get_json" in noms, "la trace se relit au canonique, par HTTP"
    assert "resolve_db_path" not in noms, (
        "relire la trace dans la base locale rend l'avant-dernier build")


def test_la_progression_est_remise_a_zero_entre_les_etapes(conn):
    """`n_done`/`n_total` décrivent l'ÉTAPE, pas le job.

    Sans remise à zéro, le passage `anchors` → `predictions` afficherait un
    instant « 3 187 / 16 015 » : deux étapes mélangées dans une seule barre, un
    pourcentage qui recule, et une ETA absurde.
    """
    from store.dino_rebuild_jobs import (
        latest_rebuild, rebuild_progress, rebuild_start, rebuild_step,
    )

    job_id = rebuild_start(conn, anchors_kind=KIND, encoder_version=ENCODER)
    rebuild_progress(conn, job_id, n_done=3187, n_total=3187)
    assert latest_rebuild(conn)["n_done"] == 3187

    rebuild_step(conn, job_id, step="predictions")
    row = latest_rebuild(conn)
    assert row["n_done"] is None and row["n_total"] is None


def test_le_backfill_annonce_son_dernier_lot():
    """Le modulo rate la fin : sans report final, la barre se fige à 99 %.

    Une barre qui s'arrête juste avant la fin est exactement le signal qu'on
    voulait éviter — elle ressemble à un blocage au pire moment.

    Test STRUCTUREL, et assumé comme tel : exercer la vraie boucle demanderait
    torch, une banque d'ancres et des crops sur disque. On vérifie donc que le
    report périodique existe ET qu'un report final le suit — c'est le couple
    qui casse, pas l'un des deux.
    """
    src = (ML_DIR / "sources/_base/steps/auto_validate.py").read_text()

    assert "if i_asset % _PROGRESS_TOUS_LES == 0" in src, "report périodique absent"
    apres_boucle = src.split("if rows_to_write:", 1)[1]
    assert "_dire(i_asset)" in apres_boucle.split("def ", 1)[0], (
        "il manque le report FINAL après le dernier flush : la barre "
        "s'arrêterait au dernier multiple de _PROGRESS_TOUS_LES")


def test_le_callback_de_progression_ne_tue_jamais_le_backfill():
    """Quarante minutes de calcul valent mieux qu'une barre de progression."""
    src = (ML_DIR / "sources/_base/steps/auto_validate.py").read_text()
    bloc = src.split("def _dire(", 1)[1].split("\n\n", 1)[0]
    assert "except Exception" in bloc, (
        "une exception du report doit être avalée et journalisée, jamais propagée")


def test_un_compteur_irreductible_ne_pilote_pas_is_stale(conn):
    """`n_classes_would_gain_anchor` a un plancher — il ne doit pas rendre la
    carte rouge à vie.

    🔴 Mesuré après le premier rebuild complet, le 2026-08-24 : 8 classes
    restaient comptées, dont `fr-2017-…-rodin` avec 9 crops éligibles au SQL et
    zéro exemplaire.

    ⚠️ **La CAUSE alors retenue — `floor_sim = 0,45` — ne tient pas au
    remesurage** (réplique du 2026-08-24 23:52, build `53d22c38` à 20:41:15Z) :
    les 9 crops de rodin ont été tranchés entre 20:42:48 et 20:43:37, soit 93 s
    APRÈS ce build, et les 8 classes comptées sont toutes dans ce cas. Aucun
    build ne les avait vus : c'était de la fraîcheur, pas un plancher.

    Ce que ce test verrouille reste vrai et reste utile : ce compteur ne pilote
    pas `is_stale`. Depuis D15 il ne regarde que les crops POSTÉRIEURS au build,
    donc il peut retomber à zéro — le remettre dans `is_stale` redeviendrait
    défendable, c'est un arbitrage PO, pas un effet de bord de test.
    """
    _build(conn, "2026-08-22T18:06:22+00:00")
    # Une classe avec un crop éligible, mais aucune ancre : le cas irréductible.
    conn.execute("INSERT INTO coins (eurio_id, country, year, face_value, "
                 " is_commemorative) VALUES ('fr-2017-rodin','FR',2017,2.0,1)")
    _asset(conn, "A9", eurio_id="fr-2017-rodin", eligible=1)
    conn.execute("UPDATE image_assets SET face='obverse', "
                 " resolution_status='manual' WHERE id='A9'")
    _prediction(conn, "A9", "2026-08-22 18:14:50")
    conn.commit()

    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_classes_would_gain_anchor >= 1, "le nombre reste SERVI, il est réel"
    assert d.n_predictions_stale == 0 and d.n_assets_without_prediction == 0
    assert d.n_crops_validated_since == 0
    assert not d.is_stale, (
        "rien de ce qu'un rebuild sait faire n'est en retard : la carte doit "
        "dire « à jour », pas réclamer une heure de calcul sans effet")
