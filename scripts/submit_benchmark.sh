#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 3 ]]; then
    echo 'Usage: scripts/submit_benchmark.sh TASK MODEL SEED' >&2
    exit 2
fi
task="$1"
model="$2"
seed="$3"
if [[ ! "$task" =~ ^[A-Za-z0-9_]+$ || ! "$model" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ || ! "$seed" =~ ^[0-9]+$ ]]; then
    echo 'Invalid task, model key or seed' >&2
    exit 2
fi
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
artifact_root="${PROTENIX_ARTIFACTS_DIR:-$(dirname "$repo_root")/protenix-artifacts}"
run_root="${PROTENIX_RUN_DIR:-${artifact_root}/runs/kras-5-seeds}"
case "$artifact_root:$run_root" in
    /*:/*) ;;
    *) echo 'Artifact and run directories must be absolute' >&2; exit 2 ;;
esac
output_dir="${run_root}/output/${task}-${model}-seed${seed}"
if [[ -e "$output_dir" ]]; then
    echo "Output already exists: $output_dir" >&2
    exit 1
fi
mkdir -p "${run_root}/output" "${run_root}/logs"
cd "$repo_root"
export PROTENIX_ARTIFACTS_DIR="$artifact_root" PROTENIX_RUN_DIR="$run_root"
sbatch --output="${run_root}/logs/benchmark-%j.out" \
    scripts/benchmark.sbatch "$task" "$model" "$output_dir" "$seed"
