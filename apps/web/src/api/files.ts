/**
 * File Upload API
 */

import { apiClient } from './client';
import type { UploadedFile } from '@/types/api';

export const filesApi = {
  // List project files
  list: (projectId: string) =>
    apiClient.get<UploadedFile[]>(`/projects/${projectId}/files`),

  // Upload file
  upload: (projectId: string, file: File, onProgress?: (progress: number) => void) =>
    apiClient.uploadFile(`/projects/${projectId}/files`, file, onProgress),

  // Parse file
  parse: (projectId: string, fileId: string) =>
    apiClient.post(`/projects/${projectId}/files/${fileId}/parse`, {}),

  // Ingest all pending files
  ingest: (projectId: string) =>
    apiClient.post(`/projects/${projectId}/ingest`, {}),
};
