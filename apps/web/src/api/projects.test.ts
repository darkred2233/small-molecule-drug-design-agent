import { describe, expect, it } from 'vitest';
import { normalizeBuiltinTarget } from './projects';

describe('project API target normalization', () => {
  it('fills fields omitted by older builtin target payloads', () => {
    const target = normalizeBuiltinTarget({
      target_id: 'TGT-LEGACY',
      name: 'Legacy kinase',
      summary: 'Older backend response',
      drugs: [
        { drug_name: 'Seed A', smiles: null },
        { drug_name: 'Seed B', canonical_smiles: 'CCO' },
      ],
    });

    expect(target.aliases).toEqual([]);
    expect(target.pdb_ids).toEqual([]);
    expect(target.binding_sites).toEqual([]);
    expect(target.sar_rules).toEqual([]);
    expect(target.admet_risks).toEqual([]);
    expect(target.seed_ligand_count).toBe(1);
    expect(target.drugs[0]).toMatchObject({
      drug_name: 'Seed A',
      smiles: null,
      canonical_smiles: null,
    });
  });
});
