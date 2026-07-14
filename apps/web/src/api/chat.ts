/**
 * Chat API
 */

import { apiClient } from './client';
import type { ChatRequest, ChatResponse, ChatMessage } from '@/types/api';

export const chatApi = {
  // Send message to project chat
  sendMessage: (projectId: string, data: ChatRequest) =>
    apiClient.post<ChatResponse>(`/projects/${projectId}/chat`, data),

  // Get project messages (when backend implements this)
  getMessages: (projectId: string) =>
    apiClient.get<ChatMessage[]>(`/projects/${projectId}/messages`),

  // Stream chat (when backend implements this)
  streamMessage: (projectId: string, message: string, onChunk: (chunk: string) => void) =>
    apiClient.stream(`/projects/${projectId}/chat/stream`, { message }, onChunk),
};
