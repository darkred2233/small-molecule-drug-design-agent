import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, FolderKanban, Plus, Trash2 } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { projectsApi } from '@/api/projects';
import { EmptyState } from '@/components/EmptyState';
import { StatusBadge } from '@/components/StatusBadge';
import { formatDate } from '@/lib/format';
import type { Project } from '@/types/workbench';

type ProjectActionsProps = {
  project: Project;
  isRemoving: boolean;
  onOpen: () => void;
  onRemove: () => void;
};

function ProjectActions({ project, isRemoving, onOpen, onRemove }: ProjectActionsProps) {
  return <div className="row project-actions">
    <button className="button" onClick={onOpen}>进入 <ArrowRight size={15} /></button>
    <button className="button button-danger icon-button" title="删除项目及运行记录" aria-label={`删除 ${project.name}`} onClick={onRemove} disabled={isRemoving}>
      <Trash2 size={15} />
    </button>
  </div>;
}

export function ProjectsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: projects = [], isLoading, error } = useQuery<Project[], Error>({ queryKey: ['projects'], queryFn: projectsApi.list });
  const [removing, setRemoving] = useState<string | null>(null);
  const removeProject = useMutation<{ message: string }, Error, string>({
    mutationFn: (projectId: string) => projectsApi.remove(projectId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['projects'] }); setRemoving(null); },
  });

  const remove = (projectId: string, name: string) => {
    if (window.confirm(`确认删除项目“${name}”及其全部运行记录吗？此操作不会影响全局分子数据库。`)) {
      removeProject.mutate(projectId);
    }
  };

  const actionsFor = (project: Project) => <ProjectActions
    project={project}
    isRemoving={removeProject.isPending && removing === project.project_id}
    onOpen={() => navigate(`/projects/${project.project_id}/overview`)}
    onRemove={() => { setRemoving(project.project_id); remove(project.project_id, project.name); }}
  />;

  return <main className="page projects-page" style={{ padding: '42px 28px' }}>
    <div className="page-heading">
      <div>
        <p className="eyebrow">小分子药物设计</p>
        <h1>项目工作台</h1>
        <p className="subtle">按项目保留靶点、数据、轮次策略、生成结果和中文报告。</p>
      </div>
      <Link to="/projects/new" className="button button-primary"><Plus size={16} />新建项目</Link>
    </div>
    {isLoading && <div className="empty-state">正在载入项目…</div>}
    {error && <div className="notice notice-danger">{error.message || '无法载入项目。'}</div>}
    {!isLoading && !error && projects.length === 0 && <div className="panel"><EmptyState icon={FolderKanban} title="还没有设计项目" detail="先选择内置靶点或创建自定义靶点项目，再导入 Seed 和资料。" action={<Link to="/projects/new" className="button button-primary"><Plus size={16} />创建首个项目</Link>} /></div>}
    {projects.length > 0 && <>
      <div className="panel table-scroll projects-table">
        <table className="data-table">
          <thead><tr><th>项目</th><th>靶点</th><th>设计目标</th><th>状态</th><th>创建时间</th><th aria-label="操作" /></tr></thead>
          <tbody>{projects.map((project) => <tr key={project.project_id}>
            <td><strong>{project.name}</strong><div className="mono subtle project-id">{project.project_id}</div></td>
            <td>{project.target_name || project.target_id || '未指定'}</td>
            <td className="project-objective">{project.objective || '尚未设定'}</td>
            <td><StatusBadge status={project.status} /></td>
            <td>{formatDate(project.created_at)}</td>
            <td>{actionsFor(project)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="projects-cards">
        {projects.map((project) => <article key={project.project_id} className="project-card">
          <div className="project-card-header">
            <div><strong>{project.name}</strong><div className="mono subtle project-id">{project.project_id}</div></div>
            <StatusBadge status={project.status} />
          </div>
          <dl className="project-card-details">
            <div><dt>靶点</dt><dd>{project.target_name || project.target_id || '未指定'}</dd></div>
            <div><dt>设计目标</dt><dd>{project.objective || '尚未设定'}</dd></div>
            <div><dt>创建时间</dt><dd>{formatDate(project.created_at)}</dd></div>
          </dl>
          {actionsFor(project)}
        </article>)}
      </div>
    </>}
  </main>;
}
