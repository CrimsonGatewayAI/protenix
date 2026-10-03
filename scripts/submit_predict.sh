#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 ]]; then
    echo 'Usage: scripts/submit_predict.sh INPUT_JSON [OUTPUT_DIR] [MODEL_NAME]' >&2
    exit 2
fi
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
artifact_root="${PROTENIX_ARTIFACTS_DIR:-$(dirname "$repo_root")/protenix-artifacts}"
run_root="${PROTENIX_RUN_DIR:-${artifact_root}/runs/kras-5-seeds}"
case "$artifact_root:$run_root" in
    /*:/*) ;;
    *) echo 'Artifact and run directories must be absolute' >&2; exit 2 ;;
esac
mkdir -p "${run_root}/output" "${run_root}/logs"
cd "$repo_root"
export PROTENIX_ARTIFACTS_DIR="$artifact_root" PROTENIX_RUN_DIR="$run_root"
sbatch --output="${run_root}/logs/predict-%j.out" scripts/predict.sbatch "$@"
