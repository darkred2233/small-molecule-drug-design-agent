/**
 * Molecules API
 */

import { apiClient } from './client';
import type {
  Molecule,
  MoleculeProperties,
  DecisionCard,
  RuleFilterSummary,
} from '@/types/api';

export const moleculesApi = {
  // List project molecules
  list: (projectId: string, status?: string) =>
    apiClient.get<Molecule[]>(`/projects/${projectId}/molecules`, { status }),

  // Get molecule by ID
  get: (projectId: string, moleculeId: string) =>
    apiClient.get<Molecule>(`/projects/${projectId}/molecules/${moleculeId}`),

  // Get molecule properties
  getProperties: (projectId: string, moleculeId: string) =>
    apiClient.get<MoleculeProperties>(`/projects/${projectId}/molecules/${moleculeId}/properties`),

  // Get molecule decision cards
  getDecisionCards: (projectId: string, moleculeId: string) =>
    apiClient.get<DecisionCard[]>(`/projects/${projectId}/molecules/${moleculeId}/decision-cards`),

  // Import seed ligands
  importSeeds: (projectId: string) =>
    apiClient.post(`/projects/${projectId}/molecules/import-seeds`, {}),

  // Validate molecules
  validate: (projectId: string) =>
    apiClient.post(`/projects/${projectId}/molecules/validate`, {}),

  // Filter molecules
  filter: (projectId: string) =>
    apiClient.post(`/projects/${projectId}/molecules/filter-rules`, {}),

  // List rule filter decisions for failure library
  getRuleFilterResults: (projectId: string) =>
    apiClient.get<RuleFilterSummary[]>(`/projects/${projectId}/rule-filter-results`),
};
