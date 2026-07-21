import { api } from '@/api/client';
import type { EvidenceLink, ProjectResource, RagDocument, TargetLigand, UploadedFile } from '@/types/workbench';

export const dataApi = {
  files: (projectId: string) => api.get<UploadedFile[]>(`/projects/${projectId}/files`),
  upload: (projectId: string, file: File, onProgress?: (progress: number) => void) => api.upload<UploadedFile>(`/projects/${projectId}/files`, file, onProgress),
  ingest: (projectId: string) => api.post<Record<string, unknown>>(`/projects/${projectId}/ingest`, {}),
  resources: (projectId: string) => api.get<ProjectResource[]>(`/projects/${projectId}/resources`),
  ligands: (projectId: string) => api.get<TargetLigand[]>(`/projects/${projectId}/resources/ligands`),
  collectTargetPack: (projectId: string) => api.post<Record<string, unknown>>(`/projects/${projectId}/resources/collect-target-pack`, {}),
  documents: (projectId: string) => api.get<RagDocument[]>(`/projects/${projectId}/rag/documents`),
  evidence: (projectId: string) => api.get<EvidenceLink[]>(`/projects/${projectId}/evidence-links`),
};
