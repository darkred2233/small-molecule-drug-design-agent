import { useQuery } from '@tanstack/react-query';
import { Activity, ArrowRight, Clock3, FlaskConical, Info } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { roundsApi } from '@/api/rounds';
import { EmptyState } from '@/components/EmptyState';
import { StatusBadge } from '@/components/StatusBadge';
import { formatDate, methodLabel } from '@/lib/format';
import type { CampaignRun, ProjectRound, RoundSummary } from '@/types/workbench';

export function RoundRunPage() {
  const { projectId, roundId } = useParams();
  const enabled = Boolean(projectId && roundId);
  const { data: round } = useQuery<ProjectRound, Error>({ queryKey: ['round', projectId, roundId], queryFn: () => roundsApi.get(projectId!, roundId!), enabled, refetchInterval: (query) => query.state.data?.status === 'running' ? 5000 : false });
  const { data: campaigns = [] } = useQuery<CampaignRun[], Error>({ queryKey: ['campaigns', projectId, roundId], queryFn: () => roundsApi.campaigns(projectId!, roundId!), enabled, refetchInterval: round?.status === 'running' ? 5000 : false });
  const { data: summary } = useQuery<RoundSummary, Error>({ queryKey: ['round-summary', projectId, roundId], queryFn: () => roundsApi.summary(projectId!, roundId!), enabled, refetchInterval: round?.status === 'running' ? 5000 : false });
  const completed = campaigns.filter((campaign) => campaign.status === 'completed').length;
  const progress = campaigns.length ? Math.round((completed / campaigns.length) * 100) : 0;
  return <div className="page"><div className="page-heading"><div><p className="eyebrow">第 {round?.round_number || '—'} 轮 · Campaign 执行</p><h1>生成与评估进度</h1><p className="subtle">执行过程由后端编排。此处只显示可验证的状态和结果，不提供没有后端能力支持的暂停或重试操作。</p></div><div className="row"><StatusBadge status={round?.status} /><Link className="button" to={`../ranking`}>查看排名 <ArrowRight size={15} /></Link></div></div>
    <div className="metric-grid"><div className="metric"><div className="metric-label">Campaign</div><div className="metric-value">{completed} / {campaigns.length}</div><div className="metric-note">已完成 / 总计划</div></div><div className="metric"><div className="metric-label">生成候选</div><div className="metric-value">{summary?.molecule_count || 0}</div><div className="metric-note">本轮已归档分子</div></div><div className="metric"><div className="metric-label">对接结果</div><div className="metric-value">{summary?.docking_count || 0}</div><div className="metric-note">GNINA / Vina 结果</div></div><div className="metric"><div className="metric-label">已完成评估</div><div className="metric-value">{summary?.ranking_count || 0}</div><div className="metric-note">进入最终排名</div></div></div>
    <section className="panel" style={{ marginTop: 18 }}><div className="panel-header"><div className="row"><Activity size={17} color="#176451" /><h2>执行进度</h2></div><span className="score">{progress}%</span></div><div className="panel-body"><div className="progress-bar"><span style={{ width: `${progress}%` }} /></div><div className="subtle">最近状态更新由页面自动刷新。轮次结束后，系统会保存排名、报告和下一轮策略建议。</div></div></section>
    <section className="panel" style={{ marginTop: 18 }}><div className="panel-header"><h2>Campaign 明细</h2></div>{campaigns.length === 0 ? <EmptyState icon={FlaskConical} title="尚未创建 Campaign" detail="策略确认并执行后，系统会在这里列出每一种生成方法的运行记录。" /> : <div className="table-scroll"><table className="data-table"><thead><tr><th>Campaign</th><th>生成方法</th><th>输入 Seed</th><th>输出候选</th><th>状态</th><th>执行时间</th><th>提示</th></tr></thead><tbody>{campaigns.map((campaign) => <tr key={campaign.campaign_run_id}><td className="mono">{campaign.campaign_run_id}</td><td><strong>{methodLabel(campaign.method)}</strong></td><td>{campaign.input_molecule_ids.length}</td><td>{campaign.output_molecule_ids.length}</td><td><StatusBadge status={campaign.status} /></td><td>{campaign.started_at ? <span><Clock3 size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />{formatDate(campaign.started_at)}</span> : '尚未开始'}</td><td>{campaign.warnings_json.length ? <span className="badge badge-warning" title={campaign.warnings_json.join('\n')}><Info size={12} />{campaign.warnings_json.length} 项</span> : '—'}</td></tr>)}</tbody></table></div>}</section>
  </div>;
}
