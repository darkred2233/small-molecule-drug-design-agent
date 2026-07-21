import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Database, FileText, Plus, Wrench } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { projectsApi, roundsApi, toolsApi } from '@/api';
import { EmptyState } from '@/components/EmptyState';
import { StatusBadge } from '@/components/StatusBadge';
import { formatDate } from '@/lib/format';
import type { Project, ProjectRound, ToolStatus } from '@/types/workbench';

export function ProjectOverviewPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: project } = useQuery<Project, Error>({ queryKey: ['project', projectId], queryFn: () => projectsApi.get(projectId!), enabled: Boolean(projectId) });
  const { data: rounds = [] } = useQuery<ProjectRound[], Error>({ queryKey: ['rounds', projectId], queryFn: () => roundsApi.list(projectId!), enabled: Boolean(projectId) });
  const { data: stats } = useQuery<Record<string, unknown>, Error>({ queryKey: ['stats', projectId], queryFn: () => projectsApi.stats(projectId!), enabled: Boolean(projectId) });
  const { data: tools = [] } = useQuery<ToolStatus[], Error>({ queryKey: ['tools'], queryFn: toolsApi.status });
  const createRound = useMutation<ProjectRound, Error>({
    mutationFn: () => roundsApi.create(projectId!, { round_number: Math.max(0, ...rounds.map((round) => round.round_number)) + 1, parent_round_id: rounds.length ? rounds[0].round_id : undefined, user_conditions_json: {} }),
    onSuccess: (round) => { queryClient.invalidateQueries({ queryKey: ['rounds', projectId] }); navigate(`/projects/${projectId}/rounds/${round.round_id}/strategy`); },
  });
  const totalMolecules = Number(stats?.total_molecules || 0);
  const evaluated = Number(stats?.evaluated_molecules || 0);
  const dockingTools = tools.filter((tool) => ['gnina', 'vina'].includes(tool.tool_name.toLowerCase()));

  return <div className="page"><div className="page-heading"><div><p className="eyebrow">项目总览</p><h1>{project?.name || '项目载入中'}</h1><p className="subtle">{project?.objective || '尚未设定设计目标。'}</p></div><div className="row"><Link className="button" to="../data"><Database size={16} />数据与资料</Link><button className="button button-primary" onClick={() => createRound.mutate()} disabled={createRound.isPending}>{createRound.isPending ? '正在创建…' : '创建新轮次'} <Plus size={16} /></button></div></div>
    <div className="metric-grid"><div className="metric"><div className="metric-label">设计轮次</div><div className="metric-value">{rounds.length}</div><div className="metric-note">策略与结果按轮次留档</div></div><div className="metric"><div className="metric-label">候选分子</div><div className="metric-value">{totalMolecules}</div><div className="metric-note">包含所有已生成分子</div></div><div className="metric"><div className="metric-label">已评估分子</div><div className="metric-value">{evaluated}</div><div className="metric-note">完成任一评估阶段</div></div><div className="metric"><div className="metric-label">推荐分子</div><div className="metric-value">{Number(stats?.excellent_molecules || 0)}</div><div className="metric-note">当前标记为推荐</div></div></div>
    <div className="two-column" style={{ marginTop: 18 }}><section className="panel"><div className="panel-header"><h2>轮次记录</h2></div>{rounds.length === 0 ? <EmptyState icon={Plus} title="尚未开始第一轮" detail="先检查数据，再让 Agent 生成可审核的策略草案。" action={<button className="button button-primary" onClick={() => createRound.mutate()}><Plus size={15} />创建第 1 轮</button>} /> : <div className="table-scroll"><table className="data-table"><thead><tr><th>轮次</th><th>状态</th><th>开始</th><th /></tr></thead><tbody>{rounds.map((round) => <tr key={round.round_id}><td>第 {round.round_number} 轮</td><td><StatusBadge status={round.status} /></td><td>{formatDate(round.started_at || round.created_at)}</td><td><Link className="button" to={`../rounds/${round.round_id}/${round.status === 'completed' ? 'ranking' : 'strategy'}`}>打开 <ArrowRight size={14} /></Link></td></tr>)}</tbody></table></div>}</section>
      <section className="panel"><div className="panel-header"><div className="row"><Wrench size={17} color="#176451" /><h2>评估工具状态</h2></div></div><div className="panel-body stack">{dockingTools.length === 0 ? <div className="notice notice-warning">尚未返回 GNINA/Vina 工具状态。生成策略前系统会再次检查可用性。</div> : dockingTools.map((tool) => <div key={tool.tool_name} className="row" style={{ justifyContent: 'space-between' }}><div><strong>{tool.tool_name.toUpperCase()}</strong><div className="subtle">{tool.version || '版本未报告'}</div></div><StatusBadge status={tool.status === 'available' ? 'completed' : tool.status === 'unavailable' ? 'failed' : 'pending'} /></div>)}<div className="divider" /><Link className="button" to="../data"><FileText size={15} />查看资料完整性</Link></div></section></div>
  </div>;
}
