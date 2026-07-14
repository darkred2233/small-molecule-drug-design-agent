/**
 * RAG API
 */

import { apiClient } from './client';
import type { RagDocument, RagQueryRequest, RagQueryResponse } from '@/types/api';

export const ragApi = {
  // List documents
  listDocuments: (projectId: string) =>
    apiClient.get<RagDocument[]>(`/projects/${projectId}/rag/documents`),

  // Query RAG
  query: (projectId: string, data: RagQueryRequest) =>
    apiClient.post<RagQueryResponse>(`/projects/${projectId}/rag/query`, data),

  // Build RAG index
  build: (projectId: string, rebuild = false) =>
    apiClient.post(`/projects/${projectId}/rag/build`, { rebuild }),

  // Crawl URL
  crawl: (projectId: string, url: string) =>
    apiClient.post(`/projects/${projectId}/rag/crawl`, { urls: [url] }),
};
