import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckSquare, Filter, FlaskConical, Plus, Square } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { roundsApi } from '@/api/rounds';
import { EmptyState } from '@/components/EmptyState';
import { MoleculeThumbnail } from '@/components/MoleculeThumbnail';
import { StatusBadge } from '@/components/StatusBadge';
import { formatNumber, methodLabel } from '@/lib/format';
import type { DockingResult, Molecule, ProjectRound, Ranking } from '@/types/workbench';

export function RankingPage() {
  const { projectId, roundId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const enabled = Boolean(projectId && roundId);
  const { data: round } = useQuery<ProjectRound, Error>({ queryKey: ['round', projectId, roundId], queryFn: () => roundsApi.get(projectId!, roundId!), enabled });
  const { data: rankings = [] } = useQuery<Ranking[], Error>({ queryKey: ['rankings', projectId, roundId], queryFn: () => roundsApi.rankings(projectId!, roundId!), enabled });
  const { data: molecules = [] } = useQuery<Molecule[], Error>({ queryKey: ['round-molecules', projectId, roundId], queryFn: () => roundsApi.molecules(projectId!, roundId!), enabled });
  const { data: dockings = [] } = useQuery<DockingResult[], Error>({ queryKey: ['round-docking', projectId, roundId], queryFn: () => roundsApi.docking(projectId!, roundId!), enabled });
  const [method, setMethod] = useState('all');
  const [minimumScore, setMinimumScore] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const moleculeById = useMemo(() => new Map(molecules.map((molecule) => [molecule.molecule_id, molecule])), [molecules]);
  const dockingById = useMemo(() => new Map(dockings.map((result) => [result.molecule_id, result])), [dockings]);
  const rows = useMemo(() => rankings.map((ranking) => ({ ranking, molecule: moleculeById.get(ranking.molecule_id), docking: dockingById.get(ranking.molecule_id) })).filter(({ ranking, molecule }) => (method === 'all' || molecule?.generation_method === method) && (!minimumScore || (ranking.overall_score || 0) >= Number(minimumScore))), [dockingById, method, minimumScore, moleculeById, rankings]);
  const methods = [...new Set(molecules.map((molecule) => molecule.generation_method).filter(Boolean))] as string[];
  const toggle = (id: string) => setSelected((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const chooseTop = (count: number) => setSelected(new Set(rows.slice(0, count).map(({ ranking }) => ranking.molecule_id)));
  const nextRound = useMutation<ProjectRound, Error>({
    mutationFn: () => roundsApi.create(projectId!, { round_number: (round?.round_number || 0) + 1, parent_round_id: roundId, user_conditions_json: { selected_seed_molecule_ids: [...selected], selection_source: 'user_ranking_selection' } }),
    onSuccess: (next) => { queryClient.invalidateQueries({ queryKey: ['rounds', projectId] }); navigate(`/projects/${projectId}/rounds/${next.round_id}/strategy`); },
  });

  return <div className="page"><div className="page-heading"><div><p className="eyebrow">第 {round?.round_number || '—'} 轮 · 排名与选择</p><h1>评估结果与下一轮 Seed</h1><p className="subtle">将综合排名、对接、来源方法和父分子放在同一张决策表中。选择 Seed 后，Agent 会将它们带入下一轮策略草案。</p></div><div className="row"><Link className="button" to={`../report`}>查看本轮报告</Link><StatusBadge status={round?.status} /></div></div>
    <div className="panel"><div className="panel-header"><div className="row"><Filter size={16} color="#176451" /><h2>候选分子排名</h2></div><div className="row"><select aria-label="按生成方法筛选" value={method} onChange={(event) => setMethod(event.target.value)} style={{ height: 32, border: '1px solid #c9d5cf', borderRadius: 4 }}><option value="all">全部生成方式</option>{methods.map((item) => <option key={item} value={item}>{methodLabel(item)}</option>)}</select><input aria-label="最低综合分" value={minimumScore} onChange={(event) => setMinimumScore(event.target.value)} type="number" placeholder="最低综合分" style={{ width: 112, height: 32, padding: '0 8px', border: '1px solid #c9d5cf', borderRadius: 4 }} /></div></div>{rows.length === 0 ? <EmptyState icon={FlaskConical} title="本轮尚无可排名分子" detail="执行完成并生成排名后，候选分子将在这里显示。" /> : <div className="table-scroll"><table className="data-table"><thead><tr><th><button className="button button-quiet icon-button" title="选择前 10 个" onClick={() => chooseTop(Math.min(10, rows.length))}>{selected.size ? <CheckSquare size={16} /> : <Square size={16} />}</button></th><th>排名</th><th>结构</th><th>分子</th><th>生成方式</th><th>父分子</th><th>综合分</th><th>Docking</th><th>决策</th></tr></thead><tbody>{rows.map(({ ranking, molecule, docking }) => <tr key={ranking.molecule_id}><td><input aria-label={`选择 ${ranking.molecule_id}`} type="checkbox" checked={selected.has(ranking.molecule_id)} onChange={() => toggle(ranking.molecule_id)} /></td><td className="score">{ranking.rank}</td><td>{molecule ? <MoleculeThumbnail smiles={molecule.smiles} /> : '—'}</td><td><Link className="text-link mono" to={`/projects/${projectId}/molecules/${ranking.molecule_id}`}>{ranking.molecule_id}</Link></td><td>{methodLabel(molecule?.generation_method || molecule?.source_agent)}</td><td>{molecule?.parent_molecule_ids?.length ? <span className="mono">{molecule.parent_molecule_ids[0]}{molecule.parent_molecule_ids.length > 1 ? ` +${molecule.parent_molecule_ids.length - 1}` : ''}</span> : 'Seed / 未记录'}</td><td className="score">{formatNumber(ranking.overall_score, 3)}</td><td>{formatNumber(docking?.vina_score ?? docking?.docking_score, 2)}</td><td><StatusBadge status={ranking.final_decision === 'recommended' ? 'completed' : ranking.final_decision} /></td></tr>)}</tbody></table></div>}</div>
    {selected.size > 0 && <div className="selection-tray"><div><strong>已选择 {selected.size} 个分子作为下一轮 Seed</strong><div className="subtle">下一轮策略生成时会保留这份用户选择，并允许 Agent 继续提出补充建议。</div></div><div className="row"><button className="button" onClick={() => setSelected(new Set())}>清空</button><button className="button button-primary" onClick={() => { if (window.confirm(`确认以这 ${selected.size} 个分子创建下一轮策略草案？`)) nextRound.mutate(); }} disabled={nextRound.isPending}>{nextRound.isPending ? '正在创建…' : '创建下一轮'} <Plus size={15} /></button></div></div>}
  </div>;
}
