import { api } from '@/api/client';
import type { DockingResult, Molecule, MoleculeNarrative, MoleculeProperties } from '@/types/workbench';

export const moleculesApi = {
  list: (projectId: string) => api.get<Molecule[]>(`/projects/${projectId}/molecules`),
  get: (projectId: string, moleculeId: string) => api.get<Molecule>(`/projects/${projectId}/molecules/${moleculeId}`),
  properties: (projectId: string, moleculeId: string) => api.get<MoleculeProperties>(`/projects/${projectId}/molecules/${moleculeId}/properties`),
  narrative: (projectId: string, moleculeId: string) => api.get<MoleculeNarrative>(`/projects/${projectId}/molecules/${moleculeId}/narrative`),
  docking: (projectId: string, roundId?: string) => api.get<DockingResult[]>(`/projects/${projectId}/docking-results`, roundId ? { round_id: roundId } : undefined),
  importSeeds: (projectId: string) => api.post<Record<string, unknown>>(`/projects/${projectId}/molecules/import-seeds`, {}),
};
