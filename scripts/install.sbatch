#!/usr/bin/env bash
#SBATCH --job-name=protenix-install
#SBATCH --partition=gpu
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=logs/install-%j.out

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
export PATH="${HOME}/.pixi/bin:${PATH}"
pixi install --locked
pixi run --locked check
