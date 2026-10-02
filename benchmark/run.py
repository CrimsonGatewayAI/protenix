"""Run one manifest task/model on Slurm; exceptions are recorded and re-raised."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback
import threading


def require_msa(path):
    """Require actual search hits for every protein; query-only is not MSA success."""
    for item in json.loads(Path(path).read_text()):
        for entity in item['sequences']:
            if 'proteinChain' not in entity:
                continue
            chain = entity['proteinChain']
            msa = Path(chain['unpairedMsaPath'])
            lines = msa.read_text().splitlines()
            if sum(line.startswith('>') for line in lines) < 2:
                raise ValueError(f'No MSA hits in {msa}')
            first = []
            for line in lines[1:]:
                if line.startswith('>'):
                    break
                first.append(line)
            query = ''.join(c for c in ''.join(first) if c.isupper())
            if query != chain['sequence']:
                raise ValueError(f'MSA query does not match input sequence: {msa}')


def validate_outputs(out, name, seed, samples):
    errors = [p for p in (out / 'ERR').glob('**/*') if p.is_file() and p.stat().st_size]
    if errors:
        raise RuntimeError(f'Protenix reported errors: {errors}')
    files = sorted((out / name / f'seed_{seed}' / 'predictions').glob('*.cif'))
    if len(files) != samples:
        raise RuntimeError(f'Expected {samples} new structures, found {len(files)}')
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict
    import numpy as np
    for path in files:
        cif = MMCIF2Dict(str(path))
        xyz = np.array([cif[f'_atom_site.Cartn_{a}'] for a in 'xyz'], dtype=float)
        if xyz.shape[1] == 0 or not np.isfinite(xyz).all():
            raise ValueError(f'Empty/nonfinite structure: {path}')
    return files


def main():
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('Prediction must run inside an AWS Slurm job')
    parser = argparse.ArgumentParser()
    parser.add_argument('task')
    parser.add_argument('model')
    parser.add_argument('output')
    parser.add_argument('--manifest', default='benchmark/tasks.json')
    parser.add_argument('--input-dir', default='data/inputs')
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text())
    task = next(t for t in manifest['tasks'] if t['id'] == args.task)
    if args.model not in task['models']:
        raise ValueError('Model not selected for this task')
    params = manifest['parameters']
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    metrics = {'status': 'running', 'task': args.task, 'model': manifest['models'][args.model],
               'parameters': params, 'slurm_job_id': os.environ['SLURM_JOB_ID'],
               'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
               'stages_seconds': {}, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    (out / 'source.diff').write_bytes(subprocess.check_output(['git', 'diff', 'HEAD']))
    for module in Path('benchmark').glob('*.py'):
        (out / ('source_' + module.name)).write_bytes(module.read_bytes())
    stop_monitor = threading.Event()
    def monitor_cpu():
        import psutil
        process = psutil.Process()
        tracked = {process.pid: process}
        with (out / 'cpu.csv').open('w') as handle:
            handle.write('elapsed_seconds,rss_bytes,cpu_percent\n')
            while not stop_monitor.is_set():
                rss = 0
                cpu = 0.
                live = [process] + process.children(recursive=True)
                for child in live:
                    tracked.setdefault(child.pid, child)
                    try:
                        rss += tracked[child.pid].memory_info().rss
                        cpu += tracked[child.pid].cpu_percent()
                    except psutil.NoSuchProcess:
                        continue  # A worker exited between enumeration and sampling.
                tracked = {child.pid: tracked[child.pid] for child in live
                           if child.pid in tracked}
                handle.write(f'{time.monotonic()-started},{rss},{cpu}\n')
                handle.flush()
                stop_monitor.wait(1)
    monitor = threading.Thread(target=monitor_cpu, daemon=True)
    monitor.start()

    def timed(label, function, *a, **kw):
        start = time.monotonic()
        try:
            return function(*a, **kw)
        finally:
            elapsed = time.monotonic() - start
            metrics['stages_seconds'][label] = metrics['stages_seconds'].get(label, 0) + elapsed
            (out / 'metrics.json').write_text(json.dumps(metrics, indent=2))

    try:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable on allocated GPU node')
        from torch.utils import cpp_extension
        compile_extension = cpp_extension._jit_compile
        cpp_extension._jit_compile = lambda *a, **kw: timed('extension_build_load', compile_extension, *a, **kw)
        from runner import batch_inference as batch
        from runner.inference import infer_predict
        from protenix.utils.logger import get_logger
        import logging
        logging.basicConfig(level=logging.INFO)
        get_logger(__name__).info('Starting strict benchmark runner')
        # Time official resource download separately, including cache checks.
        download = batch.download_inference_cache
        batch.download_inference_cache = lambda *a, **kw: timed('resource_download', download, *a, **kw)
        batch.inference_configs['dump_dir'] = str(out)
        runner = timed('model_setup_including_download', batch.get_default_runner,
                       seeds=[params['seed']], n_cycle=params['cycles'], n_step=params['steps'],
                       n_sample=params['samples'], dtype=params['dtype'],
                       model_name=manifest['models'][args.model]['name'],
                       use_msa=params['use_msa'], use_template=params['use_template'])
        (out / 'resolved_config.json').write_text(json.dumps(runner.configs.to_dict(), indent=2, default=str))
        source = Path(args.input_dir) / f'{args.task}.json'
        (out / 'input.json').write_bytes(source.read_bytes())
        metrics['input_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        processed = timed('preprocessing', batch.preprocess_input, str(out / 'input.json'),
                          str(out), use_msa=params['use_msa'], use_template=params['use_template'])
        if params['use_msa']:
            require_msa(processed)
        runner.configs['input_json_path'] = processed
        forward = runner.predict
        def measured_predict(*a, **kw):
            torch.cuda.synchronize()
            try:
                return timed('model_forward', forward, *a, **kw)
            finally:
                torch.cuda.synchronize()
        runner.predict = measured_predict
        torch.cuda.reset_peak_memory_stats()
        timed('inference_including_features_and_write', infer_predict, runner, runner.configs)
        files = validate_outputs(out, args.task, params['seed'], params['samples'])
        metrics['structures'] = [str(p.relative_to(out)) for p in files]
        metrics['gpu_peak_allocated_bytes'] = torch.cuda.max_memory_allocated()
        metrics['gpu_peak_reserved_bytes'] = torch.cuda.max_memory_reserved()
        metrics['status'] = 'success'
    except Exception:
        # This is a reporting boundary, never a fallback: preserve traceback and nonzero exit.
        metrics['status'] = 'failed'
        metrics['error'] = traceback.format_exc()
        raise
    finally:
        stop_monitor.set()
        monitor.join(timeout=5)
        metrics['total_seconds'] = time.monotonic() - started
        metrics['allocated_gpu_hours_process'] = metrics['total_seconds'] / 3600
        (out / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')


if __name__ == '__main__':
    main()
