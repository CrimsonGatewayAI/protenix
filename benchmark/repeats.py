"""Aggregate independent single-seed Slurm runs into performance and resource tables."""
import argparse
import csv
import hashlib
import json
import statistics
from pathlib import Path

from benchmark.report import gpu_telemetry
from benchmark.score import score
from benchmark.paths import data_root, output_root, logs_root


def run_directory(root, task, model, seed, first_seed):
    legacy = root / f'{task}-{model}'
    if seed == first_seed and (legacy / 'metrics.json').exists():
        return legacy
    return root / f'{task}-{model}-seed{seed}'


def summarize(values):
    values = [float(x) for x in values if x is not None]
    if not values:
        return None
    return {'mean': statistics.mean(values), 'sd': statistics.stdev(values) if len(values) > 1 else 0.,
            'min': min(values), 'max': max(values), 'n': len(values)}


def collect(manifest, root, reference_root=None, input_root=None):
    reference_root = data_root() / 'references' if reference_root is None else Path(reference_root)
    input_root = data_root() / 'inputs' if input_root is None else Path(input_root)
    seeds = manifest['parameters']['seeds']
    if len(seeds) != len(set(seeds)) or not seeds:
        raise ValueError('Expected distinct nonempty seeds')
    runs = []
    for task in manifest['tasks']:
        input_file = Path(input_root) / f"{task['id']}.json"
        expected_input_hash = hashlib.sha256(input_file.read_bytes()).hexdigest()
        for model in task['models']:
            for seed in seeds:
                directory = run_directory(root, task['id'], model, seed, seeds[0])
                row = {'task': task['id'], 'pdb': task['pdb'], 'model': model,
                       'seed': seed, 'directory': str(directory), 'status': 'not_run'}
                metrics_path = directory / 'metrics.json'
                if not metrics_path.exists():
                    runs.append(row)
                    continue
                metrics = json.loads(metrics_path.read_text())
                if metrics['task'] != task['id'] or metrics['model']['name'] != manifest['models'][model]['name']:
                    raise ValueError(f'Run identity mismatch: {directory}')
                if metrics['parameters']['seed'] != seed:
                    raise ValueError(f'Seed mismatch: {directory}')
                if (metrics['status'] == 'success' or metrics.get('input_sha256')) and \
                        metrics.get('input_sha256') != expected_input_hash:
                    raise ValueError(f'Input hash differs across repetitions: {directory}')
                row.update({'status': metrics['status'], 'job_id': metrics['slurm_job_id'],
                            'error': metrics.get('error'), 'checkpoint_sha256': metrics.get('checkpoint_sha256'),
                            'input_sha256': metrics.get('input_sha256'),
                            'checkpoint_source': metrics.get('checkpoint_source'),
                            'total_s': metrics.get('total_seconds'),
                            'preprocessing_s': metrics.get('stages_seconds', {}).get('preprocessing'),
                            'model_forward_s': metrics.get('stages_seconds', {}).get('model_forward'),
                            'gpu_hours': metrics.get('allocated_gpu_hours_process')})
                row.update(gpu_telemetry(logs_root() / f"gpu-{metrics['slurm_job_id']}.csv"))
                cpu_path = directory / 'cpu.csv'
                if cpu_path.exists():
                    with cpu_path.open() as handle:
                        samples = list(csv.DictReader(handle))
                    row['cpu_percent_peak'] = max((float(x['cpu_percent']) for x in samples), default=None)
                    row['rss_peak_bytes'] = max((int(x['rss_bytes']) for x in samples), default=None)
                if metrics['status'] == 'success':
                    structures = metrics['structures']
                    if len(structures) != 1:
                        raise ValueError(f'Expected one structure: {directory}')
                    result = score(task, reference_root / f"{task['pdb']}.cif", directory / structures[0])
                    row['aligned_ca'] = result['n_aligned_ca']
                    row['ca_rmsd_A'] = result['ca_rmsd']
                    row['pocket_ca_rmsd_A'] = result['pocket_ca_rmsd']
                    if task.get('partner_asym'):
                        row['partner_ca_rmsd_A'] = result['partner']['ca_rmsd_after_primary_fit']
                        row['interface_f1'] = result['partner']['interface_f1']
                    else:
                        ligand = next(x for x in result['ligands'] if x['ccd'] == task['focus_ccd'])
                        row['focus_rmsd_A'] = ligand['heavy_atom_rmsd']
                        tp = len(ligand['contacts_preserved'])
                        row['interface_f1'] = 2*tp / (2*tp + len(ligand['contacts_lost']) +
                                                       len(ligand['contacts_gained']))
                    (directory / 'score.json').write_text(json.dumps(result, indent=2) + '\n')
                runs.append(row)
    return runs


def aggregate(runs, manifest, usd_hour=None):
    groups = []
    for task in manifest['tasks']:
        for model in task['models']:
            selected = [r for r in runs if r['task'] == task['id'] and r['model'] == model]
            success = [r for r in selected if r['status'] == 'success']
            observed = [r for r in selected if r['status'] in ('success', 'failed')]
            base = {'task': task['id'], 'pdb': task['pdb'], 'model': model,
                    'success': len(success), 'planned': len(selected),
                    'type': 'nanobody' if task.get('partner_asym') else 'small_molecule'}
            performance = dict(base)
            for name in ('aligned_ca', 'ca_rmsd_A', 'pocket_ca_rmsd_A', 'focus_rmsd_A',
                         'partner_ca_rmsd_A', 'interface_f1'):
                performance[name] = summarize([r.get(name) for r in success])
            resources = dict(base)
            resources['observed'] = len(observed)
            for name in ('preprocessing_s', 'model_forward_s', 'total_s', 'cpu_percent_peak',
                         'rss_peak_bytes', 'gpu_memory_peak_mib', 'gpu_utilization_mean_percent'):
                resources[name] = summarize([r.get(name) for r in observed])
            resources['gpu_hours_total'] = sum(r.get('gpu_hours') or 0 for r in observed)
            resources['process_cost_usd_estimate'] = (
                resources['gpu_hours_total'] * usd_hour if usd_hour is not None else None)
            groups.append((performance, resources))
    return [p for p, _ in groups], [r for _, r in groups]


def format_stat(value, digits=2, show_range=False):
    if value is None:
        return '—'
    display = f"{value['mean']:.{digits}f} ± {value['sd']:.{digits}f}"
    if show_range:
        display += f" ({value['min']:.{digits}f}–{value['max']:.{digits}f})"
    return display


PERFORMANCE_COLUMNS = ('任务', '实验结构', '模型', '成功/计划', '对齐残基数',
                       'KRAS Cα RMSD Å', '结合部位 Cα RMSD Å', 'GDP/药物 RMSD Å',
                       '纳米抗体位置 RMSD Å', '接触 F1')
RESOURCE_COLUMNS = ('任务', '实验结构', '模型', '实测/计划', '预处理秒', '推理秒', '总秒',
                    'CPU峰值%', 'RSS峰值 GiB', 'GPU显存峰值 MiB', 'GPU利用率%',
                    'GPU小时合计', '进程费用估算 USD')


def write_summary_csvs(performance, resources, root):
    """Write two complete, human-readable UTF-8 CSV summary tables."""
    with (root / 'performance.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(PERFORMANCE_COLUMNS)
        for row in performance:
            writer.writerow((row['task'], row['pdb'], row['model'],
                             f"{row['success']}/{row['planned']}",
                             format_stat(row['aligned_ca'], 0),
                             format_stat(row['ca_rmsd_A'], show_range=True),
                             format_stat(row['pocket_ca_rmsd_A'], show_range=True),
                             format_stat(row['focus_rmsd_A'], show_range=True),
                             format_stat(row['partner_ca_rmsd_A'], show_range=True),
                             format_stat(row['interface_f1'], show_range=True)))
    with (root / 'resources.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(RESOURCE_COLUMNS)
        for row in resources:
            rss = row['rss_peak_bytes']
            gpu_memory = row['gpu_memory_peak_mib']
            cost = row['process_cost_usd_estimate']
            writer.writerow((row['task'], row['pdb'], row['model'],
                             f"{row['observed']}/{row['planned']}",
                             format_stat(row['preprocessing_s']),
                             format_stat(row['model_forward_s']),
                             format_stat(row['total_s']),
                             format_stat(row['cpu_percent_peak'], 0),
                             '—' if rss is None else f"{rss['max']/2**30:.2f}",
                             '—' if gpu_memory is None else f"{gpu_memory['max']:.0f}",
                             format_stat(row['gpu_utilization_mean_percent'], 0),
                             f"{row['gpu_hours_total']:.3f}",
                             '—' if cost is None else f'{cost:.3f}'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', default='benchmark/tasks.json')
    parser.add_argument('--output-root', default=str(output_root()))
    parser.add_argument('--usd-hour', type=float)
    args = parser.parse_args()
    if args.usd_hour is not None and args.usd_hour <= 0:
        raise ValueError('Hourly price must be positive')
    manifest = json.loads(Path(args.manifest).read_text())
    runs = collect(manifest, Path(args.output_root))
    performance, resources = aggregate(runs, manifest, args.usd_hour)
    root = Path(args.output_root)
    (root / 'runs.json').write_text(json.dumps(runs, indent=2) + '\n')
    (root / 'performance.json').write_text(json.dumps(performance, indent=2) + '\n')
    (root / 'resources.json').write_text(json.dumps(resources, indent=2) + '\n')
    write_summary_csvs(performance, resources, root)
    with (root / 'runs.csv').open('w', newline='') as handle:
        fields = sorted({key for row in runs for key in row} - {'checkpoint_source'})
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: value for key, value in row.items() if key in fields} for row in runs)
    print(f"Wrote {len(performance)} rows each to {root / 'performance.csv'} and {root / 'resources.csv'}")
