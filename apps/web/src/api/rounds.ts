import { api } from '@/api/client';
import type { AdmetResult, CampaignRun, DockingResult, Molecule, ProjectRound, Ranking, RoundSummary, StrategyDraft, SynthesisRoute } from '@/types/workbench';

const base = (projectId: string, roundId?: string) => `/projects/${projectId}/rounds${roundId ? `/${roundId}` : ''}`;

export const roundsApi = {
  list: (projectId: string) => api.get<ProjectRound[]>(base(projectId)),
  create: (projectId: string, body: { round_number: number; parent_round_id?: string; user_conditions_json?: Record<string, unknown> }) => api.post<ProjectRound>(base(projectId), body),
  get: (projectId: string, roundId: string) => api.get<ProjectRound>(base(projectId, roundId)),
  update: (projectId: string, roundId: string, body: Record<string, unknown>) => api.put<ProjectRound>(base(projectId, roundId), body),
  start: (projectId: string, roundId: string, body?: Record<string, unknown>) => api.post<Record<string, unknown>>(`${base(projectId, roundId)}/start`, body),
  campaigns: (projectId: string, roundId: string) => api.get<CampaignRun[]>(`${base(projectId, roundId)}/campaigns`),
  molecules: (projectId: string, roundId: string) => api.get<Molecule[]>(`${base(projectId, roundId)}/molecules`),
  rankings: (projectId: string, roundId: string) => api.get<Ranking[]>(`${base(projectId, roundId)}/rankings`),
  docking: (projectId: string, roundId: string) => api.get<DockingResult[]>(`${base(projectId, roundId)}/docking-results`),
  admet: (projectId: string, roundId: string) => api.get<AdmetResult[]>(`${base(projectId, roundId)}/admet-results`),
  synthesis: (projectId: string, roundId: string) => api.get<SynthesisRoute[]>(`${base(projectId, roundId)}/synthesis-routes`),
  summary: (projectId: string, roundId: string) => api.get<RoundSummary>(`${base(projectId, roundId)}/summary`),
  report: (projectId: string, roundId: string) => api.get<Record<string, unknown>>(`${base(projectId, roundId)}/report`),
  draftStrategy: (projectId: string, roundId: string, body: { user_message?: string; user_overrides?: Record<string, unknown> }) => api.post<StrategyDraft>(`${base(projectId, roundId)}/strategy/draft`, body),
  strategy: (projectId: string, roundId: string) => api.get<StrategyDraft>(`${base(projectId, roundId)}/strategy`),
  reviseStrategy: (projectId: string, roundId: string, body: { user_message: string; user_overrides?: Record<string, unknown> }) => api.post<StrategyDraft>(`${base(projectId, roundId)}/strategy/revise`, body),
  confirmStrategy: (projectId: string, roundId: string, body: { confirmed: boolean; user_modifications?: Record<string, unknown> }) => api.post<{ round_id: string; status: string; message: string }>(`${base(projectId, roundId)}/strategy/confirm`, body),
  critique: (projectId: string, roundId: string, moleculeId: string) => api.post<Record<string, unknown>>(`${base(projectId, roundId)}/molecules/${moleculeId}/critique`, {}),
};
