#!/usr/bin/env bash
# Multi-seed confirmation of the top-2 crop combos (m10-hard, m02-hard).
# Training is stochastic (no manual_seed), so repeated --force-from train runs
# sample the run-to-run variance. R@1 captured after each run (the slug-keyed
# summary.json is overwritten each time).
set -euo pipefail
cd "$(dirname "$0")/../.."   # -> ml/
PULL="../debug_pull/20260601_162127"
CSV="state/cohort_csvs/mix-zone-17.csv"
OUT="state/ablation_eval/_seed_confirm.tsv"
echo -e "slug\tseed\tr_at_1\tr_at_5" > "$OUT"

read_r() {  # $1=slug $2=seedlabel
  .venv/bin/python - "$1" "$2" "$OUT" <<'PY'
import json,sys
slug,seed,out=sys.argv[1],sys.argv[2],sys.argv[3]
d=json.load(open(f"state/ablation_eval/{slug}.summary.json"))
open(out,"a").write(f"{slug}\t{seed}\t{d['r_at_1']:.4f}\t{d['r_at_5']:.4f}\n")
print(f"  {slug} {seed}: R@1={100*d['r_at_1']:.2f}%")
PY
}

run() {  # $1=margin $2=edge $3=slug $4=seed
  echo ">>> $3 $4 (margin=$1 edge=$2)"
  env -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY -u SUPABASE_ANON_KEY -u SUPABASE_SERVICE_KEY \
  .venv/bin/python -m scripts.sweep_ablation \
      --device-pull "$PULL" --class-kind eurio_id --cohort-csv "$CSV" \
      --margin-frac "$1" --edge-mode "$2" --epochs 12 --force-from train \
      > "state/ablation_eval/_seedlog_$3_$4.log" 2>&1
  read_r "$3" "$4"
}

# seed1 = existing sweep artifacts (capture before they get overwritten)
read_r m10-hard-s224 seed1
read_r m02-hard-s224 seed1

# seed2, seed3 = fresh stochastic re-trains (dataset reused, train+embed+eval forced)
for s in seed2 seed3; do
  run 0.10 hard m10-hard-s224 "$s"
  run 0.02 hard m02-hard-s224 "$s"
done

echo "=== DONE ==="
cat "$OUT"
