import { api } from '@/api/client';
import type { ToolStatus } from '@/types/workbench';

export const toolsApi = { status: () => api.get<ToolStatus[]>('/tools/status') };
