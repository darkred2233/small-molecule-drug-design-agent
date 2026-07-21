import { api } from '@/api/client';
import type { BuiltinTarget, CreateProjectInput, Project } from '@/types/workbench';

export const projectsApi = {
  list: () => api.get<Project[]>('/projects'),
  get: (projectId: string) => api.get<Project>(`/projects/${projectId}`),
  create: (input: CreateProjectInput) => api.post<Project>('/projects', input),
  remove: (projectId: string) => api.delete<{ message: string }>(`/projects/${projectId}`),
  builtinTargets: () => api.get<BuiltinTarget[]>('/builtin-targets'),
  stats: (projectId: string) => api.get<Record<string, unknown>>(`/projects/${projectId}/stats`),
};
