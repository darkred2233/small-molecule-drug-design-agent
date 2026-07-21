import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Edit3, Play, RotateCcw, Sparkles } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { roundsApi } from '@/api/rounds';
import { EmptyState } from '@/components/EmptyState';
import { StatusBadge } from '@/components/StatusBadge';
import { campaignCount, methodLabel } from '@/lib/format';
import type { CampaignConfig, ProjectRound, StrategyDraft } from '@/types/workbench';

function countKey(config: CampaignConfig): 'num_molecules' | 'sample_count' {
  return typeof config.sample_count === 'number' ? 'sample_count' : 'num_molecules';
}

function campaignOverrides(strategy: StrategyDraft | undefined, counts: Record<string, number>, seedIds: string[]): Record<string, unknown> {
  const campaignConfig = Object.fromEntries(Object.entries(strategy?.campaign_config || {}).map(([method, config]) => {
    const key = countKey(config);
    return [method, { ...config, [key]: counts[method] ?? campaignCount(config) }];
  }));
  const overrides: Record<string, unknown> = { campaign_config: campaignConfig };
  if (seedIds.length) overrides.seed_policy = { source: 'top_from_previous', top_n: seedIds.length, molecule_ids: seedIds, description: '用户从上一轮排名中手动选择的 Seed。' };
  return overrides;
}

export function StrategyPage() {
  const { projectId, roundId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: round } = useQuery<ProjectRound, Error>({ queryKey: ['round', projectId, roundId], queryFn: () => roundsApi.get(projectId!, roundId!), enabled: Boolean(projectId && roundId) });
  const strategyQuery = useQuery<StrategyDraft, Error>({ queryKey: ['strategy', projectId, roundId], queryFn: () => roundsApi.strategy(projectId!, roundId!), enabled: Boolean(projectId && roundId), retry: false });
  const strategy = strategyQuery.data;
  const selectedSeedIds = useMemo(() => {
    const value = round?.user_conditions_json?.selected_seed_molecule_ids;
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
  }, [round]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [initialMessage, setInitialMessage] = useState('');

  useEffect(() => {
    if (!strategy) return;
    setCounts(Object.fromEntries(Object.entries(strategy.campaign_config).map(([method, config]) => [method, campaignCount(config)])));
  }, [strategy]);

  const draft = useMutation<StrategyDraft, Error>({
    mutationFn: () => roundsApi.draftStrategy(projectId!, roundId!, { user_message: initialMessage.trim() || undefined, user_overrides: selectedSeedIds.length ? { seed_policy: { source: 'top_from_previous', top_n: selectedSeedIds.length, molecule_ids: selectedSeedIds, description: '用户在上一轮排名中手动选择。' } } : undefined }),
    onSuccess: (nextStrategy) => { queryClient.setQueryData(['strategy', projectId, roundId], nextStrategy); queryClient.invalidateQueries({ queryKey: ['round', projectId, roundId] }); },
  });
  const confirm = useMutation<{ round_id: string; status: string; message: string }, Error>({
    mutationFn: () => roundsApi.confirmStrategy(projectId!, roundId!, { confirmed: true, user_modifications: campaignOverrides(strategy, counts, selectedSeedIds) }),
    onSuccess: (result) => { queryClient.invalidateQueries({ queryKey: ['rounds', projectId] }); queryClient.invalidateQueries({ queryKey: ['round', projectId, roundId] }); navigate(`/projects/${projectId}/rounds/${roundId}/${result.status === 'completed' ? 'ranking' : 'run'}`); },
  });
  const resetCounts = () => setCounts(Object.fromEntries(Object.entries(strategy?.campaign_config || {}).map(([method, config]) => [method, campaignCount(config)])));
  const canConfirm = Boolean(strategy && ['draft', 'ready'].includes(round?.status || ''));

  return <div className="page"><div className="page-heading"><div><p className="eyebrow">第 {round?.round_number || '—'} 轮 · 策略审核</p><h1>确认本轮生成与评估策略</h1><p className="subtle">Agent 根据目标、数据完整性、工具状态和上一轮结果拟定方案。任何自然语言或手动修改都会形成可审计的新草案。</p></div><StatusBadge status={round?.status} /></div>
    {!strategy && !strategyQuery.isLoading && <section className="panel"><EmptyState icon={Sparkles} title="尚未生成策略草案" detail="先让中枢 Agent 根据当前项目数据组织本轮 Campaign。" action={<div className="stack" style={{ width: 520, maxWidth: '100%' }}><div className="field"><label htmlFor="initial-strategy-message">补充本轮要求（可选）</label><textarea id="initial-strategy-message" value={initialMessage} onChange={(event) => setInitialMessage(event.target.value)} placeholder="例如：本轮优先探索骨架多样性，同时保留上一轮最优分子的局部优化。" /></div><button className="button button-primary" onClick={() => draft.mutate()} disabled={draft.isPending}>{draft.isPending ? '正在拟定策略…' : '生成策略草案'}</button>{draft.error && <div className="notice notice-danger">{draft.error instanceof Error ? draft.error.message : '策略草案生成失败。'}</div>}</div>} /></section>}
    {strategyQuery.isLoading && <div className="empty-state">正在读取本轮策略…</div>}
    {strategy && <div className="section-stack"><section className="panel"><div className="panel-header"><div><h2>策略摘要</h2><p className="subtle">{strategy.objective}</p></div><div className="row"><button className="button" onClick={resetCounts}><RotateCcw size={15} />恢复 Agent 建议</button><button className="button button-primary" onClick={() => { if (window.confirm('确认后将按当前策略执行本轮生成、评估和排名。执行记录会永久归档到本轮。')) confirm.mutate(); }} disabled={!canConfirm || confirm.isPending}><Play size={15} />{confirm.isPending ? '正在执行…' : '确认并执行'}</button></div></div><div className="panel-body section-stack"><div className="notice"><CheckCircle2 size={16} />{strategy.rationale}</div>{selectedSeedIds.length > 0 && <div className="notice"><Edit3 size={16} />本轮已带入你手动选择的 {selectedSeedIds.length} 个上一轮 Seed；确认时将覆盖 Agent 的默认 Seed 选择。</div>}{strategy.warnings.length > 0 && <div className="stack">{strategy.warnings.map((warning, index) => <div key={`${warning}-${index}`} className="notice notice-warning"><AlertTriangle size={16} />{warning}</div>)}</div>}</div></section>
      <section className="panel"><div className="panel-header"><div><h2>Campaign 计划</h2><p className="subtle">在此手动修改数量。更复杂的策略变化可通过右侧 Agent 面板用自然语言提出。</p></div><span className="badge badge-neutral">预计生成 {Object.values(counts).reduce((total, count) => total + count, 0)} 个候选</span></div><div className="table-scroll"><table className="data-table"><thead><tr><th>生成方式</th><th>状态</th><th>计划数量</th><th>关键参数</th><th>策略角色</th></tr></thead><tbody>{Object.entries(strategy.campaign_config).map(([method, config]) => <tr key={method}><td><strong>{methodLabel(method)}</strong><div className="mono subtle" style={{ margin: '2px 0 0' }}>{method}</div></td><td><StatusBadge status={config.enabled === false ? 'failed' : 'ready'} /></td><td><input aria-label={`${method} 生成数量`} type="number" min="0" max="1000" value={counts[method] ?? campaignCount(config)} onChange={(event) => setCounts((current) => ({ ...current, [method]: Math.max(0, Number(event.target.value) || 0) }))} style={{ width: 92, height: 32, padding: '0 8px', border: '1px solid #c9d5cf', borderRadius: 4 }} /></td><td>{Object.entries(config).filter(([key, value]) => !['enabled', 'num_molecules', 'sample_count'].includes(key) && value !== null && value !== undefined).slice(0, 3).map(([key, value]) => <div key={key} className="subtle" style={{ margin: '1px 0' }}>{key}: {String(value)}</div>)}</td><td>{method === 'crem' ? '局部结构编辑' : method === 'reinvent4' ? '目标导向生成' : method === 'autogrow4' ? '口袋引导探索' : '候选生成'}</td></tr>)}</tbody></table></div></section>
      <div className="two-column"><section className="panel"><div className="panel-header"><h2>Seed 策略</h2></div><div className="panel-body stack"><div><strong>{strategy.seed_policy?.source || '未指定'}</strong><p className="subtle">{strategy.seed_policy?.description || '由 Agent 根据当前数据选择。'}</p></div><div className="row-wrap">{strategy.seed_policy?.top_n && <span className="badge badge-neutral">Top {strategy.seed_policy.top_n}</span>}{strategy.seed_policy?.molecule_ids?.map((id) => <span className="badge badge-neutral mono" key={id}>{id}</span>)}</div></div></section><section className="panel"><div className="panel-header"><h2>评估边界</h2></div><div className="panel-body stack"><div className="row" style={{ justifyContent: 'space-between' }}><span>对接评估</span><StatusBadge status={strategy.assessment_config?.skip_docking ? 'failed' : 'completed'} /></div><div className="row" style={{ justifyContent: 'space-between' }}><span>ADMET 评估</span><StatusBadge status={strategy.assessment_config?.skip_admet ? 'failed' : 'completed'} /></div><div className="row" style={{ justifyContent: 'space-between' }}><span>合成可行性</span><StatusBadge status={strategy.assessment_config?.skip_synthesis ? 'failed' : 'completed'} /></div></div></section></div>
      {confirm.error && <div className="notice notice-danger">{confirm.error instanceof Error ? confirm.error.message : '本轮执行失败。'}</div>}
    </div>}
  </div>;
}
