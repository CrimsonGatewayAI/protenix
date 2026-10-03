#!/usr/bin/env bash
#SBATCH --job-name=kras-benchmark
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=56G
#SBATCH --time=04:00:00
#SBATCH --output=logs/benchmark-%j.out

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
export PATH="${HOME}/.pixi/bin:${PATH}"
export PROTENIX_ARTIFACTS_DIR="${PROTENIX_ARTIFACTS_DIR:-$(dirname "${SLURM_SUBMIT_DIR}")/protenix-artifacts}"
export PROTENIX_RUN_DIR="${PROTENIX_RUN_DIR:-${PROTENIX_ARTIFACTS_DIR}/runs/kras-5-seeds}"
export PROTENIX_ROOT_DIR="${PROTENIX_ARTIFACTS_DIR}/data/protenix"
export TORCH_EXTENSIONS_DIR="${PROTENIX_ARTIFACTS_DIR}/data/torch_extensions"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export PYTHONUNBUFFERED=1
if [[ $# != 3 && $# != 4 ]]; then
    echo "Usage: sbatch scripts/benchmark.sbatch TASK MODEL OUTPUT [SEED]" >&2
    exit 2
fi
mkdir -p "${PROTENIX_RUN_DIR}/logs"
telemetry="${PROTENIX_RUN_DIR}/logs/gpu-${SLURM_JOB_ID}.csv"
nvidia-smi --query-gpu=timestamp,uuid,memory.used,utilization.gpu,utilization.memory,power.draw --format=csv -l 1 > "$telemetry" &
monitor_pid=$!
trap 'kill "$monitor_pid" 2>/dev/null || true; wait "$monitor_pid" 2>/dev/null || true' EXIT
if [[ $# == 4 ]]; then
    /usr/bin/time -v -o "${PROTENIX_RUN_DIR}/logs/time-${SLURM_JOB_ID}.txt" \
        pixi run --locked python -m benchmark.run "$1" "$2" "$3" --seed "$4"
else
    /usr/bin/time -v -o "${PROTENIX_RUN_DIR}/logs/time-${SLURM_JOB_ID}.txt" \
        pixi run --locked python -m benchmark.run "$1" "$2" "$3"
fi
