/**
 * Project Sidebar Component
 *
 * Left sidebar with project list and navigation
 */

import { useState, type MouseEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { projectsApi } from '@/api';
import { useWorkspaceStore } from '@/state/workspaceStore';
import { Plus, Folder, Settings, Activity, Dna, Loader2, Trash2 } from 'lucide-react';
import { cn, getStatusColor, formatDate } from '@/utils/helpers';
import type { Project } from '@/types/api';

interface ProjectSidebarProps {
  onCreateProject?: () => void;
}

export default function ProjectSidebar({ onCreateProject }: ProjectSidebarProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { currentProject, setCurrentProject } = useWorkspaceStore();
  const [showSettings, setShowSettings] = useState(false);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);

  // Load projects
  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
  });

  const deleteProjectMutation = useMutation({
    mutationFn: projectsApi.delete,
    onSuccess: (_data, projectId) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.removeQueries({ queryKey: ['project', projectId] });
      queryClient.removeQueries({ queryKey: ['project-status', projectId] });

      if (currentProject?.project_id === projectId) {
        setCurrentProject(null);
        navigate('/workspace', { replace: true });
      }
    },
    onSettled: () => {
      setDeletingProjectId(null);
    },
  });

  const handleDeleteProject = (
    event: MouseEvent<HTMLButtonElement>,
    project: Project
  ) => {
    event.preventDefault();
    event.stopPropagation();

    if (deleteProjectMutation.isPending) return;

    const confirmed = window.confirm(
      `确定删除项目「${project.name}」吗？该操作会删除该项目的分子、运行记录和报告，无法撤销。`
    );

    if (!confirmed) return;

    setDeletingProjectId(project.project_id);
    deleteProjectMutation.mutate(project.project_id);
  };

  return (
    <div className="flex h-full flex-col bg-white/90">
      {/* Header */}
      <div className="border-b border-cyan-100 p-4">
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-600 text-white shadow-sm shadow-cyan-900/20">
            <Dna className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-slate-950">MedAgent</div>
            <div className="text-xs text-cyan-700">小分子药物设计智能体</div>
          </div>
        </div>
        <button
          onClick={onCreateProject}
          className="primary-action flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" />
          新建项目
        </button>
      </div>

      {/* Project List */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-4 text-center text-sm text-slate-500">加载中...</div>
        ) : projects && projects.length > 0 ? (
          <div className="p-2 space-y-1">
            {projects.map((project) => (
              <div key={project.project_id} className="group relative">
                <Link
                  to={`/workspace/${project.project_id}`}
                  className={cn(
                    'block rounded-lg border border-transparent p-3 pr-11 transition-colors hover:border-cyan-100 hover:bg-cyan-50/70',
                    currentProject?.project_id === project.project_id && 'border-cyan-200 bg-cyan-50 shadow-sm shadow-cyan-950/5'
                  )}
                >
                  <div className="flex items-start gap-3">
                    <Folder className="mt-1 h-4 w-4 flex-shrink-0 text-cyan-600" />
                    <div className="flex-1 min-w-0">
                      <div className="truncate text-sm font-medium text-slate-900">{project.name}</div>
                      {project.target_id && (
                        <div className="mt-0.5 text-xs text-cyan-700">{project.target_id}</div>
                      )}
                      <div className="flex items-center gap-2 mt-1">
                        <span className={cn('rounded px-2 py-0.5 text-xs', getStatusColor(project.status))}>
                          {project.status}
                        </span>
                        <span className="text-xs text-slate-400">{formatDate(project.updated_at || project.created_at)}</span>
                      </div>
                    </div>
                  </div>
                </Link>
                <button
                  type="button"
                  title="删除项目"
                  aria-label={`删除项目 ${project.name}`}
                  disabled={deleteProjectMutation.isPending}
                  onClick={(event) => handleDeleteProject(event, project)}
                  className={cn(
                    'absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded-md border border-transparent text-slate-400 opacity-0 transition-all',
                    'hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-rose-200',
                    'disabled:pointer-events-none disabled:opacity-60 group-hover:opacity-100',
                    currentProject?.project_id === project.project_id && 'opacity-100'
                  )}
                >
                  {deletingProjectId === project.project_id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-4 text-center text-sm text-slate-500">
            <p>暂无项目</p>
            <p className="text-xs mt-1">点击上方按钮创建新项目</p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="space-y-2 border-t border-cyan-100 p-4">
        <Link
          to="/tools/status"
          className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 transition-colors hover:bg-cyan-50 hover:text-cyan-800"
        >
          <Activity className="w-4 h-4" />
          工具状态
        </Link>
        <button
          onClick={() => setShowSettings(!showSettings)}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 transition-colors hover:bg-cyan-50 hover:text-cyan-800"
        >
          <Settings className="w-4 h-4" />
          设置
        </button>
      </div>
    </div>
  );
}
