"""Shared artifact paths; code and Pixi remain in the Git checkout."""
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def artifact_root():
    configured = os.environ.get('PROTENIX_ARTIFACTS_DIR')
    path = Path(configured).expanduser() if configured else REPO_ROOT.parent / 'protenix-artifacts'
    if not path.is_absolute():
        raise ValueError('PROTENIX_ARTIFACTS_DIR must be absolute')
    return path


def data_root():
    return artifact_root() / 'data'


def run_root():
    configured = os.environ.get('PROTENIX_RUN_DIR')
    path = Path(configured).expanduser() if configured else artifact_root() / 'runs' / 'kras-5-seeds'
    if not path.is_absolute():
        raise ValueError('PROTENIX_RUN_DIR must be absolute')
    return path


def output_root():
    return run_root() / 'output'


def logs_root():
    return run_root() / 'logs'
