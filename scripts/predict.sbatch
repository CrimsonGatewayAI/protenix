#!/usr/bin/env bash
#SBATCH --job-name=protenix-predict
#SBATCH --partition=gpu
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=56G
#SBATCH --time=08:00:00
#SBATCH --output=logs/predict-%j.out

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
export PATH="${HOME}/.pixi/bin:${PATH}"
export PROTENIX_ARTIFACTS_DIR="${PROTENIX_ARTIFACTS_DIR:-$(dirname "${SLURM_SUBMIT_DIR}")/protenix-artifacts}"
export PROTENIX_RUN_DIR="${PROTENIX_RUN_DIR:-${PROTENIX_ARTIFACTS_DIR}/runs/kras-5-seeds}"
export PROTENIX_ROOT_DIR="${PROTENIX_ARTIFACTS_DIR}/data/protenix"
export TORCH_EXTENSIONS_DIR="${TORCH_EXTENSIONS_DIR:-${PROTENIX_RUN_DIR}/torch_extensions}"
mkdir -p "${TORCH_EXTENSIONS_DIR}"

if [[ $# -lt 1 ]]; then
  echo "Usage: sbatch scripts/predict.sbatch INPUT_JSON [OUTPUT_DIR] [MODEL_NAME]" >&2
  exit 2
fi

input_json="$1"
output_dir="${2:-${PROTENIX_RUN_DIR}/output/predict-${SLURM_JOB_ID}}"
model_name="${3:-protenix_base_default_v1.0.0}"

pixi run --locked protenix pred -i "$input_json" -o "$output_dir" -n "$model_name"
