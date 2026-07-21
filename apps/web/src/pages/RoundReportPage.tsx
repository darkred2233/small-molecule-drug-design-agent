import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, FileText, RefreshCw, ShieldAlert } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { reportsApi, roundsApi } from '@/api';
import { EmptyState } from '@/components/EmptyState';
import { MoleculeThumbnail } from '@/components/MoleculeThumbnail';
import { formatNumber, methodLabel } from '@/lib/format';
import type { ProjectReport, ProjectRound, RoundSummary } from '@/types/workbench';

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function citationParts(citation: Record<string, unknown>): { title: string; source: string; detail: string } {
  const title = String(citation.title || citation.document_title || citation.source || '未命名参考文献');
  const source = [citation.authors, citation.journal, citation.year, citation.doi || citation.pmid].filter(Boolean).map(String).join(' · ');
  const detail = String(citation.summary || citation.rationale || citation.content || '该引用的具体证据内容未在报告中返回。');
  return { title, source, detail };
}

export function RoundReportPage() {
  const { projectId, roundId } = useParams();
  const queryClient = useQueryClient();
  const enabled = Boolean(projectId && roundId);
  const { data: round } = useQuery<ProjectRound, Error>({ queryKey: ['round', projectId, roundId], queryFn: () => roundsApi.get(projectId!, roundId!), enabled });
  const { data: summary } = useQuery<RoundSummary, Error>({ queryKey: ['round-summary', projectId, roundId], queryFn: () => roundsApi.summary(projectId!, roundId!), enabled });
  const { data: roundReport } = useQuery<Record<string, unknown>, Error>({ queryKey: ['round-report', projectId, roundId], queryFn: () => roundsApi.report(projectId!, roundId!), enabled });
  const { data: report, error } = useQuery<ProjectReport, Error>({ queryKey: ['project-report', projectId], queryFn: () => reportsApi.project(projectId!), enabled, retry: false });
  const generate = useMutation<ProjectReport, Error>({ mutationFn: () => reportsApi.generate(projectId!), onSuccess: (next) => queryClient.setQueryData(['project-report', projectId], next) });
  const finalReport = report?.final_report;
  const executiveSummary = useMemo(() => finalReport?.executive_summary || strings(roundReport?.executive_summary) || strings(roundReport?.summary), [finalReport, roundReport]);
  const nextSteps = finalReport?.next_steps || strings(roundReport?.next_steps);
  const uncertainties = finalReport?.failures_and_uncertainties || strings(roundReport?.failures_and_uncertainties);
  const citations = finalReport?.citations || (Array.isArray(roundReport?.citations) ? roundReport.citations.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : []);

  return <div className="page"><div className="page-heading"><div><p className="eyebrow">第 {round?.round_number || '—'} 轮 · 中文报告</p><h1>{finalReport?.title || '本轮设计报告'}</h1><p className="subtle">报告正文、结论和风险说明均以中文呈现；SMILES、工具名、基因和专业缩写保留原始标识。</p></div><div className="row"><a className="button" href={reportsApi.downloadUrl(projectId!)} target="_blank" rel="noreferrer"><Download size={15} />下载 JSON</a><button className="button button-primary" onClick={() => generate.mutate()} disabled={generate.isPending}><RefreshCw size={15} />{generate.isPending ? '正在生成…' : '生成 / 刷新中文报告'}</button></div></div>
    {error && !report && <div className="notice notice-warning">{error instanceof Error ? error.message : '当前还不能生成完整报告。'} 可在本轮完成后重新生成。</div>}
    {!report && !error && <div className="panel"><EmptyState icon={FileText} title="中文报告尚未生成" detail="报告会汇总本轮策略、生成、排名、对接、ADMET、合成路线和文献证据。" action={<button className="button button-primary" onClick={() => generate.mutate()} disabled={generate.isPending}>生成报告</button>} /></div>}
    {report && <div className="section-stack"><div className="metric-grid"><div className="metric"><div className="metric-label">候选分子</div><div className="metric-value">{summary?.molecule_count ?? report.candidate_summary.molecule_count}</div><div className="metric-note">本轮归档结果</div></div><div className="metric"><div className="metric-label">完成对接</div><div className="metric-value">{summary?.docking_count || 0}</div><div className="metric-note">带有计算结果的分子</div></div><div className="metric"><div className="metric-label">进入排名</div><div className="metric-value">{summary?.ranking_count ?? report.candidate_summary.ranking_count}</div><div className="metric-note">综合排名记录</div></div><div className="metric"><div className="metric-label">参考文献</div><div className="metric-value">{citations.length}</div><div className="metric-note">可追溯的证据条目</div></div></div>
      <section className="panel"><div className="panel-header"><h2>执行摘要</h2></div><div className="panel-body stack">{executiveSummary.length ? executiveSummary.map((paragraph, index) => <p key={index} style={{ margin: 0, lineHeight: 1.75, fontSize: 14 }}>{paragraph}</p>) : <div className="notice">本轮汇总已建立，但 Agent 尚未返回文字摘要。下方仍可查看已归档的量化结果。</div>}</div></section>
      <section className="panel"><div className="panel-header"><h2>本轮 Campaign 结果</h2></div><div className="table-scroll"><table className="data-table"><thead><tr><th>生成方式</th><th>状态</th><th>输出候选</th></tr></thead><tbody>{summary?.campaigns.map((campaign) => <tr key={campaign.campaign_run_id}><td>{methodLabel(campaign.method)}</td><td>{campaign.status}</td><td>{campaign.output_count}</td></tr>) || <tr><td colSpan={3}>尚无 Campaign 汇总。</td></tr>}</tbody></table></div></section>
      <section className="panel"><div className="panel-header"><h2>Top 候选分子</h2></div>{report.top_candidates.length === 0 ? <EmptyState icon={FileText} title="暂无 Top 分子" detail="排名完成后会在报告中生成候选分子摘要。" /> : <div className="table-scroll"><table className="data-table"><thead><tr><th>排名</th><th>结构</th><th>分子</th><th>来源</th><th>综合分</th><th>最佳对接分数</th><th>结论</th></tr></thead><tbody>{report.top_candidates.map((candidate) => <tr key={candidate.molecule_id}><td className="score">{candidate.rank}</td><td>{candidate.smiles ? <MoleculeThumbnail smiles={candidate.smiles} /> : '—'}</td><td className="mono">{candidate.molecule_id}</td><td>{methodLabel(candidate.generation_method || candidate.generation_source_agent)}</td><td className="score">{formatNumber(candidate.overall_score, 3)}</td><td>{formatNumber(candidate.docking?.vina_score ?? candidate.docking?.docking_score, 2)}</td><td>{candidate.final_decision}</td></tr>)}</tbody></table></div>}</section>
      <div className="two-column"><section className="panel"><div className="panel-header"><h2>不确定性与限制</h2></div><div className="panel-body stack">{uncertainties.length ? uncertainties.map((item, index) => <div className="notice notice-warning" key={index}><ShieldAlert size={16} />{item}</div>) : <div className="subtle">报告中未记录额外的不确定性条目。</div>}</div></section><section className="panel"><div className="panel-header"><h2>下一轮建议</h2></div><div className="panel-body stack">{nextSteps.length ? nextSteps.map((item, index) => <div className="notice" key={index}>{item}</div>) : <div className="subtle">完成排名并选择 Seed 后，系统会形成下一轮策略建议。</div>}</div></section></div>
      <section className="panel"><div className="panel-header"><h2>参考文献与证据来源</h2><span className="subtle" style={{ margin: 0 }}>所有结论应区分计算结果、文献证据和 Agent 推断。</span></div><div className="panel-body">{citations.length ? citations.map((citation, index) => { const item = citationParts(citation); return <article className="citation" key={index}><div className="row-wrap"><span className="badge badge-neutral">[{index + 1}]</span><div className="citation-title">{item.title}</div></div>{item.source && <div className="citation-meta">{item.source}</div>}<div className="citation-quote">{item.detail}</div></article>; }) : <div className="subtle">当前报告没有返回可引用的文献条目。上传并解析论文资料后，分子证据页会显示页码和原文片段。</div>}</div></section>
    </div>}
  </div>;
}
