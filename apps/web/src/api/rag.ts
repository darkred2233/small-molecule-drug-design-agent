/**
 * RAG API
 */

import { apiClient } from './client';
import type { RagDocument, RagQueryRequest, RagQueryResponse, RagChunkRead, EvidenceLink } from '@/types/api';

export const ragApi = {
  // List documents
  listDocuments: (projectId: string) =>
    apiClient.get<RagDocument[]>(`/projects/${projectId}/rag/documents`),

  // Get single evidence link
  getEvidenceLink: (projectId: string, evidenceId: string) =>
    apiClient.get<EvidenceLink>(
      `/projects/${encodeURIComponent(projectId)}/evidence-links/${encodeURIComponent(evidenceId)}`
    ),

  // Get single chunk detail
  getChunk: (projectId: string, chunkId: string) =>
    apiClient.get<RagChunkRead>(
      `/projects/${encodeURIComponent(projectId)}/rag/chunks/${encodeURIComponent(chunkId)}`
    ),

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
