"""Le tirage du jeu d'or tire-t-il ce que `JEU-D-OR.md` dit qu'il tire ?

La requête est le cœur de L2 : elle décide de ce que le PO va annoter, donc de
ce que le juge sera capable de mesurer. Trois pièges y sont désarmés, et chacun
a déjà coûté une mesure fausse dans ce chantier — ils sont testés un par un.

⚠️ `source_images.is_lot_suspected` n'existe **pas** dans `state/schema.sql` :
elle n'est posée que par le `_ensure_column` de `store/connection.py:440`. Une
base montée au seul schéma ne la porte pas. Le test la pose donc explicitement,
comme le fait `Store` à l'ouverture.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from bench.gold_crop.sample import (
    N_ACCEPT,
    N_ACCEPT_RESERVE,
    N_REJECT,
    N_REJECT_RESERVE,
    hint_depuis_bbox,
    tirer,
)
from tests._schema_reel import base_au_schema_reel

BBOX = json.dumps({"x": 10.0, "y": 20.0, "w": 100.0, "h": 100.0})


def _uuid(graine: str) -> str:
    """32 hex, comme les vrais `image_assets.id` — la longueur COMPTE ici."""
    return hashlib.md5(graine.encode()).hexdigest()


def _sha(graine: str) -> str:
    """64 hex, comme les vrais `source_images.sha256`."""
    return hashlib.sha256(graine.encode()).hexdigest()


def _base(tmp_path):
    chemin = tmp_path / "corpus.db"
    conn = base_au_schema_reel(chemin)
    conn.execute("ALTER TABLE source_images ADD COLUMN is_lot_suspected "
                 "INTEGER NOT NULL DEFAULT 0")
    return conn, chemin


def _image(conn, sid, *, sha="a" * 60, titre="2 euro commemorative",
           n_crops=1, lot_suspect=0, statut="present", chemin="ebay/x.jpg",
           kind="single", markers="[]"):
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, listing_title, storage_path,"
        " width, height, sha256, n_crops_detected, storage_status, is_lot_suspected)"
        " VALUES (?,'ebay',?,?,?,900,900,?,?,?,?)",
        (sid, sid, titre, chemin, sha, n_crops, statut, lot_suspect))
    conn.execute(
        "INSERT INTO listing_text_signals (source_image_id, coverage, listing_kind,"
        " rejected_markers_json, is_lot) VALUES (?,'rich',?,?,0)",
        (sid, kind, markers))


def _asset(conn, aid, sid, *, statut="manual", motif=None, axis=0.99,
           tilt=8.0, fiable=0, bbox=BBOX, crop_index=0):
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, bbox_json,"
        " resolution_status, quality_reason, tilt_deg, axis_ratio, tilt_trustworthy,"
        " storage_path) VALUES (?,?,?,?,?,?,?,?,?,'crops/x.jpg')",
        (aid, sid, crop_index, bbox, statut, motif, tilt, axis, fiable))


def _corpus_s1(conn, n_accept, n_reject):
    """`n` acceptés et `n` rejetés, tous en S1 (1 crop, single, axis_ratio ≥ 0,97)."""
    for i in range(n_accept + n_reject):
        # longueurs RÉELLES : 64 hex pour le sha256, 32 pour l'id d'asset. Un
        # corpus aux identifiants courts ferait mentir la clé de tirage — voir
        # `test_la_cle_de_tirage_ne_doit_rien_au_sha256_du_raw`.
        sid = f"si{i:03d}"
        _image(conn, sid, sha=_sha(sid))
        _asset(conn, _uuid(sid), sid,
               statut="manual" if i < n_accept else "rejected",
               motif=None if i < n_accept else "rejected_in_review")


# ─── le hint ────────────────────────────────────────────────────────────────

def test_le_hint_est_le_cercle_inscrit_dans_la_bbox():
    h = hint_depuis_bbox(BBOX)
    assert h == {"cx": 60.0, "cy": 70.0, "r": 50.0}


@pytest.mark.parametrize("bbox", ["", "pas du json", "{}", '{"x":0,"y":0,"w":0,"h":10}'])
def test_une_bbox_inutilisable_ne_produit_pas_de_hint(bbox):
    assert hint_depuis_bbox(bbox) is None


# ─── les trois pièges de la requête ─────────────────────────────────────────

def test_un_rejet_de_face_ou_de_denomination_ne_dit_rien_du_cadrage(tmp_path):
    """4 678 des 6 299 rejets portent ces deux motifs. Les inclure apprendrait
    à détecter des revers, pas à cadrer."""
    conn, chemin = _base(tmp_path)
    for i, motif in enumerate(("rejected_in_review", "face_reverse", "not_2eur",
                               "consensus_reject")):
        _image(conn, f"si{i}", sha=f"{i:060d}")
        _asset(conn, f"ia{i}", f"si{i}", statut="rejected", motif=motif)
    conn.commit()
    motifs = {r["quality_reason"] for r in tirer(chemin)}
    assert motifs == {"rejected_in_review", "consensus_reject"}


def test_un_accepte_garde_son_motif_quel_qu_il_soit(tmp_path):
    """Le filtre ne porte QUE sur les rejets : un `manual` reste, motif ou pas.

    Sans la garde `resolution_status = 'manual' OR …`, le prédicat amputerait
    aussi le vivier accepté — et le 8/7 de RE-4 deviendrait infaisable.
    """
    conn, chemin = _base(tmp_path)
    _image(conn, "si0", sha="0" * 60)
    _asset(conn, "ia0", "si0", statut="manual", motif="face_reverse")
    conn.commit()
    assert [r["asset_id"] for r in tirer(chemin)] == ["ia0"]


def test_la_strate_de_face_suit_axis_ratio_et_jamais_tilt_deg(tmp_path):
    """`tilt_deg` est tronqué à 14,07° par construction (`_TILT_TRIVIAL = 0,97`) :
    y chercher « de face » est une contradiction logique."""
    conn, chemin = _base(tmp_path)
    _image(conn, "sa", sha="a" * 60)
    _asset(conn, "de_face", "sa", axis=0.99, tilt=8.0)       # quasi-cercle
    _image(conn, "sb", sha="b" * 60)
    _asset(conn, "oblique", "sb", axis=0.90, tilt=25.8)      # nettement de biais
    # les deux cas où les colonnes DIVERGENT — c'est là que le choix se joue :
    _image(conn, "sc", sha="c" * 60)
    _asset(conn, "sans_tilt", "sc", axis=0.99, tilt=None)    # tilt jamais mesuré
    _image(conn, "sd", sha="d" * 60)
    _asset(conn, "tilt_menteur", "sd", axis=0.80, tilt=3.0)  # tilt bas, pièce de biais
    conn.commit()
    par_id = {r["asset_id"]: r["strate"] for r in tirer(chemin)}
    assert par_id["de_face"] == "S1_facile"
    # un tilt absent n'empêche pas de reconnaître une pièce de face
    assert par_id["sans_tilt"] == "S1_facile"
    # `axis_ratio` < 0,97 et `tilt_trustworthy` = 0 → hors strate, donc absentes
    assert "oblique" not in par_id
    assert "tilt_menteur" not in par_id


def test_un_coffret_va_en_multi_meme_avec_un_seul_crop(tmp_path):
    """La strate « facile » exige `listing_kind = 'single'` : un coffret n'est
    pas un fond uniforme, même quand la détection n'a trouvé qu'une pièce."""
    conn, chemin = _base(tmp_path)
    _image(conn, "sa", sha=_sha("sa"), kind="single")
    _asset(conn, _uuid("sa"), "sa")
    _image(conn, "sb", sha=_sha("sb"), kind="coffret")
    _asset(conn, _uuid("sb"), "sb")
    # un slab gradé n'est attrapé par AUCUNE autre branche : c'est le seul cas
    # où `listing_kind = 'single'` de S1 décide seul, donc le seul qui le teste.
    _image(conn, "sc", sha=_sha("sc"), kind="graded_slab")
    _asset(conn, _uuid("sc"), "sc")
    conn.commit()
    par_id = {r["asset_id"]: r["strate"] for r in tirer(chemin)}
    assert set(par_id.values()) == {"S1_facile", "S3_multi"}
    assert _uuid("sc") not in par_id


def test_un_marqueur_de_conditionnement_fait_la_strate_capsule(tmp_path):
    """⚠️ Le mot « capsule » n'existe pas dans le parc (3 occurrences). C'est le
    CONDITIONNEMENT qui définit S2 — proof, blister, PCGS/NGC, belle épreuve."""
    conn, chemin = _base(tmp_path)
    _image(conn, "sa", sha=_sha("sa"), titre="2 euros BE proof coffret BU")
    _asset(conn, _uuid("sa"), "sa")
    conn.commit()
    assert [r["strate"] for r in tirer(chemin)] == ["S2_capsule"]


def test_un_tilt_non_fiable_ne_peuple_pas_la_strate_oblique(tmp_path):
    conn, chemin = _base(tmp_path)
    _image(conn, "sa", sha="a" * 60)
    _asset(conn, "faux_oblique", "sa", axis=0.5, tilt=60.0, fiable=0)
    _image(conn, "sb", sha="b" * 60)
    _asset(conn, "vrai_oblique", "sb", axis=0.5, tilt=60.0, fiable=1)
    conn.commit()
    par_id = {r["asset_id"]: r["strate"] for r in tirer(chemin)}
    assert par_id == {"vrai_oblique": "S4_oblique"}


@pytest.mark.parametrize("champ,valeur", [
    ("sha256", None),                       # la clé de tirage en dépend
    ("storage_status", "missing_in_storage"),
    ("storage_path", None),
])
def test_une_image_sans_raw_lisible_est_exclue(tmp_path, champ, valeur):
    conn, chemin = _base(tmp_path)
    _image(conn, "si0", sha="0" * 60)
    _asset(conn, "ia0", "si0")
    conn.execute(f"UPDATE source_images SET {champ} = ?", (valeur,))
    conn.commit()
    assert tirer(chemin) == []


def test_une_bbox_absente_est_exclue(tmp_path):
    conn, chemin = _base(tmp_path)
    _image(conn, "si0", sha="0" * 60)
    _asset(conn, "ia0", "si0", bbox=None)
    conn.commit()
    assert tirer(chemin) == []


# ─── le tirage lui-même ─────────────────────────────────────────────────────

def test_le_tirage_rend_huit_acceptes_et_sept_rejetes_par_strate(tmp_path):
    """Le 8/7 n'est pas cosmétique : c'est ce qui rend RE-4 exécutable."""
    conn, chemin = _base(tmp_path)
    _corpus_s1(conn, 20, 20)
    conn.commit()
    tirage = [r for r in tirer(chemin) if r["role"] == "tirage"]
    # les littéraux, PAS les constantes : un test qui relit la constante qu'il
    # vérifie suit sa mutation en silence.
    assert sum(1 for r in tirage if r["verdict"] == "accept") == 8
    assert sum(1 for r in tirage if r["verdict"] == "reject") == 7
    assert (N_ACCEPT, N_REJECT) == (8, 7)


def test_la_reserve_prolonge_le_tirage_sans_le_retirer(tmp_path):
    """Remplacer un cas « indécidable » ne doit pas rejouer le tirage."""
    conn, chemin = _base(tmp_path)
    _corpus_s1(conn, 20, 20)
    conn.commit()
    rows = tirer(chemin, avec_reserve=True)
    tirage = [r for r in rows if r["role"] == "tirage"]
    reserve = [r for r in rows if r["role"] == "reserve"]
    assert len(reserve) == (N_ACCEPT_RESERVE - N_ACCEPT) + (N_REJECT_RESERVE - N_REJECT)
    # le tirage est identique, avec ou sans réserve : la réserve s'AJOUTE
    sans = tirer(chemin, avec_reserve=False)
    assert [r["asset_id"] for r in sans] == [r["asset_id"] for r in tirage]
    # et la réserve vient bien APRÈS, dans le même ordre de clé
    assert all(r["rn"] > N_ACCEPT for r in reserve if r["verdict"] == "accept")


def test_le_tirage_est_reproductible_et_suit_la_cle_de_hachage(tmp_path):
    """Pas de `random()` : la clé est `substr(sha256 || id, -8)`. Rejouer le
    script sur la même réplique doit rendre le même tirage, à l'octet."""
    conn, chemin = _base(tmp_path)
    _corpus_s1(conn, 20, 20)
    conn.commit()
    a = [r["asset_id"] for r in tirer(chemin)]
    b = [r["asset_id"] for r in tirer(chemin)]
    assert a == b

    con = sqlite3.connect(chemin)
    attendu = [r[0] for r in con.execute(
        "SELECT ia.id FROM image_assets ia JOIN source_images si ON si.id = ia.source_image_id"
        " WHERE ia.resolution_status = 'manual'"
        " ORDER BY substr(si.sha256 || ia.id, -8), ia.id LIMIT 8")]
    con.close()
    obtenu = [r["asset_id"] for r in tirer(chemin)
              if r["verdict"] == "accept" and r["role"] == "tirage"]
    assert obtenu == attendu


def test_la_cle_desambigue_les_crops_freres_d_un_meme_raw(tmp_path):
    """La clé est `sha256 || ia.id`, pas `sha256` seul.

    Un raw multi-pièces porte N assets qui partagent son `sha256`. Avec le seul
    hachage du raw, les frères ont une clé IDENTIQUE : le tri les rend
    strictement adjacents, et le tirage part en paquets de frères — 15 lignes
    tirées deviennent 7 ou 8 annonces. La concaténation avec l'`id` de l'asset
    les redistribue.
    """
    conn, chemin = _base(tmp_path)
    for i in range(12):
        sid = f"si{i:03d}"
        _image(conn, sid, sha=_sha(sid), n_crops=2)
        for j in range(2):
            _asset(conn, _uuid(f"{sid}/{j}"), sid, statut="manual", crop_index=j)
    conn.commit()
    tires = [r["source_image_id"] for r in tirer(chemin)
             if r["role"] == "tirage" and r["verdict"] == "accept"]
    assert len(tires) == 8
    adjacents = sum(1 for a, b in zip(tires, tires[1:]) if a == b)
    # avec `sha256` seul, les frères ont la MÊME clé et sortent collés deux à deux
    assert adjacents <= 1, tires


def test_la_cle_de_tirage_ne_doit_rien_au_sha256_du_raw(tmp_path):
    """⚠️ En production, `substr(si.sha256 || ia.id, -8)` **est** `substr(ia.id, -8)`.

    Mesuré : `image_assets.id` fait 32 caractères sur les 20 375 lignes, donc
    les 8 derniers caractères de la concaténation tombent **entièrement** dans
    l'id. Le `sha256` du raw n'entre pas dans la clé — contrairement à ce que
    `JEU-D-OR.md` laissait entendre avant le 2026-08-28.

    Ce n'est pas un défaut : l'id est un uuid4, donc le tirage reste uniforme et
    reproductible. Mais quiconque raisonnera sur cette clé doit savoir laquelle
    des deux colonnes la porte. Le test fige le fait, pour qu'un id plus court
    un jour ne change pas le tirage en silence.
    """
    conn, chemin = _base(tmp_path)
    _corpus_s1(conn, 20, 20)
    conn.commit()
    con = sqlite3.connect(chemin)
    longueurs = {r[0] for r in con.execute("SELECT length(id) FROM image_assets")}
    par_id = [r[0] for r in con.execute(
        "SELECT id FROM image_assets WHERE resolution_status='manual'"
        " ORDER BY substr(id, -8), id LIMIT 8")]
    con.close()
    assert longueurs == {32}
    obtenu = [r["asset_id"] for r in tirer(chemin)
              if r["verdict"] == "accept" and r["role"] == "tirage"]
    assert obtenu == par_id
