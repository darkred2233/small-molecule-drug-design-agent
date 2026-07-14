/**
 * Workspace Store
 *
 * Global state management using Zustand
 */

import { create } from 'zustand';
import type { Project } from '@/types/api';

type RightPanelTab = 'design' | 'overview' | 'molecules' | 'failed' | 'evidence' | 'advisor';

interface WorkspaceState {
  // Current project
  currentProject: Project | null;
  setCurrentProject: (project: Project | null) => void;

  // Selected molecule
  selectedMoleculeId: string | null;
  setSelectedMoleculeId: (id: string | null) => void;

  // Right panel state
  rightPanelOpen: boolean;
  rightPanelTab: RightPanelTab;
  setRightPanelOpen: (open: boolean) => void;
  setRightPanelTab: (tab: RightPanelTab) => void;

  // Chat composer draft injected from guided panels
  composerDraft: { content: string; version: number } | null;
  setComposerDraft: (content: string) => void;
  clearComposerDraft: () => void;

  // Left sidebar state
  leftSidebarOpen: boolean;
  setLeftSidebarOpen: (open: boolean) => void;

  // Evidence drawer
  evidenceDrawerOpen: boolean;
  evidenceDrawerChunkId: string | null;
  openEvidenceDrawer: (chunkId: string) => void;
  closeEvidenceDrawer: () => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  // Current project
  currentProject: null,
  setCurrentProject: (project) => set({ currentProject: project }),

  // Selected molecule
  selectedMoleculeId: null,
  setSelectedMoleculeId: (id) => set({ selectedMoleculeId: id }),

  // Right panel
  rightPanelOpen: true,
  rightPanelTab: 'design',
  setRightPanelOpen: (open) => set({ rightPanelOpen: open }),
  setRightPanelTab: (tab) => set({ rightPanelTab: tab }),

  // Chat composer
  composerDraft: null,
  setComposerDraft: (content) =>
    set((state) => ({
      composerDraft: {
        content,
        version: (state.composerDraft?.version ?? 0) + 1,
      },
    })),
  clearComposerDraft: () => set({ composerDraft: null }),

  // Left sidebar
  leftSidebarOpen: true,
  setLeftSidebarOpen: (open) => set({ leftSidebarOpen: open }),

  // Evidence drawer
  evidenceDrawerOpen: false,
  evidenceDrawerChunkId: null,
  openEvidenceDrawer: (chunkId) =>
    set({ evidenceDrawerOpen: true, evidenceDrawerChunkId: chunkId }),
  closeEvidenceDrawer: () =>
    set({ evidenceDrawerOpen: false, evidenceDrawerChunkId: null }),
}));
