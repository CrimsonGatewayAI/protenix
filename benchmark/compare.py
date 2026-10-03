"""Paired, single-sample comparison of two selected model variants."""
import argparse
import csv
import json
from pathlib import Path
from benchmark.paths import output_root


def paired(summary, manifest, left, right):
    if left not in manifest['models'] or right not in manifest['models']:
        raise ValueError('Unknown model key')
    indexed = {(item['task'], item['model']): item for item in summary}
    result = []
    for task in manifest['tasks']:
        if not {left, right} <= set(task['models']):
            continue
        a, b = indexed[(task['id'], left)], indexed[(task['id'], right)]
        row = {'task': task['id'], 'pdb': task['pdb'], 'left_model': left,
               'right_model': right, 'left_status': a['status'], 'right_status': b['status'],
               'left_checkpoint_source': a.get('checkpoint_source')}
        if a['status'] == b['status'] == 'success':
            if len(a['scores']) != 1 or len(b['scores']) != 1:
                raise ValueError('Paired comparison needs one sample per task/model')
            x, y = a['scores'][0], b['scores'][0]
            xlig = next(item for item in x['ligands'] if item['ccd'] == task['focus_ccd'])
            ylig = next(item for item in y['ligands'] if item['ccd'] == task['focus_ccd'])
            row.update({
                'left_aligned_ca': x['n_aligned_ca'],
                'right_aligned_ca': y['n_aligned_ca'],
                'left_ca_rmsd_A': x['ca_rmsd'],
                'right_ca_rmsd_A': y['ca_rmsd'],
                'delta_ca_rmsd_A': x['ca_rmsd']-y['ca_rmsd'],
                'left_pocket_ca_rmsd_A': x['pocket_ca_rmsd'],
                'right_pocket_ca_rmsd_A': y['pocket_ca_rmsd'],
                'delta_pocket_ca_rmsd_A': x['pocket_ca_rmsd']-y['pocket_ca_rmsd'],
                'left_focus_ligand_rmsd_A': xlig['heavy_atom_rmsd'],
                'right_focus_ligand_rmsd_A': ylig['heavy_atom_rmsd'],
                'delta_focus_ligand_rmsd_A': xlig['heavy_atom_rmsd']-ylig['heavy_atom_rmsd'],
                'left_model_forward_s': a['stages_seconds'].get('model_forward'),
                'right_model_forward_s': b['stages_seconds'].get('model_forward'),
            })
        result.append(row)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--summary', default=str(output_root() / 'summary.json'))
    parser.add_argument('--manifest', default='benchmark/tasks.json')
    parser.add_argument('--left', default='v2')
    parser.add_argument('--right', default='v1')
    parser.add_argument('--csv', default=str(output_root() / 'comparison-internal.csv'))
    args = parser.parse_args()
    rows = paired(json.loads(Path(args.summary).read_text()),
                  json.loads(Path(args.manifest).read_text()), args.left, args.right)
    columns = ['task', 'pdb', 'left_model', 'right_model', 'left_status', 'right_status',
               'left_checkpoint_source', 'left_aligned_ca', 'right_aligned_ca',
               'left_ca_rmsd_A', 'right_ca_rmsd_A', 'delta_ca_rmsd_A',
               'left_pocket_ca_rmsd_A', 'right_pocket_ca_rmsd_A', 'delta_pocket_ca_rmsd_A',
               'left_focus_ligand_rmsd_A', 'right_focus_ligand_rmsd_A',
               'delta_focus_ligand_rmsd_A', 'left_model_forward_s', 'right_model_forward_s']
    with Path(args.csv).open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(rows, indent=2))
