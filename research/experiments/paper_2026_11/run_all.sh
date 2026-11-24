#!/usr/bin/env bash
# Reproduce experiments E1-E3 of the RecoverX paper (Linux, root: ext4 images
# are built through a loop mount). All images are synthetic and disposable.
#
#   CODE   path to a RecoverX checkout containing src/ and config/
#   WORK   scratch directory on a native Linux filesystem (images + cases)
#   OUT    where run records are copied (Research_Paper/results)
set -euo pipefail
CODE=${CODE:?set CODE}; WORK=${WORK:-/root/rxr}; OUT=${OUT:?set OUT}
HERE=$(cd "$(dirname "$0")" && pwd)
export RECOVERX_HOME=$WORK/home PYTHONHASHSEED=0
mkdir -p "$WORK" "$OUT"
py() { python3 -B "$@"; }

py "$HERE/rx_bench.py" env --code "$CODE" --out "$OUT/environment.json"

# E1: replication of the pre-registered protocol (seeds 0-7: train 0-4, val 5, test 6-7)
[ -f "$WORK/d1/manifest.json" ] || py "$HERE/rx_bench.py" gen --code "$CODE" --out "$WORK/d1" --seeds 0-7
py "$HERE/rx_bench.py" run --code "$CODE" --dataset "$WORK/d1" --exp "$WORK/e1" --phase phase1
py "$HERE/rx_train.py" train --code "$CODE" --dataset "$WORK/d1" --exp "$WORK/e1"
MODEL=$(python3 -c "import json;print(json.load(open('$WORK/e1/training_report.json'))['model_dir'])")
py "$HERE/rx_bench.py" run --code "$CODE" --dataset "$WORK/d1" --exp "$WORK/e1" --phase phase3 \
   --splits test --methods tsk,photorec,combined,rule,cart --model "$MODEL"
py "$HERE/rx_train.py" analyze --code "$CODE" --dataset "$WORK/d1" --exp "$WORK/e1"

# E2: fresh evaluation-only seeds 8-23 (192 images) with the frozen E1 model
[ -f "$WORK/d2/manifest.json" ] || py "$HERE/rx_bench.py" gen --code "$CODE" --out "$WORK/d2" --seeds 8-23 --split-label test
py "$HERE/rx_bench.py" run --code "$CODE" --dataset "$WORK/d2" --exp "$WORK/e2" --phase phase1 --splits test
py "$HERE/rx_train.py" labels --code "$CODE" --dataset "$WORK/d2" --exp "$WORK/e2"
py "$HERE/rx_bench.py" run --code "$CODE" --dataset "$WORK/d2" --exp "$WORK/e2" --phase phase3 \
   --splits test --methods tsk,photorec,combined,rule,cart --model "$MODEL"
py "$HERE/rx_train.py" analyze --code "$CODE" --dataset "$WORK/d2" --exp "$WORK/e2"

# E3: scaling (one seed, all fs x scenarios, 256 MiB and 1024 MiB images)
for SZ in 256 1024; do
  [ -f "$WORK/d3_$SZ/manifest.json" ] || py "$HERE/rx_bench.py" gen --code "$CODE" --out "$WORK/d3_$SZ" --seeds 100 --sizes $SZ --split-label test
  py "$HERE/rx_bench.py" run --code "$CODE" --dataset "$WORK/d3_$SZ" --exp "$WORK/e3_$SZ" --phase phase1 --splits test
  py "$HERE/rx_train.py" labels --code "$CODE" --dataset "$WORK/d3_$SZ" --exp "$WORK/e3_$SZ"
  py "$HERE/rx_bench.py" run --code "$CODE" --dataset "$WORK/d3_$SZ" --exp "$WORK/e3_$SZ" --phase phase3 \
     --splits test --methods tsk,photorec,combined,rule,cart --model "$MODEL"
done

# copy records (no images, no recovered files)
for E in e1 e2 e3_256 e3_1024; do
  mkdir -p "$OUT/$E"
  cp "$WORK/$E"/*.json* "$OUT/$E"/ 2>/dev/null || true
  cp "$WORK/$E"/*.csv "$OUT/$E"/ 2>/dev/null || true
  [ -d "$WORK/$E/models" ] && cp -r "$WORK/$E/models" "$OUT/$E/"
done
for D in d1 d2 d3_256 d3_1024; do
  mkdir -p "$OUT/datasets/$D"; cp "$WORK/$D/manifest.json" "$WORK/$D/validation.json" "$OUT/datasets/$D/"
done
echo done
