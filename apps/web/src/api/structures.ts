import { api } from '@/api/client';
import type { BindingSite, ProjectStructure, StructureReadiness } from '@/types/workbench';

interface P2RankResponse {
  status: string;
  warnings: string[];
  binding_sites: BindingSite[];
}

interface StructurePreparation {
  structure_id: string;
  status: string;
  prepared_receptor_file: string | null;
  prepared_receptor_sha256: string | null;
  warnings: string[];
}

export const structuresApi = {
  list: (projectId: string) => api.get<ProjectStructure[]>(`/projects/${projectId}/structures`),
  importRcsb: (projectId: string, pdbId: string) => api.post<ProjectStructure>(`/projects/${projectId}/structures/import-rcsb`, { pdb_id: pdbId }),
  registerUpload: (projectId: string, sourceFileId: string) => api.post<ProjectStructure>(`/projects/${projectId}/structures/register-upload`, { source_file_id: sourceFileId }),
  activate: (projectId: string, structureId: string) => api.post<ProjectStructure>(`/projects/${projectId}/structures/${structureId}/activate`, {}),
  predictPockets: (projectId: string, structureId: string) => api.post<P2RankResponse>(`/projects/${projectId}/structures/${structureId}/p2rank`, {}),
  prepare: (projectId: string, structureId: string) => api.post<StructurePreparation>(`/projects/${projectId}/structures/${structureId}/prepare`, {}),
  bindingSites: (projectId: string) => api.get<BindingSite[]>(`/projects/${projectId}/binding-sites`),
  selectBindingSite: (projectId: string, bindingSiteId: string) => api.post<BindingSite>(`/projects/${projectId}/binding-sites/${bindingSiteId}/select`, {}),
  readiness: (projectId: string) => api.get<StructureReadiness>(`/projects/${projectId}/structure-readiness`),
};
