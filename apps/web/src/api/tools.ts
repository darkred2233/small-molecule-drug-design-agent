/**
 * Tools API
 */

import { apiClient } from './client';
import type { ToolStatus } from '@/types/api';

export const toolsApi = {
  // Get all tools status
  getStatus: () =>
    apiClient.get<ToolStatus[]>('/tools/status'),

  // Check specific tool
  checkTool: (toolName: string) =>
    apiClient.get<ToolStatus>(`/tools/${toolName}/status`),
};
