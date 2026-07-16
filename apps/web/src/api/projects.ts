/**
 * Project API
 */

import { apiClient } from './client';
import type {
  Project,
  CreateProjectRequest,
  BuiltinTarget,
  BuiltinDrug,
  PipelineStatus,
  RunPlan,
} from '@/types/api';

type RawBuiltinDrug = Partial<BuiltinDrug> | null | undefined;
type RawBuiltinTarget = Omit<Partial<BuiltinTarget>, 'drugs'> & {
  drugs?: RawBuiltinDrug[] | null;
};

export function normalizeBuiltinTarget(raw: RawBuiltinTarget | null | undefined): BuiltinTarget {
  const drugs = arrayOf<RawBuiltinDrug>(raw?.drugs).map(normalizeBuiltinDrug);
  const seedLigandCount =
    typeof raw?.seed_ligand_count === 'number' && Number.isFinite(raw.seed_ligand_count)
      ? raw.seed_ligand_count
      : drugs.filter((drug) => drug.smiles || drug.canonical_smiles || drug.isomeric_smiles).length;

  return {
    target_id: stringValue(raw?.target_id, 'UNKNOWN-TARGET'),
    name: stringValue(raw?.name, raw?.target_id ?? 'Unknown target'),
    aliases: stringArray(raw?.aliases),
    uniprot_id: nullableString(raw?.uniprot_id),
    species: nullableString(raw?.species),
    pdb_ids: stringArray(raw?.pdb_ids),
    summary: nullableString(raw?.summary),
    pocket_summary: nullableString(raw?.pocket_summary),
    binding_sites: arrayOf(raw?.binding_sites),
    sar_rules: arrayOf(raw?.sar_rules),
    admet_risks: arrayOf(raw?.admet_risks),
    seed_ligand_count: seedLigandCount,
    drugs,
  };
}

function normalizeBuiltinDrug(raw: RawBuiltinDrug): BuiltinDrug {
  return {
    drug_name: stringValue(raw?.drug_name, 'Unknown ligand'),
    drug_status: nullableString(raw?.drug_status),
    mechanism: nullableString(raw?.mechanism),
    indication: nullableString(raw?.indication),
    smiles: nullableString(raw?.smiles),
    canonical_smiles: nullableString(raw?.canonical_smiles),
    isomeric_smiles: nullableString(raw?.isomeric_smiles),
    inchi_key: nullableString(raw?.inchi_key),
    pubchem_cid: typeof raw?.pubchem_cid === 'number' ? raw.pubchem_cid : null,
    evidence_source: nullableString(raw?.evidence_source),
  };
}

function arrayOf<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value.filter(Boolean) as T[]) : [];
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

export const projectsApi = {
  // List all projects
  list: () => apiClient.get<Project[]>('/projects'),

  // Get project by ID
  get: (projectId: string) => apiClient.get<Project>(`/projects/${projectId}`),

  // Create new project
  create: (data: CreateProjectRequest) => apiClient.post<Project>('/projects', data),

  // Delete project
  delete: (projectId: string) =>
    apiClient.delete<{ message: string }>(`/projects/${projectId}`),

  // Get builtin targets
  getBuiltinTargets: () =>
    apiClient
      .get<RawBuiltinTarget[]>('/builtin-targets')
      .then((targets) => arrayOf<RawBuiltinTarget>(targets).map(normalizeBuiltinTarget)),

  // Get project status
  getStatus: (projectId: string) =>
    apiClient.get<PipelineStatus>(`/projects/${projectId}/status`),

  // Get current RunPlan
  getRunPlan: (projectId: string) =>
    apiClient.get<RunPlan>(`/projects/${projectId}/run-plan`),

  // Save current RunPlan draft
  saveRunPlan: (projectId: string, runPlan: RunPlan) =>
    apiClient.put<RunPlan>(`/projects/${projectId}/run-plan`, runPlan),

  // Run current RunPlan
  run: (projectId: string, mode: 'iterative', legacyGenerationConfig?: Record<string, any>) =>
    apiClient.post(`/projects/${projectId}/run`, {
      mode,
      generation_config: legacyGenerationConfig ?? {},
    }),
};
