"""Build an honest per-run result table from real Slurm outputs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess

from benchmark.score import score


def sacct(job_id):
    result = subprocess.run(['sacct', '-n', '-P', '-j', str(job_id),
                             '--format=JobIDRaw,State,ElapsedRaw,TotalCPU,MaxRSS,ExitCode'],
                            capture_output=True, text=True)
    if result.returncode:
        if 'accounting storage is disabled' not in result.stderr:
            raise RuntimeError(f'sacct failed: {result.stderr}')
        return {'available': False, 'reason': result.stderr.strip()}
    return [dict(zip(('job_id', 'state', 'elapsed_seconds', 'total_cpu', 'max_rss', 'exit_code'),
                     line.split('|'))) for line in result.stdout.splitlines() if line]


def gpu_telemetry(path):
    if not path.exists():
        return {}
    with path.open() as stream:
        rows = list(csv.DictReader(stream, skipinitialspace=True))
    def numbers(key):
        return [float(row[key].split()[0]) for row in rows if row.get(key) and row[key].split()[0] not in ('N/A', '[Not')]
    memory = numbers('memory.used [MiB]')
    util = numbers('utilization.gpu [%]')
    power = numbers('power.draw [W]')
    return {'gpu_memory_peak_mib': max(memory) if memory else None,
            'gpu_utilization_mean_percent': sum(util)/len(util) if util else None,
            'gpu_utilization_peak_percent': max(util) if util else None,
            'gpu_power_mean_watts': sum(power)/len(power) if power else None,
            'gpu_samples': len(rows)}


def build(manifest, root, audit_path='data/inputs/audit.json', reference_root='data/references',
          checkpoint_root='data/protenix/checkpoint'):
    table = []
    audit = {t['id']: t for t in json.loads(Path(audit_path).read_text())}
    model_blockers = {}
    weight_hashes = {}
    for directory in root.iterdir():
        metric_path = directory / 'metrics.json'
        if not metric_path.exists():
            continue
        prior = json.loads(metric_path.read_text())
        checkpoint = Path(checkpoint_root) / (prior['model']['name'] + '.pt')
        if (prior.get('status') == 'failed' and 'HTTP Error 403' in prior.get('error', '')
                and 'resource_download' in prior.get('stages_seconds', {})
                and not checkpoint.exists()):
            model_blockers[prior['model']['name']] = {
                'reason': 'Official model checkpoint download returned HTTP 403',
                'job_id': prior['slurm_job_id']}
    for task in manifest['tasks']:
        for model in task['models']:
            name = f"{task['id']}-{model}"
            directory = root / name
            metric_path = directory / 'metrics.json'
            item = {'task': task['id'], 'pdb': task['pdb'], 'model': model,
                    'release_date': audit[task['id']]['release_date'],
                    'training_cutoff': manifest['models'][model]['training_cutoff'],
                    'split': audit[task['id']]['split'][model],
                    'construction_notes': task['notes']}
            if not metric_path.exists():
                blocker = model_blockers.get(manifest['models'][model]['name'])
                item['status'] = 'blocked_by_checkpoint' if blocker else 'not_run'
                if blocker:
                    item['blocker'] = blocker
                table.append(item)
                continue
            metrics = json.loads(metric_path.read_text())
            item.update({'status': metrics['status'], 'job_id': metrics['slurm_job_id'],
                         'total_seconds': metrics.get('total_seconds'),
                         'gpu_hours_process': metrics.get('allocated_gpu_hours_process'),
                         'stages_seconds': metrics.get('stages_seconds', {}),
                         'gpu_peak_allocated_bytes': metrics.get('gpu_peak_allocated_bytes'),
                         'gpu_peak_reserved_bytes': metrics.get('gpu_peak_reserved_bytes'),
                         'error': metrics.get('error')})
            if 'checkpoint_source' in metrics:
                item['checkpoint_source'] = metrics['checkpoint_source']
            item['slurm_accounting'] = sacct(metrics['slurm_job_id'])
            time_log = Path('logs') / f"time-{metrics['slurm_job_id']}.txt"
            if time_log.exists():
                item['gnu_time_log'] = str(time_log)
                item['gnu_time'] = time_log.read_text()
            item.update(gpu_telemetry(Path('logs') / f"gpu-{metrics['slurm_job_id']}.csv"))
            cpu = directory / 'cpu.csv'
            if cpu.exists():
                with cpu.open() as stream:
                    samples = list(csv.DictReader(stream))
                item['process_tree_rss_peak_bytes'] = max((int(row['rss_bytes']) for row in samples), default=None)
                item['sampled_cpu_percent_peak'] = max((float(row['cpu_percent']) for row in samples), default=None)
            if metrics['status'] == 'success':
                checkpoint = Path(checkpoint_root) / (manifest['models'][model]['name'] + '.pt')
                if checkpoint.exists():
                    if model not in weight_hashes:
                        with checkpoint.open('rb') as stream:
                            weight_hashes[model] = hashlib.file_digest(stream, 'sha256').hexdigest()
                    item['checkpoint_sha256'] = weight_hashes[model]
                else:
                    item['checkpoint_sha256_unavailable'] = str(checkpoint)
                structures = metrics['structures']
                if len(structures) != manifest['parameters']['samples']:
                    raise ValueError(f'Missing successful structure in {name}')
                item['scores'] = [score(task, Path(reference_root)/(task['pdb']+'.cif'),
                                        directory / path) for path in structures]
                if len(item['scores']) == 1:
                    item['score'] = item['scores'][0]
                (directory / 'score.json').write_text(json.dumps(item['scores'], indent=2) + '\n')
            table.append(item)
    return table


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', default='benchmark/tasks.json')
    parser.add_argument('--output-root', default='output')
    parser.add_argument('--report', default='output/summary.json')
    parser.add_argument('--csv', default='output/summary.csv')
    parser.add_argument('--audit', default='data/inputs/audit.json')
    parser.add_argument('--reference-root', default='data/references')
    parser.add_argument('--checkpoint-root', default='data/protenix/checkpoint')
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text())
    table = build(manifest, Path(args.output_root), args.audit, args.reference_root,
                  args.checkpoint_root)
    Path(args.report).write_text(json.dumps(table, indent=2) + '\n')
    with Path(args.csv).open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(('task', 'pdb', 'model', 'status', 'release_date', 'split',
                         'aligned_ca', 'ca_rmsd_A', 'pocket_ca_rmsd_A',
                         'focus_ligand_rmsd_A', 'preprocessing_s', 'model_forward_s',
                         'total_s', 'cpu_rss_peak_bytes', 'cpu_percent_peak_sampled',
                         'gpu_memory_peak_mib',
                         'gpu_utilization_mean_percent', 'gpu_hours_process', 'slurm_job_id'))
        for item in table:
            task = next(t for t in manifest['tasks'] if t['id'] == item['task'])
            for s in item.get('scores', [{}]):
                focus = next((lig for lig in s.get('ligands', [])
                              if lig['ccd'] == task['focus_ccd']), {})
                stages = item.get('stages_seconds', {})
                writer.writerow((item['task'], item['pdb'], item['model'], item['status'],
                                 item['release_date'], item['split'], s.get('n_aligned_ca'),
                                 s.get('ca_rmsd'), s.get('pocket_ca_rmsd'),
                                 focus.get('heavy_atom_rmsd'), stages.get('preprocessing'),
                                 stages.get('model_forward'), item.get('total_seconds'),
                                 item.get('process_tree_rss_peak_bytes'),
                                 item.get('sampled_cpu_percent_peak'),
                                 item.get('gpu_memory_peak_mib'),
                                 item.get('gpu_utilization_mean_percent'),
                                 item.get('gpu_hours_process'), item.get('job_id')))
    print('task,model,status,CA_RMSD,pocket_CA_RMSD,ligand_RMSD,total_s,GPU_peak_MiB,job')
    for item in table:
        for sample_index, s in enumerate(item.get('scores', [{}])):
            ligand = next((x for x in s.get('ligands', []) if x['ccd'] ==
                           next(t for t in manifest['tasks'] if t['id'] == item['task'])['focus_ccd']), {})
            print(','.join(str(x if x is not None else '') for x in
                           (item['task'], item['model'] + (f':sample{sample_index}' if item.get('scores') and len(item['scores']) > 1 else ''),
                            item['status'], s.get('ca_rmsd'), s.get('pocket_ca_rmsd'),
                            ligand.get('heavy_atom_rmsd'), item.get('total_seconds'),
                            item.get('gpu_memory_peak_mib'), item.get('job_id'))))
