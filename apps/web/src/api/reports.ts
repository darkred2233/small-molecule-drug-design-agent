import { api, apiUrl } from '@/api/client';
import type { ProjectReport } from '@/types/workbench';

export const reportsApi = {
  project: (projectId: string) => api.get<ProjectReport>(`/projects/${projectId}/report`),
  generate: (projectId: string) => api.post<ProjectReport>(`/projects/${projectId}/report`, {}),
  poseUrl: (projectId: string, moleculeId: string) => apiUrl(`/projects/${encodeURIComponent(projectId)}/molecules/${encodeURIComponent(moleculeId)}/docking/pose`),
  downloadUrl: (projectId: string) => apiUrl(`/projects/${encodeURIComponent(projectId)}/report/download`),
};
