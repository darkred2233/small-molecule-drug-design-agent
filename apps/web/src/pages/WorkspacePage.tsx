/**
 * Updated Workspace Page with Evidence Drawer
 */

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useWorkspaceStore } from '@/state/workspaceStore';
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { projectsApi } from '@/api';
import ProjectSidebar from '@/components/ProjectSidebar';
import ChatPanel from '@/components/ChatPanel';
import WorkspacePanel from '@/components/WorkspacePanel';
import CreateProjectModal from '@/components/CreateProjectModal';

export default function WorkspacePage() {
  const { projectId } = useParams();
  const { setCurrentProject, leftSidebarOpen } = useWorkspaceStore();
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Load current project
  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId,
  });

  useEffect(() => {
    if (project) {
      setCurrentProject(project);
    }
  }, [project, setCurrentProject]);

  return (
    <>
      <div className="app-shell flex h-screen overflow-hidden">
        {/* Left Sidebar - Projects */}
        {leftSidebarOpen && (
          <div className="hidden w-72 border-r border-cyan-100/80 bg-white/90 backdrop-blur lg:block">
            <ProjectSidebar onCreateProject={() => setShowCreateModal(true)} />
          </div>
        )}

        {/* Center - Chat Panel */}
        <div className="flex-1 flex flex-col min-w-0">
          <ChatPanel />
        </div>

        {/* Right Panel - Workspace */}
        <div className="hidden w-[32rem] min-w-[28rem] overflow-y-auto border-l border-cyan-100/80 bg-white/90 backdrop-blur xl:block">
          <WorkspacePanel />
        </div>
      </div>

      {/* Create Project Modal */}
      <CreateProjectModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
      />
    </>
  );
}
