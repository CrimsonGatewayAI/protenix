"""Post-hoc scoring, using label sequence indices and explicit entity selections.

All RMSDs use the global protein CA fit (no ligand refitting). Pocket: protein
heavy atoms within 5 A of the focus ligand; contacts: heavy atom pairs <=4 A.
Ligand RMSD uses CCD atom names, without symmetry minimization.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from Bio.SeqUtils import seq1
from scipy.spatial import cKDTree

from benchmark.prepare import rows, build_input


def atoms(cif, *, asym=None, entity=None):
    selected = [r for r in rows(cif, '_atom_site')
                if (asym is None or r['label_asym_id'] == asym)
                and (entity is None or r['label_entity_id'] == str(entity))
                and r['type_symbol'] not in ('H', 'D')
                and float(r['occupancy']) > 0]
    if not selected:
        raise ValueError(f'No atoms for asym={asym}, entity={entity}')
    if len({r['pdbx_PDB_model_num'] for r in selected}) != 1:
        raise ValueError('Select a single model; multi-model CIF unsupported')
    if len({r['label_asym_id'] for r in selected}) != 1:
        raise ValueError('Entity has multiple copies; explicit copy mapping required')
    # Choose a coherent alternate conformer per residue by total occupancy.
    conformers = {}
    for r in selected:
        key = (r['label_seq_id'], r['auth_seq_id'])
        alt = r['label_alt_id']
        if alt not in ('.', '?'):
            conformers.setdefault(key, {}).setdefault(alt, 0)
            conformers[key][alt] += float(r['occupancy'])
    chosen = {k: sorted(v, key=lambda alt: (-v[alt], alt))[0] for k, v in conformers.items()}
    result = {}
    for r in selected:
        residue = (r['label_seq_id'], r['auth_seq_id'])
        if r['label_alt_id'] not in ('.', '?', chosen.get(residue)):
            continue
        seqid = int(r['label_seq_id']) if r['label_seq_id'] not in ('.', '?') else 1
        key = (seqid, r['label_atom_id'])
        if key in result:
            raise ValueError(f'Duplicate atom mapping {key}')
        xyz = np.array([float(r[f'Cartn_{a}']) for a in 'xyz'])
        if not np.isfinite(xyz).all():
            raise ValueError('Nonfinite coordinates')
        result[key] = {'xyz': xyz, 'resname': r['label_comp_id'], 'element': r['type_symbol'],
                       'auth_seq_id': r['auth_seq_id']}
    return result


def fit(mobile, target):
    mobile, target = np.asarray(mobile, float), np.asarray(target, float)
    if mobile.shape != target.shape or mobile.ndim != 2 or mobile.shape[1] != 3 or len(mobile) < 3:
        raise ValueError('Fit requires matching arrays of >=3 CA coordinates')
    mcenter, tcenter = mobile.mean(0), target.mean(0)
    if min(np.linalg.matrix_rank(mobile-mcenter), np.linalg.matrix_rank(target-tcenter)) < 2:
        raise ValueError('Degenerate CA fit')
    u, _, vt = np.linalg.svd((mobile-mcenter).T @ (target-tcenter))
    correction = np.diag([1., 1., np.linalg.det(u @ vt)])
    rotation = u @ correction @ vt
    return rotation, tcenter - mcenter @ rotation


def rmsd(a, b):
    return float(np.sqrt(np.mean(np.sum((np.asarray(a)-np.asarray(b))**2, axis=1))))


def contacts(protein, ligand, cutoff):
    return {(res, name, lname) for (res, name), atom in protein.items()
            for (_, lname), latom in ligand.items()
            if np.linalg.norm(atom['xyz']-latom['xyz']) <= cutoff}


def residue_contacts(first, second, cutoff=5.):
    if not first or not second:
        return set()
    left, right = list(first.items()), list(second.items())
    tree = cKDTree([atom['xyz'] for _, atom in right])
    neighbors = tree.query_ball_point([atom['xyz'] for _, atom in left], cutoff)
    return {(left[i][0][0], right[j][0][0])
            for i, found in enumerate(neighbors) for j in found}


def score(task, reference, prediction):
    refc, predc = MMCIF2Dict(str(reference)), MMCIF2Dict(str(prediction))
    inp = build_input(task, refc)
    sequence = inp['sequences'][0]['proteinChain']['sequence']
    ref, pred = atoms(refc, asym=task['protein_asym']), atoms(predc, entity=1)
    for (res, name), atom in pred.items():
        if name == 'CA' and (not 1 <= res <= len(sequence) or seq1(atom['resname']) != sequence[res-1]):
            raise ValueError(f'Prediction sequence mismatch at {res}')
    expected_ca = {(i, 'CA') for i in range(1, len(sequence)+1)}
    if not expected_ca <= pred.keys():
        raise ValueError('Prediction lacks expected protein CA atoms')
    keys = sorted(k for k in ref if k[1] == 'CA')
    if not set(keys) <= pred.keys():
        raise ValueError('Prediction lacks observed reference CA atoms')
    for k in keys:
        if ref[k]['resname'] != pred[k]['resname']:
            raise ValueError(f'Reference/prediction residue mismatch: {k}')
    rotation, translation = fit([pred[k]['xyz'] for k in keys], [ref[k]['xyz'] for k in keys])
    aligned = {k: a['xyz'] @ rotation + translation for k, a in pred.items()}
    result = {'prediction': str(prediction), 'n_aligned_ca': len(keys),
              'n_input_residues': len(sequence), 'n_unobserved_reference_ca': len(sequence)-len(keys),
              'ca_rmsd': rmsd([aligned[k] for k in keys], [ref[k]['xyz'] for k in keys]),
              'fit_rotation': rotation.tolist(), 'fit_translation': translation.tolist(),
              'ca_displacements': [{'label_seq_id': k[0], 'auth_seq_id': ref[k]['auth_seq_id'],
                                    'angstrom': float(np.linalg.norm(aligned[k]-ref[k]['xyz']))} for k in keys],
              'ligands': [], 'covalent_bonds': []}
    entities = {1: (ref, pred)}
    ligand_start = 3 if task.get('partner_asym') else 2
    for i, ligand in enumerate(task['ligands'], ligand_start):
        lr, lp = atoms(refc, asym=ligand['asym']), atoms(predc, entity=i)
        entities[i] = (lr, lp)
        if {a['resname'] for a in lr.values()} != {ligand['ccd']}:
            raise ValueError('Reference ligand CCD mismatch')
        if not lr.keys() <= lp.keys():
            raise ValueError(f"Missing predicted ligand atoms: {lr.keys()-lp.keys()}")
        for k in lr:
            if lr[k]['element'] != lp[k]['element'] or lr[k]['resname'] != lp[k]['resname']:
                raise ValueError(f'Ligand chemical identity mismatch: {k}')
        lk = sorted(lr)
        # Compare contacts only on observed atoms shared by both structures.
        common_protein = ref.keys() & pred.keys()
        rp = {k: ref[k] for k in common_protein}
        pp = {k: pred[k] for k in common_protein}
        rc, pc = contacts(rp, lr, 4.), contacts(pp, {k: lp[k] for k in lk}, 4.)
        item = {'ccd': ligand['ccd'], 'n_observed_heavy_atoms': len(lk),
                'n_predicted_heavy_atoms': len(lp),
                'heavy_atom_rmsd': rmsd([lp[k]['xyz'] @ rotation + translation for k in lk],
                                        [lr[k]['xyz'] for k in lk]),
                'contacts_preserved': sorted(rc & pc), 'contacts_lost': sorted(rc-pc),
                'contacts_gained': sorted(pc-rc),
                'unmatched_reference_protein_atoms': len(ref.keys()-pred.keys())}
        result['ligands'].append(item)
        if ligand['ccd'] == task.get('focus_ccd'):
            pocket_residues = {r for r, _, _ in contacts(rp, lr, 5.)}
            pocket = [k for k in keys if k[0] in pocket_residues]
            if not pocket:
                raise ValueError('No observed pocket CA atoms')
            result['pocket_label_seq_ids'] = [k[0] for k in pocket]
            result['pocket_ca_rmsd'] = rmsd([aligned[k] for k in pocket], [ref[k]['xyz'] for k in pocket])
    if task.get('partner_asym'):
        partner_ref = atoms(refc, asym=task['partner_asym'])
        partner_pred = atoms(predc, entity=2)
        partner_sequence = inp['sequences'][1]['proteinChain']['sequence']
        partner_keys = sorted(k for k in partner_ref if k[1] == 'CA')
        if not partner_keys or not set(partner_keys) <= partner_pred.keys():
            raise ValueError('Prediction lacks observed partner CA atoms')
        if {(i, 'CA') for i in range(1, len(partner_sequence)+1)} - partner_pred.keys():
            raise ValueError('Prediction lacks expected partner CA atoms')
        for (res, name), atom in partner_pred.items():
            if name == 'CA' and (not 1 <= res <= len(partner_sequence) or
                                 seq1(atom['resname']) != partner_sequence[res-1]):
                raise ValueError(f'Prediction partner sequence mismatch at {res}')
        for k in partner_keys:
            if partner_ref[k]['resname'] != partner_pred[k]['resname']:
                raise ValueError(f'Partner residue mismatch: {k}')
        reference_pairs = residue_contacts(ref, partner_ref)
        predicted_pairs = residue_contacts(pred, partner_pred)
        interface_primary = [k for k in keys if k[0] in {p[0] for p in reference_pairs}]
        if not interface_primary or not reference_pairs:
            raise ValueError('No observed protein interface')
        common_primary = {k: v for k, v in ref.items() if k in pred}
        common_partner = {k: v for k, v in partner_ref.items() if k in partner_pred}
        reference_pairs = residue_contacts(common_primary, common_partner)
        predicted_pairs = residue_contacts(
            {k: pred[k] for k in common_primary},
            {k: partner_pred[k] for k in common_partner})
        tp = len(reference_pairs & predicted_pairs)
        result['pocket_ca_rmsd'] = rmsd([aligned[k] for k in interface_primary],
                                          [ref[k]['xyz'] for k in interface_primary])
        result['partner'] = {
            'n_aligned_ca': len(partner_keys),
            'ca_rmsd_after_primary_fit': rmsd(
                [partner_pred[k]['xyz'] @ rotation + translation for k in partner_keys],
                [partner_ref[k]['xyz'] for k in partner_keys]),
            'interface_contacts_reference': len(reference_pairs),
            'interface_contacts_predicted': len(predicted_pairs),
            'interface_contacts_preserved': tp,
            'interface_precision': tp/len(predicted_pairs) if predicted_pairs else 0.,
            'interface_recall': tp/len(reference_pairs),
            'interface_f1': 2*tp/(len(reference_pairs)+len(predicted_pairs))
                            if reference_pairs or predicted_pairs else 0.}
    elif 'pocket_ca_rmsd' not in result:
        raise ValueError('Focus ligand not selected')
    for bond in inp['covalent_bonds']:
        coords = []
        for side in (0, 1):
            coords.append([entities[bond[f'entity{j}']][side][(bond[f'position{j}'], bond[f'atom{j}'])]['xyz']
                           for j in (1, 2)])
        rd, pd = [float(np.linalg.norm(pair[0]-pair[1])) for pair in coords]
        result['covalent_bonds'].append({**bond, 'reference_distance': rd, 'predicted_distance': pd,
                                        'distance_difference': pd-rd,
                                        'check': 'geometry_only; explicit bond supplied in input'})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('task')
    parser.add_argument('prediction')
    parser.add_argument('output')
    parser.add_argument('--manifest', default='benchmark/tasks.json')
    parser.add_argument('--reference-root', default='data/references')
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text())
    task = next(t for t in manifest['tasks'] if t['id'] == args.task)
    result = score(task, Path(args.reference_root) / (task['pdb']+'.cif'), args.prediction)
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
