"""Déplace les OCTETS des crops d'éval dans leur propre bucket — décision D9.

Chantier ``juge-et-banc``, étape 2, deuxième temps. ``select_eval_holdout`` a
posé le RÔLE (``image_assets.eval_corpus``) ; ce script fait suivre le
RANGEMENT : ``enrichment-crops/<clé>`` → ``eval-corpus/eval/<corpus>/<clé>``,
puis dit à la base où les octets sont maintenant.

Pourquoi les octets bougent, alors qu'on avait d'abord dit non
==============================================================

La première réponse était : « la clé S3 est immuable et sert de jointure
partout, c'est la LIGNE qui porte le rôle, déplacer les objets serait
décoratif ». Le PO a objecté, et il avait raison : un crop passé en évaluation
**n'est plus le même objet fonctionnellement** — il sort du pool
d'entraînement. Tant que le stockage l'ignore, la séparation ne tient que par
un ``WHERE``, et un prédicat oublié la fait fuir en silence.

L'incohérence était de notre côté : quelques heures plus tôt on avait mis le
corpus de jugement dans une base **isolée** (``scan_corpus.db``) exactement
pour cette raison — *l'entraînement ne la lit pas, donc il ne PEUT pas la
prendre, même par bug*. On l'avait appliqué à la base et refusé au stockage,
sans justifier la différence. Ce qui restait vrai dans la réponse initiale
relevait du **coût**, pas du principe : c'est un lot, pas une ligne. Le voici.

Deux marques, et il en faut deux (cf. ``shared/storage/__init__.py``) :

* le **bucket** ``eval-corpus`` — la garantie physique ;
* le **préfixe** ``eval/<corpus>/`` dans la clé — ce qui rend le bucket
  dérivable de la clé SEULE (``bucket_for_key``), sans faire descendre
  ``eval_corpus`` dans chaque requête qui alimente une vignette. Il ferme en
  plus le trou que le bucket seul laisserait ouvert : à clé inchangée, le
  cache local ``~/.cache/eurio/enrichment-crops/<clé>`` resterait un **HIT** et
  l'entraînement lirait le crop d'éval malgré le déplacement.

L'ordre des opérations n'est pas négociable
--------------------------------------------

Pour chaque crop : **copier → vérifier → écrire la base → supprimer la
source**, jamais autrement.

* supprimer avant d'écrire la base laisserait une ligne qui pointe un objet
  disparu — et ``local_path`` marquerait l'asset ``missing_in_storage``, ce
  qui ressemble à une perte de données ;
* une interruption entre l'écriture et la suppression laisse un **orphelin**
  dans ``enrichment-crops`` : sans référence, détecté par
  ``scripts/cascade_sync.py audit``, et rattrapé par une simple relance de ce
  script — c'est le seul état intermédiaire acceptable, et il est réparable.

Le script est **idempotent** : un crop dont la clé est déjà préfixée est
compté ``deja_range`` et n'est pas retouché.

Usage ::

    python -m scripts.move_eval_corpus_objects                 # dry-run (défaut)
    python -m scripts.move_eval_corpus_objects --apply
    python -m scripts.move_eval_corpus_objects --apply --keep-source
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parent.parent
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from shared.storage import (  # noqa: E402
    eval_storage_key,
    is_eval_key,
)
from store import resolve_db_path  # noqa: E402

SOURCE_BUCKET = "enrichment-crops"
EVAL_BUCKET = "eval-corpus"

_A_DEPLACER_SQL = """
    SELECT a.id           AS asset_id,
           a.eval_corpus  AS corpus,
           a.storage_path AS storage_path
      FROM image_assets a
     WHERE a.eval_corpus IS NOT NULL
       AND a.storage_path IS NOT NULL
       AND a.storage_path != ''
     ORDER BY a.id
"""


def _open_ro(db: Path) -> sqlite3.Connection:
    """``mode=ro`` et non ``immutable=1`` : la réplique est en WAL et un
    écrivain peut tourner — ``immutable=1`` rendrait un instantané périmé, en
    silence (cf. skill ``eurio-verify``, fiche WAL)."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def plan_deplacement(conn: sqlite3.Connection) -> dict:
    """Rend ``{"a_deplacer": [...], "deja_range": n}``, sans rien écrire."""
    a_deplacer: list[dict] = []
    deja = 0
    for r in conn.execute(_A_DEPLACER_SQL):
        if is_eval_key(r["storage_path"]):
            deja += 1
            continue
        a_deplacer.append({
            "asset_id": r["asset_id"],
            "corpus": r["corpus"],
            "src_key": r["storage_path"],
            "dst_key": eval_storage_key(r["storage_path"], r["corpus"]),
        })
    return {"a_deplacer": a_deplacer, "deja_range": deja}


def assurer_bucket(client, bucket: str) -> bool:
    """Crée le bucket s'il manque. Rend True s'il a été créé.

    Aucune policy publique : ``eval-corpus`` est privé comme
    ``enrichment-crops`` — il se lit par URL présignée, jamais anonymement.
    """
    from botocore.exceptions import ClientError

    try:
        client.head_bucket(Bucket=bucket)
        return False
    except ClientError:
        client.create_bucket(Bucket=bucket)
        return True


class TeteRefusee(Exception):
    """L'objet n'a pas pu être INTERROGÉ — ce n'est pas « il n'est pas là ».

    Vécu le 2026-08-26 : pendant la fenêtre où la policy MinIO était remplacée,
    les 300 `head_object` ont pris un 403 et le script a annoncé « source
    absente de MinIO ». Un message faux est pire qu'une erreur : il désigne un
    coupable (les octets ont disparu) au lieu du vrai (la clé n'a plus le
    droit). On sépare donc les deux, et un refus ARRÊTE la passe au lieu de la
    laisser conclure 300 fois de suite.
    """


def _tete(client, bucket: str, key: str) -> dict | None:
    """``head_object`` : ``None`` si l'objet n'existe pas (404).

    Toute AUTRE erreur lève ``TeteRefusee`` — un 403, une coupure réseau ou un
    5xx ne disent pas que l'objet est absent, ils disent qu'on ne sait pas.
    """
    try:
        h = client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "response", {}).get(
            "ResponseMetadata", {}).get("HTTPStatusCode")
        if code in (404,):
            return None
        raise TeteRefusee(f"{bucket}/{key} : {exc}") from exc
    return {"size": h.get("ContentLength"), "etag": (h.get("ETag") or "").strip('"')}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path,
                    default=resolve_db_path(_ML_DIR / "state" / "eurio.replica.db"))
    ap.add_argument("--apply", action="store_true",
                    help="copie, écrit la base et supprime la source "
                         "(défaut = dry-run)")
    ap.add_argument("--keep-source", action="store_true",
                    help="ne supprime PAS l'objet source après copie. La "
                         "séparation n'est alors PAS physique — les octets "
                         "restent lisibles depuis `enrichment-crops`. À "
                         "n'utiliser que pour une répétition.")
    ap.add_argument("--batch", type=int, default=100)
    args = ap.parse_args(argv)

    conn = _open_ro(args.db)
    plan = plan_deplacement(conn)
    conn.close()

    items = plan["a_deplacer"]
    print(f"DB (lecture seule) : {args.db}")
    print(f"déjà rangés        : {plan['deja_range']}")
    print(f"à déplacer         : {len(items)}")
    corpus = sorted({i["corpus"] for i in items})
    if corpus:
        print(f"corpus concernés   : {', '.join(corpus)}")
        ex = items[0]
        print(f"exemple            : {SOURCE_BUCKET}/{ex['src_key']}")
        print(f"                  → {EVAL_BUCKET}/{ex['dst_key']}")

    if not args.apply:
        print("\nDRY-RUN — rien copié, rien écrit, rien supprimé. "
              "Relancer avec --apply.")
        print(json.dumps({"copies": 0, "ecrits": 0, "supprimes": 0,
                          "deja_range": plan["deja_range"],
                          "a_deplacer": len(items), "dry_run": True}))
        return 0

    if not items:
        print("\nRien à faire.")
        print(json.dumps({"copies": 0, "ecrits": 0, "supprimes": 0,
                          "deja_range": plan["deja_range"], "echecs": 0}))
        return 0

    from client.http import sync_enabled

    if not sync_enabled():
        print("EURIO_API_URL absent : impossible d'écrire la nouvelle clé au "
              "canonique. Charge le devShell.", file=sys.stderr)
        return 2

    from client.ingest import push_eval_corpus
    from shared.storage import _client
    from shared.storage.local_cache import cache_path_for

    client = _client()
    if assurer_bucket(client, EVAL_BUCKET):
        print(f"bucket créé        : {EVAL_BUCKET} (privé)")

    copies = 0
    echecs: list[dict] = []
    prets: list[dict] = []

    # ── 1. copier + vérifier ────────────────────────────────────────────────
    #
    # Un refus d'interrogation (403, réseau, 5xx) arrête TOUT : il ne dit rien
    # sur les octets, et le voir 300 fois d'affilée ne le rend pas plus vrai.
    for it in items:
        try:
            src_t = _tete(client, SOURCE_BUCKET, it["src_key"])
        except TeteRefusee as exc:
            print(f"\n⛔ MinIO refuse de répondre — passe ARRÊTÉE après "
                  f"{copies} copie(s).\n   {exc}\n   Rien n'a été supprimé. "
                  f"Vérifie la policy de la clé, puis relance : le script est "
                  f"idempotent.", file=sys.stderr)
            return 2
        if src_t is None:
            # L'objet n'est pas dans la source. Est-il déjà à destination ?
            # (relance après interruption entre la copie et l'écriture)
            try:
                deja_la = _tete(client, EVAL_BUCKET, it["dst_key"]) is not None
            except TeteRefusee as exc:
                print(f"\n⛔ MinIO refuse de répondre sur {EVAL_BUCKET} — "
                      f"passe ARRÊTÉE.\n   {exc}", file=sys.stderr)
                return 2
            if deja_la:
                prets.append(it)
                continue
            echecs.append({**it, "motif": "source absente de MinIO (404)"})
            continue
        try:
            client.copy_object(
                Bucket=EVAL_BUCKET, Key=it["dst_key"],
                CopySource={"Bucket": SOURCE_BUCKET, "Key": it["src_key"]},
            )
        except Exception as exc:  # noqa: BLE001
            echecs.append({**it, "motif": f"copie refusée : {exc}"})
            continue
        try:
            dst_t = _tete(client, EVAL_BUCKET, it["dst_key"])
        except TeteRefusee as exc:
            print(f"\n⛔ vérification impossible — passe ARRÊTÉE.\n   {exc}",
                  file=sys.stderr)
            return 2
        # On vérifie AVANT de toucher la base : une copie tronquée qu'on
        # déclarerait bonne ferait perdre l'original à l'étape 3.
        if dst_t is None or dst_t["size"] != src_t["size"]:
            echecs.append({**it, "motif": f"copie non vérifiée "
                                          f"(src={src_t}, dst={dst_t})"})
            continue
        copies += 1
        prets.append(it)
        if copies % 50 == 0:
            print(f"  … copiés {copies}/{len(items)}", flush=True)

    print(f"copiés + vérifiés  : {copies} (déjà à destination : "
          f"{len(prets) - copies})")

    # ── 2. écrire la nouvelle clé au canonique ──────────────────────────────
    totaux = {"updated": 0, "skipped": 0}
    conflits: list[str] = []
    manquants: list[str] = []
    rows = [{"asset_id": it["asset_id"], "eval_corpus": it["corpus"],
             "storage_path": it["dst_key"]} for it in prets]
    for i in range(0, len(rows), args.batch):
        lot = rows[i:i + args.batch]
        res = push_eval_corpus(lot) or {}
        totaux["updated"] += int(res.get("updated") or 0)
        totaux["skipped"] += int(res.get("skipped") or 0)
        conflits.extend(res.get("conflict") or [])
        manquants.extend(res.get("missing") or [])
        print(f"  … clé écrite {res.get('updated')}/{len(lot)}", flush=True)

    refuses = set(conflits) | set(manquants)
    if refuses:
        print(f"⚠️  lignes REFUSÉES par le canonique : {len(refuses)} — leur "
              f"objet source est CONSERVÉ (la base pointe encore dessus)")

    # ── 3. supprimer la source, seulement pour les lignes écrites ───────────
    supprimes = 0
    if args.keep_source:
        print("--keep-source : sources conservées. ⚠️  La séparation N'EST PAS "
              "physique tant qu'elles sont là.")
    else:
        for it in prets:
            if it["asset_id"] in refuses:
                continue
            try:
                client.delete_object(Bucket=SOURCE_BUCKET, Key=it["src_key"])
                supprimes += 1
            except Exception as exc:  # noqa: BLE001
                echecs.append({**it, "motif": f"suppression source : {exc}"})
            # Le cache local de l'ANCIENNE clé devient un orphelin. Il ne peut
            # plus être servi (la base ne cite plus cette clé), mais il occupe
            # de la place et brouillerait un diagnostic — on le retire.
            try:
                orphelin = cache_path_for(SOURCE_BUCKET, it["src_key"])
                orphelin.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001 — cache absent : rien à faire
                pass

    print("\ndestination : "
          f"MinIO ({EVAL_BUCKET}) + canonique (POST /ingest/eval-corpus)")
    if echecs:
        print(f"⚠️  ÉCHECS : {len(echecs)}")
        for e in echecs[:5]:
            print(f"    {e['asset_id']} — {e['motif']}")
    print(json.dumps({
        "copies": copies, "ecrits": totaux["updated"],
        "inchanges": totaux["skipped"], "supprimes": supprimes,
        "deja_range": plan["deja_range"], "conflict": len(conflits),
        "missing": len(manquants), "echecs": len(echecs),
    }))
    return 1 if echecs else 0


if __name__ == "__main__":
    raise SystemExit(main())
