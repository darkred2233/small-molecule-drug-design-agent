/**
 * Assessment API
 */

import { apiClient } from './client';
import type {
  CandidateAssessmentRunRequest,
  CandidateAssessmentRunResponse,
  Ranking,
  ReasoningTrace,
  AdvisorSuggestion,
  OptimizationConstraint,
  SynthesisRoute,
} from '@/types/api';

export const assessmentApi = {
  // Run candidate assessment
  runAssessment: (
    projectId: string,
    options: number | CandidateAssessmentRunRequest = {}
  ) => {
    const payload =
      typeof options === 'number'
        ? { max_molecules: options }
        : options;

    return apiClient.post<CandidateAssessmentRunResponse>(`/projects/${projectId}/candidate-assessment/run`, {
      assessment_mode: 'external',
      external_top_n: 10,
      ...payload,
    });
  },

  // Get rankings
  getRankings: (projectId: string) =>
    apiClient.get<Ranking[]>(`/projects/${projectId}/rankings`),

  // Get synthesis route assessments
  getSynthesisRoutes: (projectId: string) =>
    apiClient.get<SynthesisRoute[]>(`/projects/${projectId}/synthesis-routes`),

  // Generate rankings
  generateRankings: (projectId: string, topN = 50) =>
    apiClient.post(`/projects/${projectId}/rankings/generate`, { top_n: topN }),

  // Get reasoning traces
  getReasoningTraces: (projectId: string) =>
    apiClient.get<ReasoningTrace[]>(`/projects/${projectId}/reasoning-traces`),

  // Get decision cards
  getDecisionCards: (projectId: string) =>
    apiClient.post(`/projects/${projectId}/decision-cards/generate`, {}),

  // Get constraints
  getConstraints: (projectId: string) =>
    apiClient.get<OptimizationConstraint[]>(`/projects/${projectId}/constraints`),

  // Get advisor suggestions
  getAdvice: (projectId: string) =>
    apiClient.get<AdvisorSuggestion[]>(`/projects/${projectId}/advice`),

  // Apply advisor suggestions
  applyAdvice: (projectId: string) =>
    apiClient.post(`/projects/${projectId}/advisor/apply`, {}),
};
