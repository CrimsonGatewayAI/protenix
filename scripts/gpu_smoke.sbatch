#!/usr/bin/env bash
#SBATCH --job-name=protenix-gpu-smoke
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=logs/gpu-smoke-%j.out

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"

nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

.pixi/envs/default/bin/python - <<'PY'
import torch

assert torch.cuda.is_available(), "PyTorch cannot access CUDA"
device = torch.device("cuda:0")
a = torch.ones((1024, 1024), device=device)
b = a @ a
torch.cuda.synchronize()
assert b[0, 0].item() == 1024.0
print(f"PyTorch {torch.__version__}; CUDA {torch.version.cuda}")
print(f"GPU: {torch.cuda.get_device_name(device)}")
print(f"Matrix multiplication passed: {b[0, 0].item()}")
PY
