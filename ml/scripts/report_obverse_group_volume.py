"""Rapport volume eBay par classe d'entraînement (design_group avers).

LECTURE SEULE. Pour chaque classe ArcFace standard d'un pays
(``COALESCE(design_group_id, eurio_id)``), compte le volume d'images eBay et le
compare à la cible ~100/classe (cf. [[project_cohort_training_pipeline]]). Sert à
trancher honnêtement le critère de succès du pilote (KICKOFF §6) : « une image
attribuée » ne suffit pas — on veut un volume, et on DOCUMENTE le déficit.

Deux signaux (le 1er = activité du scrape, le 2nd = feed réel du training) :
- **attribués** : crops (``image_assets``) dont le listing a pour prior
  (``source_images.target_eurio_id``) un membre du groupe — proposés par le scrape,
  avant review.
- **training-eligible** : crops dont le coin RÉSOLU (``image_assets.eurio_id``,
  post-review) appartient au groupe ET ``training_eligible = 1`` — ce qui entraîne
  vraiment la classe.

Note : la base Numista augmentée (1 avers canonique/membre + augmentations) est une
source SÉPARÉE non comptée ici (cf. [[project_training_bench_split]]) ; ce rapport
mesure le *wild scrap* eBay, c'est lui qui starve.

Usage :
    python -m scripts.report_obverse_group_volume --country BE
    python -m scripts.report_obverse_group_volume --country BE --target 100 --fail-under
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]

from store import resolve_db_path  # noqa: E402

DEFAULT_DB = resolve_db_path(ML_DIR / "state" / "eurio.db")


def _open_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class ClassVolume:
    class_id: str
    members: list[str] = field(default_factory=list)
    year_min: int = 9999
    year_max: int = 0
    attributed: int = 0       # crops proposés (prior), HORS rejetés
    rejected: int = 0         # crops écartés (gate vision / review)
    train_eligible: int = 0   # crops résolus + entraînables

    @property
    def is_group(self) -> bool:
        return len(self.members) > 1


def collect(conn: sqlite3.Connection, country: str, face_value: float | None) -> list[ClassVolume]:
    # « attributed » exclut les rejetés (resolution_status='rejected') pour refléter
    # le pool propre post-gate ; « rejected » les compte à part (transparence).
    sql = (
        "SELECT c.eurio_id, c.year, "
        "       COALESCE(c.design_group_id, c.eurio_id) AS class_id, "
        "       (SELECT COUNT(*) FROM image_assets ia "
        "          JOIN source_images si ON si.id = ia.source_image_id "
        "         WHERE si.source = 'ebay' AND si.target_eurio_id = c.eurio_id "
        "           AND ia.resolution_status != 'rejected') AS attributed, "
        "       (SELECT COUNT(*) FROM image_assets iar "
        "          JOIN source_images sir ON sir.id = iar.source_image_id "
        "         WHERE sir.source = 'ebay' AND sir.target_eurio_id = c.eurio_id "
        "           AND iar.resolution_status = 'rejected') AS rejected, "
        "       (SELECT COUNT(*) FROM image_assets ia2 "
        "         WHERE ia2.eurio_id = c.eurio_id AND ia2.training_eligible = 1) AS train_eligible "
        "  FROM coins c "
        " WHERE c.country = ? AND c.is_commemorative = 0 AND c.canonical_eurio_id IS NULL"
    )
    params: list[object] = [country.upper()]
    if face_value is not None:
        sql += " AND c.face_value = ?"
        params.append(face_value)
    sql += " ORDER BY class_id, c.year, c.eurio_id"

    classes: dict[str, ClassVolume] = defaultdict(lambda: ClassVolume(class_id=""))
    for r in conn.execute(sql, params):
        cv = classes[r["class_id"]]
        cv.class_id = r["class_id"]
        cv.members.append(r["eurio_id"])
        cv.year_min = min(cv.year_min, int(r["year"]))
        cv.year_max = max(cv.year_max, int(r["year"]))
        cv.attributed += int(r["attributed"])
        cv.rejected += int(r["rejected"])
        cv.train_eligible += int(r["train_eligible"])
    return sorted(classes.values(), key=lambda c: (c.year_min, c.class_id))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", required=True, help="ISO2 (ex. BE)")
    parser.add_argument("--face-value", type=float, default=None, help="optionnel, ex. 2.0")
    parser.add_argument("--target", type=int, default=100, help="cible images/classe (défaut 100)")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument(
        "--fail-under", action="store_true",
        help="exit≠0 si une classe est sous la cible (gate CI ; défaut = rapport seul)",
    )
    args = parser.parse_args()

    conn = _open_ro(Path(args.db))
    try:
        classes = collect(conn, args.country, args.face_value)
    finally:
        conn.close()

    if not classes:
        print(f"Aucune classe standard pour {args.country.upper()}.")
        return 0

    print(
        f"Volume eBay par classe — {args.country.upper()} — cible {args.target}/classe\n\n"
        f"  {'classe':30} {'plage':>9} {'memb':>4} {'attrib':>7} {'rejet':>6} {'train':>6} {'gap':>6}"
    )
    n_under = 0
    tot_attr = tot_rej = tot_train = 0
    for cv in classes:
        rng = f"{cv.year_min}" if cv.year_min == cv.year_max else f"{cv.year_min}-{cv.year_max}"
        gap = max(0, args.target - cv.train_eligible)
        if gap > 0:
            n_under += 1
        tot_attr += cv.attributed
        tot_rej += cv.rejected
        tot_train += cv.train_eligible
        flag = "" if gap == 0 else (" ⚠" if cv.train_eligible else " ✗0")
        print(
            f"  {cv.class_id:30} {rng:>9} {len(cv.members):>4} "
            f"{cv.attributed:>7} {cv.rejected:>6} {cv.train_eligible:>6} {gap:>6}{flag}"
        )

    print(
        f"\n{len(classes)} classe(s) — {n_under} sous la cible. "
        f"Attribué (hors rejet)={tot_attr}, rejeté={tot_rej}, training-eligible={tot_train}."
    )
    if n_under:
        print(
            "→ Déficit documenté. Enrichir le wild scrap (cf. project_cohort_training_pipeline) ; "
            "rappel : base Numista augmentée non comptée ici."
        )
    if args.fail_under and n_under:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
