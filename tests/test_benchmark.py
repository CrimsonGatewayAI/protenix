import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from benchmark.prepare import build_input
from benchmark.run import require_msa, validate_outputs
from benchmark.report import build
from benchmark.compare import paired
from benchmark.repeats import (PERFORMANCE_COLUMNS, RESOURCE_COLUMNS, aggregate,
                               collect, run_directory, write_summary_csvs)
from benchmark.paths import artifact_root, data_root, logs_root, output_root, run_root
from benchmark.score import fit, rmsd
from benchmark.score import score
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from Bio.PDB.mmcifio import MMCIFIO


class FitTests(unittest.TestCase):
    def test_multiple_shapes_and_transforms(self):
        rng = np.random.default_rng(72)
        for n in (3, 7, 59, 201):
            points = rng.normal(size=(n, 3))
            q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
            q[:, 0] *= np.linalg.det(q)
            target = points @ q + rng.normal(size=3)
            rotation, translation = fit(points, target)
            self.assertLess(rmsd(points @ rotation + translation, target), 1e-10)

    def test_reflection_is_not_allowed(self):
        p = np.random.default_rng(12).normal(size=(15, 3))
        target = p * [-1, 1, 1]
        rotation, translation = fit(p, target)
        self.assertGreater(np.linalg.det(rotation), .99)
        self.assertGreater(rmsd(p @ rotation + translation, target), .1)

    def test_invalid_fit_fails(self):
        for p in (np.zeros((2, 3)), np.zeros((5, 3))):
            with self.assertRaises(ValueError):
                fit(p, p)


class InputTests(unittest.TestCase):
    def metadata(self, sequence):
        return {'_struct_asym.id': ['Z', 'Q'], '_struct_asym.entity_id': ['7', '9'],
                '_entity_poly.entity_id': ['7'], '_entity_poly.type': ['polypeptide(L)'],
                '_entity_poly.nstd_monomer': ['no'],
                '_entity_poly.pdbx_seq_one_letter_code_can': [sequence],
                '_pdbx_entity_nonpoly.entity_id': ['9'], '_pdbx_entity_nonpoly.comp_id': ['ATP']}

    def test_distinct_sequences_and_nonstandard_chain_ids(self):
        for sequence in ('ACDEFG', 'MKWVTFISLLFLFSSAYS'):
            task = {'id': 'independent', 'protein_asym': 'Z', 'ligands': [{'asym': 'Q', 'ccd': 'ATP'}]}
            result = build_input(task, self.metadata(sequence))
            self.assertEqual(result['sequences'][0]['proteinChain']['sequence'], sequence)
            self.assertEqual(result['sequences'][1]['ligand']['ligand'], 'CCD_ATP')
            self.assertNotIn('templatesPath', json.dumps(result))
            self.assertNotIn('Cartn', json.dumps(result))

    def test_bad_ligand_and_modified_protein_fail(self):
        task = {'id': 'bad', 'protein_asym': 'Z', 'ligands': [{'asym': 'Q', 'ccd': 'GDP'}]}
        with self.assertRaises(ValueError):
            build_input(task, self.metadata('ACDE'))
        task['ligands'] = []
        with self.assertRaises(ValueError):
            build_input(task, self.metadata('ACX'))

    def test_covalent_position_comes_from_metadata(self):
        for position in (2, 6):
            cif = self.metadata('ACDEFC')
            fields = {'conn_type_id': 'covale', 'ptnr1_label_asym_id': 'Z',
                      'ptnr2_label_asym_id': 'Q', 'ptnr1_label_seq_id': str(position),
                      'ptnr2_label_seq_id': '.', 'ptnr1_label_atom_id': 'SG',
                      'ptnr2_label_atom_id': 'C7', 'ptnr1_symmetry': '1_555',
                      'ptnr2_symmetry': '1_555'}
            cif.update({'_struct_conn.'+k: [v] for k, v in fields.items()})
            task = {'id': 'test', 'protein_asym': 'Z', 'ligands': [{'asym': 'Q', 'ccd': 'ATP'}]}
            result = build_input(task, cif)
            self.assertEqual(result['covalent_bonds'][0]['position1'], position)
            task['ligands'] = []
            with self.assertRaises(ValueError):
                build_input(task, cif)

    def test_two_distinct_protein_chains_are_preserved(self):
        cif = self.metadata('ACDE')
        cif['_struct_asym.id'].append('R')
        cif['_struct_asym.entity_id'].append('11')
        for key, value in {'entity_id': '11', 'type': 'polypeptide(L)',
                           'nstd_monomer': 'no',
                           'pdbx_seq_one_letter_code_can': 'MKWVTF'}.items():
            cif['_entity_poly.'+key].append(value)
        task = {'id': 'complex', 'protein_asym': 'Z', 'partner_asym': 'R',
                'ligands': [{'asym': 'Q', 'ccd': 'ATP'}]}
        result = build_input(task, cif)
        self.assertEqual([x['proteinChain']['sequence'] for x in result['sequences'][:2]],
                         ['ACDE', 'MKWVTF'])
        self.assertEqual(result['sequences'][2]['ligand']['ligand'], 'CCD_ATP')
        self.assertNotIn('Cartn', json.dumps(result))


class FailureTests(unittest.TestCase):
    def test_msa_failure_visible(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            msa = root / 'hits.a3m'
            inp = root / 'input.json'
            inp.write_text(json.dumps([{'sequences': [{'proteinChain': {
                'sequence': 'ACDE', 'unpairedMsaPath': str(msa)}}]}]))
            msa.write_text('>query\nACDE\n')
            with self.assertRaises(ValueError):
                require_msa(inp)
            msa.write_text('>query\nACDE\n>hit\nAC-E\n')
            require_msa(inp)
            msa.write_text('>query\nACDF\n>hit\nAC-E\n')
            with self.assertRaises(ValueError):
                require_msa(inp)

    def test_missing_output_and_upstream_errors_fail(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            with self.assertRaises(RuntimeError):
                validate_outputs(root, 'different_target', 18, 2)
            (root / 'ERR').mkdir()
            (root / 'ERR' / 'failed.txt').write_text('CUDA out of memory')
            with self.assertRaisesRegex(RuntimeError, 'reported errors'):
                validate_outputs(root, 'different_target', 18, 2)

    def test_checkpoint_blocker_clears_when_weight_arrives(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            output, cache = root/'output', root/'cache'
            (output/'first-v2').mkdir(parents=True)
            cache.mkdir()
            manifest = {'models': {'v2': {'name': 'different_official_model',
                                         'training_cutoff': '2021-09-30'}},
                        'tasks': [{'id': 'first', 'pdb': '1AAA', 'models': ['v2'],
                                   'notes': ''},
                                  {'id': 'second', 'pdb': '2BBB', 'models': ['v2'],
                                   'notes': ''}]}
            audit = [{'id': t['id'], 'release_date': '2020-01-01',
                      'split': {'v2': 'retrospective'}} for t in manifest['tasks']]
            audit_file = root/'audit.json'
            audit_file.write_text(json.dumps(audit))
            (output/'first-v2'/'metrics.json').write_text(json.dumps({
                'model': manifest['models']['v2'], 'status': 'failed',
                'error': 'HTTP Error 403', 'slurm_job_id': '9',
                'stages_seconds': {'resource_download': 1}}))
            self.assertEqual(build(manifest, output, audit_file, checkpoint_root=cache)[1]['status'],
                             'blocked_by_checkpoint')
            (cache/'different_official_model.pt').write_bytes(b'weight-received')
            self.assertEqual(build(manifest, output, audit_file, checkpoint_root=cache)[1]['status'],
                             'not_run')


class ScoringTests(unittest.TestCase):
    def write_structure(self, path, n, *, predicted=False, ligand_shift=0, omit_ligand=False):
        rng = np.random.default_rng(n)
        points = rng.normal(size=(n, 3)) * 2
        metadata = InputTests().metadata('A' * n)
        metadata['data_'] = 'independent'
        metadata['_pdbx_entity_nonpoly.comp_id'] = ['ATP']
        columns = ['group_PDB', 'id', 'type_symbol', 'label_atom_id', 'label_alt_id',
                   'label_comp_id', 'label_asym_id', 'label_entity_id', 'label_seq_id',
                   'auth_seq_id', 'occupancy', 'Cartn_x', 'Cartn_y', 'Cartn_z', 'pdbx_PDB_model_num']
        data = []
        for i, point in enumerate(points, 1):
            if not predicted and i == 2:
                continue  # An experimental unresolved residue must not enter RMSD.
            xyz = point + (np.array([8., 1., -3.]) if predicted else 0)
            data.append(['ATOM', str(len(data)+1), 'C', 'CA', '.', 'ALA',
                         'A' if predicted else 'Z', '1' if predicted else '7', str(i), str(i+40),
                         '1', *map(str, xyz), '1'])
        for j, point in enumerate(([0., 0., 0.], [1., 0., 0.])):
            if omit_ligand and j == 1:
                continue
            xyz = np.array(point) + (np.array([8.+ligand_shift, 1., -3.]) if predicted else 0)
            data.append(['HETATM', str(len(data)+1), 'C', f'C{j+1}', '.', 'ATP',
                         'L2' if predicted else 'Q', '2' if predicted else '9', '.', '401',
                         '1', *map(str, xyz), '1'])
        metadata.update({'_atom_site.'+col: [row[i] for row in data] for i, col in enumerate(columns)})
        writer = MMCIFIO()
        writer.set_dict(metadata)
        writer.save(str(path))

    def test_missing_reference_residues_and_displaced_ligands(self):
        task = {'id': 'unseen', 'protein_asym': 'Z', 'ligands': [{'asym': 'Q', 'ccd': 'ATP'}],
                'focus_ccd': 'ATP'}
        for n in (5, 17):
            with tempfile.TemporaryDirectory() as root:
                ref, pred = Path(root)/'ref.cif', Path(root)/'pred.cif'
                self.write_structure(ref, n)
                self.write_structure(pred, n, predicted=True, ligand_shift=2.)
                result = score(task, ref, pred)
                self.assertEqual(result['n_aligned_ca'], n-1)
                self.assertEqual(result['n_unobserved_reference_ca'], 1)
                self.assertLess(result['ca_rmsd'], 1e-10)
                self.assertAlmostEqual(result['ligands'][0]['heavy_atom_rmsd'], 2.)
                self.assertTrue(result['ligands'][0]['contacts_lost'] or result['ligands'][0]['contacts_gained'])
                self.write_structure(pred, n, predicted=True, omit_ligand=True)
                with self.assertRaisesRegex(ValueError, 'Missing predicted ligand atoms'):
                    score(task, ref, pred)

    def test_paired_comparison_is_generic_and_exposes_failures(self):
        manifest = {'models': {'new': {}, 'old': {}},
                    'tasks': [{'id': 'arbitrary', 'pdb': '1XYZ', 'focus_ccd': 'ATP',
                               'models': ['new', 'old']},
                              {'id': 'another', 'pdb': '2XYZ', 'focus_ccd': 'GDP',
                               'models': ['new', 'old']}]}
        def result(task, model, rmsd):
            return {'task': task, 'model': model, 'status': 'success',
                    'scores': [{'n_aligned_ca': 12, 'ca_rmsd': rmsd,
                                'pocket_ca_rmsd': rmsd/2,
                                'ligands': [{'ccd': 'ATP' if task == 'arbitrary' else 'GDP',
                                             'heavy_atom_rmsd': rmsd*2}]}],
                    'stages_seconds': {'model_forward': 7.}}
        summary = [result('arbitrary', 'new', .8), result('arbitrary', 'old', 1.2),
                   result('another', 'old', 2.)]
        summary.append({'task': 'another', 'model': 'new', 'status': 'failed'})
        comparison = paired(summary, manifest, 'new', 'old')
        self.assertAlmostEqual(comparison[0]['delta_ca_rmsd_A'], -.4)
        self.assertAlmostEqual(comparison[0]['delta_focus_ligand_rmsd_A'], -.8)
        self.assertEqual(comparison[1]['left_status'], 'failed')
        self.assertNotIn('delta_ca_rmsd_A', comparison[1])

    def test_partner_position_is_scored_after_primary_fit(self):
        task = {'id': 'complex', 'protein_asym': 'Z', 'partner_asym': 'R',
                'ligands': [{'asym': 'Q', 'ccd': 'ATP'}], 'focus_partner': True}
        with tempfile.TemporaryDirectory() as root:
            ref, pred = Path(root)/'ref.cif', Path(root)/'pred.cif'
            self.write_structure(ref, 9)
            self.write_structure(pred, 9, predicted=True)
            for path, predicted in ((ref, False), (pred, True)):
                cif = MMCIF2Dict(str(path))
                cif['_struct_asym.id'].append('R' if not predicted else 'B')
                cif['_struct_asym.entity_id'].append('8' if not predicted else '2')
                for key, value in {'entity_id': '8', 'type': 'polypeptide(L)',
                                   'nstd_monomer': 'no',
                                   'pdbx_seq_one_letter_code_can': 'A'*4}.items():
                    cif['_entity_poly.'+key].append(value)
                if predicted:
                    cif['_atom_site.label_entity_id'] = [
                        '3' if x == '2' else x for x in cif['_atom_site.label_entity_id']]
                positions = list(zip(*([float(x) for x in cif['_atom_site.Cartn_'+axis]]
                                       for axis in 'xyz')))
                primary = [p for p, name, seq in zip(
                    positions, cif['_atom_site.label_atom_id'], cif['_atom_site.label_seq_id'])
                    if name == 'CA' and seq in ('1', '3', '4', '5')]
                for i, xyz in enumerate(primary, 1):
                    for field, value in {'group_PDB': 'ATOM', 'id': str(len(cif['_atom_site.id'])+1),
                                         'type_symbol': 'C', 'label_atom_id': 'CA',
                                         'label_alt_id': '.', 'label_comp_id': 'ALA',
                                         'label_asym_id': 'B' if predicted else 'R',
                                         'label_entity_id': '2' if predicted else '8',
                                         'label_seq_id': str(i), 'auth_seq_id': str(i),
                                         'occupancy': '1', 'pdbx_PDB_model_num': '1',
                                         **{'Cartn_'+a: str(xyz[j] + (2. if predicted and a == 'x' else 0.) +
                                                               (1. if a == 'y' else 0.))
                                            for j, a in enumerate('xyz')}}.items():
                        cif['_atom_site.'+field].append(value)
                writer = MMCIFIO()
                writer.set_dict(cif)
                writer.save(str(path))
            result = score(task, ref, pred)
            self.assertEqual(result['partner']['n_aligned_ca'], 4)
            self.assertAlmostEqual(result['partner']['ca_rmsd_after_primary_fit'], 2.)
            self.assertGreater(result['partner']['interface_contacts_reference'], 0)


class RepeatTests(unittest.TestCase):
    def test_summary_csvs_keep_all_columns_and_missing_metrics(self):
        manifest = {'tasks': [{'id': 'ligand', 'pdb': '1ABC', 'models': ['v2']},
                              {'id': 'partner', 'pdb': '2XYZ', 'models': ['v1'],
                               'partner_asym': 'N'}]}
        runs = [{'task': 'ligand', 'model': 'v2', 'status': 'success',
                 'aligned_ca': 42, 'ca_rmsd_A': 1., 'focus_rmsd_A': 2.,
                 'interface_f1': .5, 'total_s': 20., 'gpu_hours': 20/3600},
                {'task': 'ligand', 'model': 'v2', 'status': 'failed',
                 'total_s': 10., 'gpu_hours': 10/3600},
                {'task': 'partner', 'model': 'v1', 'status': 'success',
                 'aligned_ca': 51, 'partner_ca_rmsd_A': 3.,
                 'interface_f1': .25, 'total_s': 40., 'gpu_hours': 40/3600}]
        performance, resources = aggregate(runs, manifest, 3.)
        with tempfile.TemporaryDirectory() as root:
            write_summary_csvs(performance, resources, Path(root))
            with (Path(root)/'performance.csv').open(encoding='utf-8-sig', newline='') as handle:
                perf_rows = list(csv.DictReader(handle))
            with (Path(root)/'resources.csv').open(encoding='utf-8-sig', newline='') as handle:
                resource_rows = list(csv.DictReader(handle))
        self.assertEqual(tuple(perf_rows[0]), PERFORMANCE_COLUMNS)
        self.assertEqual(tuple(resource_rows[0]), RESOURCE_COLUMNS)
        self.assertEqual(len(perf_rows), 2)
        self.assertEqual(perf_rows[0]['成功/计划'], '1/2')
        self.assertEqual(perf_rows[0]['纳米抗体位置 RMSD Å'], '—')
        self.assertEqual(perf_rows[1]['GDP/药物 RMSD Å'], '—')
        self.assertIn('3.00', perf_rows[1]['纳米抗体位置 RMSD Å'])
        self.assertEqual(resource_rows[0]['实测/计划'], '2/2')
        self.assertEqual(resource_rows[0]['总秒'], '15.00 ± 7.07')
        self.assertEqual(resource_rows[1]['进程费用估算 USD'], '0.033')

    def test_mismatched_input_hash_fails_even_for_failed_job(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            inputs = root/'inputs'
            outputs = root/'output'
            inputs.mkdir()
            run = outputs/'independent-v2'
            run.mkdir(parents=True)
            (inputs/'independent.json').write_text('[]')
            manifest = {'parameters': {'seeds': [17]},
                        'models': {'v2': {'name': 'model'}},
                        'tasks': [{'id': 'independent', 'pdb': '2ABC', 'models': ['v2']}]}
            (run/'metrics.json').write_text(json.dumps({
                'task': 'independent', 'model': {'name': 'model'},
                'parameters': {'seed': 17}, 'status': 'failed',
                'slurm_job_id': '42', 'input_sha256': 'bad'}))
            with self.assertRaisesRegex(ValueError, 'Input hash differs'):
                collect(manifest, outputs, input_root=inputs)

    def test_aggregate_keeps_failed_seed_in_denominator(self):
        manifest = {'tasks': [{'id': 'different', 'pdb': '2ABC', 'models': ['variant']}]}
        runs = [{'task': 'different', 'model': 'variant', 'seed': 4, 'status': 'success',
                 'ca_rmsd_A': 1., 'total_s': 30., 'gpu_hours': 30/3600},
                {'task': 'different', 'model': 'variant', 'seed': 7, 'status': 'success',
                 'ca_rmsd_A': 3., 'total_s': 60., 'gpu_hours': 60/3600},
                {'task': 'different', 'model': 'variant', 'seed': 9, 'status': 'failed',
                 'total_s': 15., 'gpu_hours': 15/3600}]
        performance, resources = aggregate(runs, manifest, 4.)
        self.assertEqual((performance[0]['success'], performance[0]['planned']), (2, 3))
        self.assertEqual(performance[0]['ca_rmsd_A']['mean'], 2.)
        self.assertAlmostEqual(performance[0]['ca_rmsd_A']['sd'], 2**.5)
        self.assertEqual(resources[0]['observed'], 3)
        self.assertEqual(resources[0]['total_s']['mean'], 35.)
        self.assertAlmostEqual(resources[0]['gpu_hours_total'], 105/3600)

    def test_run_directory_respects_legacy_first_seed(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            self.assertEqual(run_directory(root, 'target', 'v1', 11, 11),
                             root/'target-v1-seed11')
            legacy = root/'target-v1'
            legacy.mkdir()
            (legacy/'metrics.json').write_text('{}')
            self.assertEqual(run_directory(root, 'target', 'v1', 11, 11), legacy)
            self.assertEqual(run_directory(root, 'target', 'v1', 12, 11),
                             root/'target-v1-seed12')


class PathTests(unittest.TestCase):
    def test_artifact_and_run_overrides_use_distinct_absolute_roots(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            with patch.dict(os.environ, {'PROTENIX_ARTIFACTS_DIR': str(root/'storage'),
                                         'PROTENIX_RUN_DIR': str(root/'runs'/'trial')}, clear=False):
                self.assertEqual(artifact_root(), root/'storage')
                self.assertEqual(data_root(), root/'storage'/'data')
                self.assertEqual(run_root(), root/'runs'/'trial')
                self.assertEqual(output_root(), root/'runs'/'trial'/'output')
                self.assertEqual(logs_root(), root/'runs'/'trial'/'logs')

    def test_relative_artifact_and_run_overrides_fail(self):
        for key in ('PROTENIX_ARTIFACTS_DIR', 'PROTENIX_RUN_DIR'):
            with patch.dict(os.environ, {key: 'relative/path'}, clear=False):
                with self.assertRaisesRegex(ValueError, 'must be absolute'):
                    artifact_root() if key == 'PROTENIX_ARTIFACTS_DIR' else run_root()


if __name__ == '__main__':
    unittest.main()
