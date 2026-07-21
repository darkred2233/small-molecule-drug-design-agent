import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Beaker, Database, FlaskConical, LayoutDashboard, Plus, Workflow } from 'lucide-react';
import { Link, NavLink, Outlet, useLocation, useParams } from 'react-router-dom';
import { projectsApi, roundsApi } from '@/api';
import { AgentPanel } from '@/components/AgentPanel';
import { StatusBadge } from '@/components/StatusBadge';
import { statusLabel } from '@/lib/format';
import type { Project, ProjectRound } from '@/types/workbench';

function Navigation({ projectId }: { projectId: string }) {
  const location = useLocation();
  const { data: rounds = [] } = useQuery<ProjectRound[], Error>({ queryKey: ['rounds', projectId], queryFn: () => roundsApi.list(projectId) });
  const activeRoundId = useMemo(() => location.pathname.match(/rounds\/([^/]+)/)?.[1], [location.pathname]);
  return <nav className="sidebar">
    <div className="nav-heading"><span>项目工作台</span></div>
    <NavLink to={`/projects/${projectId}/overview`} className={({ isActive }) => `nav-item ${isActive ? 'nav-item-active' : ''}`}><LayoutDashboard size={16} />项目总览</NavLink>
    <NavLink to={`/projects/${projectId}/data`} className={({ isActive }) => `nav-item ${isActive ? 'nav-item-active' : ''}`}><Database size={16} />数据与资料</NavLink>
    <div className="nav-heading"><span>设计轮次</span><Link to={`/projects/${projectId}/overview`} className="button button-quiet icon-button" title="创建下一轮"><Plus size={16} /></Link></div>
    {rounds.length === 0 ? <div className="subtle" style={{ padding: '0 9px' }}>尚无轮次</div> : rounds.map((round) => <Link key={round.round_id} to={`/projects/${projectId}/rounds/${round.round_id}/${round.status === 'completed' ? 'ranking' : 'strategy'}`} className={`round-link ${activeRoundId === round.round_id ? 'round-link-active' : ''}`}><span>第 {round.round_number} 轮</span><StatusBadge status={round.status} /></Link>)}
    <div className="nav-heading"><span>当前工作</span></div>
    {activeRoundId ? <>
      <NavLink to={`/projects/${projectId}/rounds/${activeRoundId}/strategy`} className={({ isActive }) => `nav-item ${isActive ? 'nav-item-active' : ''}`}><Workflow size={16} />策略审核</NavLink>
      <NavLink to={`/projects/${projectId}/rounds/${activeRoundId}/run`} className={({ isActive }) => `nav-item ${isActive ? 'nav-item-active' : ''}`}><FlaskConical size={16} />Campaign 执行</NavLink>
      <NavLink to={`/projects/${projectId}/rounds/${activeRoundId}/ranking`} className={({ isActive }) => `nav-item ${isActive ? 'nav-item-active' : ''}`}><Beaker size={16} />排名与 Seed</NavLink>
    </> : <div className="subtle" style={{ padding: '0 9px' }}>选择一个轮次开始工作</div>}
  </nav>;
}

export function AppShell() {
  const { projectId } = useParams();
  const { data: project } = useQuery<Project, Error>({ queryKey: ['project', projectId], queryFn: () => projectsApi.get(projectId!), enabled: Boolean(projectId) });
  if (!projectId) return null;
  return <div className="app-shell">
    <header className="topbar"><Link className="brand" to="/projects"><FlaskConical size={20} />药物设计工作台</Link><div className="topbar-context"><span>项目</span><strong>{project?.name || '载入中…'}</strong><span>·</span><span>{project?.target_name || project?.target_id || '未选择靶点'}</span></div><div className="topbar-spacer" /><StatusBadge status={project?.status} /><span style={{ color: '#bed5cf', fontSize: 12 }}>{statusLabel(project?.status)}</span></header>
    <Navigation projectId={projectId} />
    <main className="main-content"><Outlet /></main>
    <div className="agent-rail"><AgentPanel /></div>
  </div>;
}
