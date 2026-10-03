"""Generate coordinate-free inputs from explicitly selected mmCIF entities.

Scope: one unmodified protein chain and any number of single-CCD ligands/ions.
Selections are manifest data, never inferred from distances or target names.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from benchmark.paths import data_root


def rows(cif, category):
    columns = {k.split('.', 1)[1]: v for k, v in cif.items() if k.startswith(category + '.')}
    if not columns:
        return []
    if len({len(v) for v in columns.values()}) != 1:
        raise ValueError(f"Inconsistent {category} columns")
    return [dict(zip(columns, values)) for values in zip(*columns.values())]


def fetch(url, path):
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(url, timeout=120) as response:
            payload = response.read()
        # Parse before accepting a downloaded resource as a cache entry.
        temporary = path.with_suffix('.download')
        temporary.write_bytes(payload)
        MMCIF2Dict(str(temporary))
        temporary.replace(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protein_sequence(cif, asym, asym_entities):
    if asym not in asym_entities:
        raise ValueError(f'Unknown protein asym {asym}')
    polymer = [r for r in rows(cif, '_entity_poly')
               if r['entity_id'] == asym_entities[asym]]
    if len(polymer) != 1 or polymer[0]['type'] != 'polypeptide(L)':
        raise ValueError(f'Expected one selected L-polypeptide: {asym}')
    poly = polymer[0]
    sequence = ''.join(poly['pdbx_seq_one_letter_code_can'].split())
    if poly['nstd_monomer'] != 'no' or set(sequence) - set('ACDEFGHIKLMNPQRSTVWY'):
        raise ValueError(f'Modified/unknown protein monomers require explicit input support: {asym}')
    return sequence


def build_input(task, cif):
    asym_entities = {r['id']: r['entity_id'] for r in rows(cif, '_struct_asym')}
    primary = task['protein_asym']
    proteins = [primary] + ([task['partner_asym']] if task.get('partner_asym') else [])
    if len(proteins) != len(set(proteins)):
        raise ValueError('Protein chains must be distinct')
    mapping = {asym: i for i, asym in enumerate(proteins, 1)}
    seqs = [{'proteinChain': {'sequence': protein_sequence(cif, asym, asym_entities),
                             'count': 1, 'id': ['A' if len(proteins) == 1 else f'P{i}']}}
            for i, asym in enumerate(proteins, 1)]
    nonpolys = {r['entity_id']: r['comp_id'] for r in rows(cif, '_pdbx_entity_nonpoly')}
    for i, ligand in enumerate(task['ligands'], len(proteins)+1):
        asym, ccd = ligand['asym'], ligand['ccd']
        if asym in mapping or asym not in asym_entities or nonpolys.get(asym_entities[asym]) != ccd:
            raise ValueError(f'Duplicate or mismatched ligand {ligand}')
        mapping[asym] = i
        seqs.append({'ligand': {'ligand': f'CCD_{ccd}', 'count': 1, 'id': [f'L{i}']}})
    bonds = []
    for row in rows(cif, '_struct_conn'):
        if row['conn_type_id'] != 'covale':
            continue
        partners = [row[f'ptnr{j}_label_asym_id'] for j in (1, 2)]
        if not any(p in mapping for p in partners):
            continue
        if not all(p in mapping for p in partners):
            raise ValueError('Selected entity has covalent connection to an omitted entity')
        bond = {}
        for j, asym in enumerate(partners, 1):
            if row[f'ptnr{j}_symmetry'] != '1_555':
                raise ValueError('Symmetry-related covalent bonds are unsupported')
            position = row[f'ptnr{j}_label_seq_id']
            bond.update({f'entity{j}': mapping[asym], f'copy{j}': 1,
                         f'position{j}': int(position) if position not in ('.', '?') else 1,
                         f'atom{j}': row[f'ptnr{j}_label_atom_id']})
        bonds.append(bond)
    return {'name': task['id'], 'sequences': seqs, 'covalent_bonds': bonds}


def prepare(manifest, destination, reference_root=None, ccd_root=None):
    destination = Path(destination)
    reference_root = data_root() / 'references' if reference_root is None else Path(reference_root)
    ccd_root = data_root() / 'ccd' if ccd_root is None else Path(ccd_root)
    destination.mkdir(parents=True, exist_ok=True)
    audit = []
    ids = [task['id'] for task in manifest['tasks']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate task IDs')
    for task in manifest['tasks']:
        if not task['id'].replace('_', '').isalnum():
            raise ValueError('Task IDs must be alphanumeric with optional underscores')
        path = Path(reference_root) / (task['pdb'] + '.cif')
        url = f"https://files.rcsb.org/download/{task['pdb']}.cif"
        digest = fetch(url, path)
        cif = MMCIF2Dict(str(path))
        item = build_input(task, cif)
        chemistry = []
        for ligand in task['ligands']:
            ccd = ligand['ccd']
            cpath = Path(ccd_root) / f'{ccd}.cif'
            curl = f'https://files.rcsb.org/ligands/download/{ccd}.cif'
            chash = fetch(curl, cpath)
            chem = MMCIF2Dict(str(cpath))
            chemistry.append({'ccd': ccd, 'url': curl, 'sha256': chash,
                              'name': chem['_chem_comp.name'][0],
                              'descriptors': rows(chem, '_pdbx_chem_comp_descriptor')})
        release = min(cif['_pdbx_audit_revision_history.revision_date'])
        (destination / f"{task['id']}.json").write_text(json.dumps([item], indent=2) + '\n')
        audit.append({**task, 'reference_url': url, 'reference_sha256': digest,
                      'release_date': release, 'sequence': item['sequences'][0]['proteinChain']['sequence'],
                      'protein_sequences': [x['proteinChain']['sequence'] for x in item['sequences']
                                            if 'proteinChain' in x],
                      'covalent_bonds': item['covalent_bonds'], 'chemistry': chemistry,
                      'split': {m: 'post_cutoff' if release > manifest['models'][m]['training_cutoff']
                                else 'retrospective' for m in task['models']}})
    (destination / 'audit.json').write_text(json.dumps(audit, indent=2) + '\n')
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', default='benchmark/tasks.json')
    parser.add_argument('--output', default=str(data_root() / 'inputs'))
    parser.add_argument('--reference-root', default=str(data_root() / 'references'))
    parser.add_argument('--ccd-root', default=str(data_root() / 'ccd'))
    args = parser.parse_args()
    prepare(json.loads(Path(args.manifest).read_text()), args.output,
            args.reference_root, args.ccd_root)
