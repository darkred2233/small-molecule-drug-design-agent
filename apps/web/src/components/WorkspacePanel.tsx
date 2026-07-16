/**
 * Updated Workspace Panel with new components
 */

import { useWorkspaceStore } from '@/state/workspaceStore';
import { useParams } from 'react-router-dom';
import { FileText, Beaker, BookOpen, ShieldX } from 'lucide-react';
import { cn } from '@/utils/helpers';
import { useQuery } from '@tanstack/react-query';
import { projectsApi } from '@/api';
import AgentTimeline from './AgentTimeline';
import MoleculeTable from './MoleculeTable';
import FileDropzone from './FileDropzone';
import FailedMoleculeLibrary from './FailedMoleculeLibrary';

export default function WorkspacePanel() {
  const { projectId } = useParams();
  const { rightPanelTab, setRightPanelTab } = useWorkspaceStore();

  const tabs = [
    { id: 'overview', label: '概览', icon: FileText },
    { id: 'molecules', label: '分子', icon: Beaker },
    { id: 'failed', label: '失败库', icon: ShieldX },
    { id: 'evidence', label: '证据', icon: BookOpen },
  ] as const;

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-slate-500">
        <p>选择一个项目以查看详情</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Tabs */}
      <div className="border-b border-cyan-100 bg-white/95">
        <div className="flex">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setRightPanelTab(tab.id)}
                className={cn(
                  'flex-1 flex items-center justify-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                  rightPanelTab === tab.id
                    ? 'border-cyan-600 bg-cyan-50 text-cyan-700'
                    : 'border-transparent text-slate-600 hover:bg-cyan-50/60 hover:text-cyan-800'
                )}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {rightPanelTab === 'overview' && <OverviewTab projectId={projectId} />}
        {rightPanelTab === 'molecules' && <MoleculesTab />}
        {rightPanelTab === 'failed' && <FailedTab />}
        {rightPanelTab === 'evidence' && <EvidenceTab />}
      </div>
    </div>
  );
}

function OverviewTab({ projectId }: { projectId: string }) {
  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId),
  });

  const { data: status } = useQuery({
    queryKey: ['project-status', projectId],
    queryFn: () => projectsApi.getStatus(projectId),
    refetchInterval: (query) =>
      query.state.data?.status === 'pipeline_running' ? 2000 : false,
  });

  return (
    <div className="space-y-6">
      <div className="science-card">
        <h3 className="mb-3 text-sm font-semibold text-slate-950">项目信息</h3>
        <div className="space-y-2 text-sm">
          <div>
            <span className="text-slate-500">项目名称:</span>
            <span className="ml-2 font-medium text-slate-900">{project?.name}</span>
          </div>
          <div>
            <span className="text-slate-500">靶点:</span>
            <span className="ml-2 font-medium text-cyan-700">{project?.target_id || '未设置'}</span>
          </div>
          {project?.objective && (
            <div>
              <span className="text-slate-500">目标:</span>
              <p className="mt-1 text-slate-700">{project.objective}</p>
            </div>
          )}
        </div>
      </div>

      {/* Agent Timeline */}
      {status && (
        <div>
          <h3 className="mb-3 text-sm font-semibold text-slate-950">执行进度</h3>
          <div className="science-card">
            <AgentTimeline projectId={projectId} />
          </div>
        </div>
      )}
    </div>
  );
}

function MoleculesTab() {
  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold text-slate-950">候选分子</h3>
      <MoleculeTable />
    </div>
  );
}

function FailedTab() {
  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold text-slate-950">失败分子库</h3>
      <FailedMoleculeLibrary />
    </div>
  );
}

function EvidenceTab() {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="mb-3 text-sm font-semibold text-slate-950">文件上传</h3>
        <FileDropzone />
      </div>
    </div>
  );
}
