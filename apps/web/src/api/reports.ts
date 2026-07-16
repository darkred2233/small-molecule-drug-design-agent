/**
 * Reports API
 */

import { API_BASE_URL, apiClient } from './client';
import type { ProjectReport } from '@/types/api';

export const reportsApi = {
  // Get project report
  get: (projectId: string) =>
    apiClient.get<ProjectReport>(`/projects/${projectId}/report`),

  // Generate project report (if separate from get)
  generate: (projectId: string) =>
    apiClient.post<ProjectReport>(`/projects/${projectId}/report`, {}),

  download: (projectId: string) =>
    apiClient.download(`/projects/${projectId}/report/download`),

  downloadUrl: (projectId: string) =>
    `${API_BASE_URL.replace(/\/$/, '')}/projects/${projectId}/report/download`,

  poseDownloadUrl: (projectId: string, moleculeId: string) =>
    `${API_BASE_URL.replace(/\/$/, '')}/projects/${encodeURIComponent(projectId)}/molecules/${encodeURIComponent(
      moleculeId
    )}/docking/pose`,
};
