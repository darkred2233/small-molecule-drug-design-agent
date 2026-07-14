import { describe, expect, it } from 'vitest';
import {
  DEFAULT_PHYSCHEM_CONSTRAINTS,
  buildDesignPrompt,
  getDefaultPriorityIdsForGoal,
} from './designGuidance';

describe('design guidance prompt builder', () => {
  it('builds a guided drug-design prompt from selected options', () => {
    const prompt = buildDesignPrompt({
      project: {
        project_id: 'PRJ-1',
        name: 'EGFR 优化',
        target_id: 'EGFR',
        objective: '降低 hERG 风险并提高溶解度',
        status: 'created',
        created_at: '2026-07-12T00:00:00Z',
      },
      target: {
        target_id: 'EGFR',
        name: 'Epidermal growth factor receptor',
        aliases: ['ERBB1'],
        uniprot_id: 'P00533',
        species: 'human',
        pdb_ids: ['1M17'],
        summary: 'Kinase target',
        pocket_summary: 'ATP hinge pocket',
        binding_sites: [],
        sar_rules: [],
        admet_risks: [],
        seed_ligand_count: 0,
        drugs: [],
      },
      goalId: 'lead_optimization',
      strategyId: 'crem',
      priorityIds: ['herg', 'solubility', 'synthesis'],
      constraints: DEFAULT_PHYSCHEM_CONSTRAINTS,
      selectedSeeds: [{ name: 'Gefitinib', smiles: 'COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1O' }],
      customSeedSmiles: 'CCO',
    });

    expect(prompt).toContain('Lead 优化');
    expect(prompt).toContain('Epidermal growth factor receptor (EGFR)');
    expect(prompt).toContain('降低 hERG');
    expect(prompt).toContain('CReM');
    expect(prompt).toContain('Gefitinib');
    expect(prompt).toContain('逆合成');
  });

  it('chooses useful defaults for each design goal', () => {
    expect(getDefaultPriorityIdsForGoal('hit_finding')).toContain('novelty');
    expect(getDefaultPriorityIdsForGoal('scaffold_hopping')).toContain('scaffold');
    expect(getDefaultPriorityIdsForGoal('selectivity')).toContain('selectivity');
    expect(getDefaultPriorityIdsForGoal('lead_optimization')).toContain('herg');
  });
});
