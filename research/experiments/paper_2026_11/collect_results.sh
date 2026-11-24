#!/usr/bin/env bash
# Copy run records, analyses, stats, macros and figures from the Linux work dir
# into Research_Paper/ (no images, no recovered files).
set -euo pipefail
WORK=${1:-/root/rxr}; RP=${2:?Research_Paper path}
for E in e1 e2 e3_256 e3_1024; do
  mkdir -p "$RP/results/$E"
  cp "$WORK/$E"/*.json "$WORK/$E"/*.jsonl "$RP/results/$E"/ 2>/dev/null || true
  cp "$WORK/$E"/*.csv "$RP/results/$E"/ 2>/dev/null || true
  [ -d "$WORK/$E/models" ] && cp -r "$WORK/$E/models" "$RP/results/$E/"
done
mkdir -p "$RP/results/e0_original"; cp "$WORK/e0"/* "$RP/results/e0_original/" 2>/dev/null || true
for D in d1 d2 d3_256 d3_1024; do
  mkdir -p "$RP/results/datasets/$D"; cp "$WORK/$D/manifest.json" "$WORK/$D/validation.json" "$RP/results/datasets/$D/"
done
cp "$WORK/stats.json" "$WORK/macros.tex" "$RP/results/"
cp "$WORK/out/environment.json" "$RP/results/"
cp "$WORK/figs/"*.pdf "$WORK/figs/tree.tex" "$RP/figures/"
(cd "$WORK/code" && find src config -type f | sort | xargs sha256sum > "$RP/results/source_sha256.txt" \
  && echo "tree-digest $(find src config -type f | sort | xargs sha256sum | sha256sum | cut -d' ' -f1)" >> "$RP/results/source_sha256.txt")
echo collected
