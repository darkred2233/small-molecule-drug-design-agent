import { type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  FlaskConical,
  GitBranch,
  MapPinned,
  Route,
  ShieldAlert,
  Target,
} from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { reportsApi } from '@/api';
import type {
  AdmetSummary,
  ProjectReport,
  ReportCandidate,
  ReportSeedLigand,
  RuleFilterSummary,
  SynthesisSummary,
  TargetAdmetRisk,
  TargetBindingSite,
  TargetSarRule,
} from '@/types/api';
import { cn, formatNumber } from '@/utils/helpers';
import { decisionTone } from '@/utils/reportPresentation';

export default function ReportPage() {
  const { projectId } = useParams();

  const { data: report, isLoading } = useQuery<ProjectReport>({
    queryKey: ['report', projectId],
    queryFn: () => reportsApi.get(projectId!),
    enabled: Boolean(projectId),
  });

  if (isLoading) {
    return (
      <div className="app-shell flex h-screen items-center justify-center">
        <div className="flex items-center gap-2 text-slate-500">
          <Activity className="h-4 w-4 animate-pulse text-cyan-700" />
          正在生成报告
        </div>
      </div>
    );
  }

  if (!report || !projectId) {
    return (
      <div className="app-shell flex h-screen items-center justify-center">
        <div className="text-slate-500">报告不可用</div>
      </div>
    );
  }

  const summary = report.project_summary;
  const targetName = summary.target_name ?? summary.target_id ?? '自定义靶点';
  const targetAnalysis = report.target_and_pocket_analysis;
  const candidateSummary = report.candidate_summary;
  const sarOverview = report.sar_overview;
  const admetOverview = report.admet_overview;
  const synthesisOverview = report.synthesis_overview;
  const topCandidate = report.top_candidates[0];
  const reportDownloadName = `${safeFilename(summary.name)}_${summary.project_id}_report.json`;

  return (
    <div className="app-shell h-screen overflow-y-auto">
      <div className="sticky top-0 z-10 border-b border-cyan-100/80 bg-white/95 backdrop-blur">
        <div className="mx-auto max-w-7xl px-6 py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <Link
                  to={`/workspace/${projectId}`}
                  className="inline-flex items-center gap-2 rounded-md border border-cyan-100 bg-white px-3 py-1.5 text-sm text-slate-600 hover:border-cyan-200 hover:text-cyan-800"
                >
                  <ArrowLeft className="h-4 w-4" />
                  返回
                </Link>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <FileText className="h-5 w-5 text-cyan-700" />
                    <h1 className="truncate text-xl font-semibold text-slate-950">项目报告</h1>
                  </div>
                  <p className="truncate text-sm text-slate-500">{summary.name}</p>
                </div>
              </div>
            </div>
            <a
              href={reportsApi.downloadUrl(projectId)}
              download={reportDownloadName}
              className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-cyan-900/20 hover:bg-cyan-700"
            >
              <Download className="h-4 w-4" />
              下载报告
            </a>
          </div>
        </div>
      </div>

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-6">
        <section className="rounded-lg border border-cyan-100 bg-white p-6 shadow-sm shadow-cyan-950/5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-cyan-800">
                <Target className="h-4 w-4" />
                {targetName}
              </div>
              <h2 className="mt-2 text-2xl font-semibold text-slate-950">{summary.name}</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                {summary.objective ?? '当前项目没有填写明确的优化目标。'}
              </p>
            </div>
            <StatusPill status={summary.status} />
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <Metric label="总分子数" value={candidateSummary.molecule_count} tone="slate" />
            <Metric label="排名分子" value={candidateSummary.ranking_count} tone="cyan" />
            <Metric label="样例分子" value={candidateSummary.seed_ligand_count ?? 0} tone="emerald" />
            <Metric label="口袋数" value={candidateSummary.binding_site_count ?? 0} tone="sky" />
            <Metric label="合成路线" value={candidateSummary.synthesis_route_count ?? 0} tone="amber" />
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,0.65fr)]">
          <div className="space-y-6">
            <Panel title="靶点与口袋" icon={<MapPinned className="h-4 w-4" />}>
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
                <div className="space-y-4">
                  <InfoGrid
                    items={[
                      ['靶点 ID', summary.target_id ?? '-'],
                      ['UniProt', targetAnalysis?.target.uniprot_id ?? '-'],
                      ['物种', targetAnalysis?.target.species ?? '-'],
                      ['PDB 数量', (targetAnalysis?.target.pdb_ids ?? []).length],
                    ]}
                  />
                  <div className="rounded-lg border border-cyan-100 bg-cyan-50/50 p-4">
                    <div className="text-sm font-semibold text-cyan-900">口袋摘要</div>
                    <p className="mt-2 text-sm leading-6 text-slate-600">
                      {targetAnalysis?.target.pocket_summary ?? summary.target_name ?? '暂无口袋摘要'}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(targetAnalysis?.target.pdb_ids ?? []).map((pdbId) => (
                        <Badge key={pdbId} tone="cyan">
                          PDB {pdbId}
                        </Badge>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="rounded-lg border border-cyan-100 bg-white p-4">
                  <div className="text-sm font-semibold text-slate-950">绑定位点</div>
                  <div className="mt-3 space-y-3">
                    {(targetAnalysis?.binding_sites ?? []).map((site) => (
                      <BindingSiteCard key={site.binding_site_id} site={site} />
                    ))}
                    {(targetAnalysis?.binding_sites ?? []).length === 0 && (
                      <div className="text-sm text-slate-500">暂无绑定位点。</div>
                    )}
                  </div>
                </div>
              </div>

              <div className="mt-4">
                <div className="mb-3 text-sm font-semibold text-slate-950">样例分子</div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {(targetAnalysis?.seed_ligands ?? []).slice(0, 6).map((ligand) => (
                    <SeedLigandCard key={ligand.ligand_id} ligand={ligand} />
                  ))}
                  {(targetAnalysis?.seed_ligands ?? []).length === 0 && (
                    <div className="text-sm text-slate-500">暂无样例分子。</div>
                  )}
                </div>
              </div>
            </Panel>

            <Panel title="SAR 规则" icon={<FlaskConical className="h-4 w-4" />}>
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
                <div className="space-y-3">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <Metric
                      label="规则结果"
                      value={sarOverview?.rule_filter_statistics?.result_count ?? 0}
                      tone="cyan"
                    />
                    <Metric
                      label="失败规则"
                      value={Object.keys(sarOverview?.rule_filter_statistics?.failed_rule_counts ?? {}).length}
                      tone="amber"
                    />
                    <Metric
                      label="告警分子"
                      value={sarOverview?.molecule_rule_findings?.length ?? 0}
                      tone="rose"
                    />
                  </div>
                  <div className="space-y-3">
                    {(sarOverview?.target_sar_rules ?? []).map((rule) => (
                      <RuleCard key={rule.rule_id ?? rule.title} rule={rule} />
                    ))}
                  </div>
                </div>

                <div className="space-y-3 rounded-lg border border-cyan-100 bg-cyan-50/40 p-4">
                  <div className="text-sm font-semibold text-slate-950">规则统计</div>
                  <CountList
                    title="决策分布"
                    counts={sarOverview?.rule_filter_statistics?.decision_counts}
                  />
                  <CountList
                    title="失败规则"
                    counts={sarOverview?.rule_filter_statistics?.failed_rule_counts}
                  />
                  <CountList
                    title="告警标签"
                    counts={sarOverview?.rule_filter_statistics?.warning_counts}
                  />
                  <div className="pt-2">
                    <div className="text-sm font-semibold text-slate-950">结构化发现</div>
                    <div className="mt-2 space-y-2">
                      {(sarOverview?.molecule_rule_findings ?? []).slice(0, 4).map((item) => (
                        <RuleFindingCard key={item.filter_result_id} finding={item} />
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </Panel>

            <Panel title="ADMET 风险" icon={<ShieldAlert className="h-4 w-4" />}>
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
                <div className="space-y-3">
                  <div className="grid gap-3 sm:grid-cols-4">
                    <Metric label="结果数" value={admetOverview?.result_count ?? 0} tone="cyan" />
                    <Metric
                      label="高风险分子"
                      value={admetOverview?.high_risk_molecules?.length ?? 0}
                      tone="rose"
                    />
                    <Metric label="hERG" value={getRiskCount(admetOverview?.risk_counts, 'hERG')} tone="amber" />
                    <Metric label="Ames" value={getRiskCount(admetOverview?.risk_counts, 'Ames')} tone="amber" />
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    {(admetOverview?.target_admet_risks ?? []).map((risk) => (
                      <AdmetRiskCard key={risk.risk_id ?? risk.category} risk={risk} />
                    ))}
                  </div>
                </div>

                <div className="space-y-3 rounded-lg border border-cyan-100 bg-cyan-50/40 p-4">
                  <div className="text-sm font-semibold text-slate-950">高风险分子</div>
                  <div className="space-y-2">
                    {(admetOverview?.high_risk_molecules ?? []).slice(0, 5).map((item) => (
                      <AdmetSummaryCard key={item.molecule_id} item={item} />
                    ))}
                  </div>
                </div>
              </div>
            </Panel>

            <Panel title="合成路线" icon={<Route className="h-4 w-4" />}>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Metric
                  label="找到路线"
                  value={synthesisOverview?.route_found_count ?? 0}
                  tone="emerald"
                />
                <Metric
                  label="未找到"
                  value={synthesisOverview?.route_missing_count ?? 0}
                  tone="rose"
                />
                <Metric
                  label="平均步数"
                  value={synthesisOverview?.average_route_steps ?? 0}
                  tone="sky"
                />
                <Metric
                  label="平均置信度"
                  value={synthesisOverview?.average_route_confidence ?? 0}
                  tone="amber"
                />
              </div>
              <div className="mt-4 overflow-x-auto rounded-lg border border-cyan-100">
                <table className="min-w-full text-sm">
                  <thead className="bg-cyan-50/60">
                    <tr className="border-b border-cyan-100 text-left text-slate-700">
                      <th className="px-3 py-2">分子</th>
                      <th className="px-3 py-2">结果</th>
                      <th className="px-3 py-2">步数</th>
                      <th className="px-3 py-2">置信度</th>
                      <th className="px-3 py-2">可购砌块</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(synthesisOverview?.routes ?? []).map((route) => (
                      <tr key={route.molecule_id} className="border-b border-cyan-50">
                        <td className="px-3 py-2 font-medium text-slate-900">{route.molecule_id}</td>
                        <td className="px-3 py-2">
                          <StatusChip tone={route.route_found ? 'emerald' : 'slate'}>
                            {route.route_found ? '找到' : '未找到'}
                          </StatusChip>
                        </td>
                        <td className="px-3 py-2">{route.route_steps ?? '-'}</td>
                        <td className="px-3 py-2">{formatNumber(route.route_confidence, 3)}</td>
                        <td className="px-3 py-2">{route.buyable_building_blocks ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-4">
                <div className="mb-3 text-sm font-semibold text-slate-950">路线蓝图</div>
                <div className="grid gap-3 xl:grid-cols-2">
                  {(synthesisOverview?.routes ?? []).slice(0, 6).map((route) => (
                    <SynthesisRouteCard key={route.molecule_id} route={route} />
                  ))}
                  {(synthesisOverview?.routes ?? []).length === 0 && (
                    <div className="text-sm text-slate-500">暂无合成路线。</div>
                  )}
                </div>
              </div>
            </Panel>
          </div>

          <aside className="space-y-6">
            <Panel title="报告概览" icon={<Activity className="h-4 w-4" />}>
              <div className="space-y-3">
                <InfoGrid
                  items={[
                    ['项目 ID', summary.project_id],
                    ['状态', summary.status],
                    ['目标', targetName],
                    ['候选排名', candidateSummary.ranking_count],
                    ['决策卡', candidateSummary.decision_card_count ?? 0],
                    ['推理轨迹', candidateSummary.reasoning_trace_count ?? 0],
                  ]}
                />
                <div className="rounded-lg border border-cyan-100 bg-cyan-50/50 p-3 text-sm text-slate-600">
                  这个报告已经把靶点、口袋、SAR、ADMET 和合成路线聚合到同一个视图里，适合继续往前端的交互层扩展。
                </div>
              </div>
            </Panel>

            <Panel title="Top 候选摘要" icon={<CheckCircle2 className="h-4 w-4" />}>
              {topCandidate ? (
                <div className="space-y-3">
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-semibold text-emerald-900">
                        #{topCandidate.rank} {topCandidate.molecule_id}
                      </div>
                      <StatusChip tone={decisionTone(topCandidate.final_decision)}>
                        {topCandidate.final_decision}
                      </StatusChip>
                    </div>
                    <div className="mt-2 text-xs text-slate-600">
                      总分 {formatNumber(topCandidate.overall_score, 2)}
                    </div>
                    <div className="mt-3 rounded bg-white px-2 py-1 font-mono text-xs text-slate-700">
                      {shortSmiles(topCandidate.smiles)}
                    </div>
                  </div>
                  <div className="space-y-2 text-sm">
                    <MiniLine label="SAR 结果" value={topCandidate.rule_filter?.[0]?.decision ?? '未评估'} />
                    <MiniLine
                      label="ADMET"
                      value={topCandidate.admet?.hERG?.risk ?? topCandidate.admet?.Ames?.risk ?? '未评估'}
                    />
                    <MiniLine
                      label="合成"
                      value={topCandidate.synthesis?.route_found ? '已找到路线' : '未找到路线'}
                    />
                  </div>
                </div>
              ) : (
                <div className="text-sm text-slate-500">暂无候选分子。</div>
              )}
            </Panel>
          </aside>
        </section>

        <Panel title="Top 候选列表" icon={<GitBranch className="h-4 w-4" />}>
          {report.top_candidates.length === 0 ? (
            <div className="text-sm text-slate-500">暂无排名结果。</div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-cyan-100">
              <table className="min-w-full text-sm">
                <thead className="bg-cyan-50/60">
                  <tr className="border-b border-cyan-100 text-left text-slate-700">
                    <th className="px-3 py-2">排名</th>
                    <th className="px-3 py-2">分子</th>
                    <th className="px-3 py-2">得分</th>
                    <th className="px-3 py-2">决策</th>
                    <th className="px-3 py-2">SAR</th>
                    <th className="px-3 py-2">ADMET</th>
                    <th className="px-3 py-2">合成</th>
                  </tr>
                </thead>
                <tbody>
                  {report.top_candidates.slice(0, 20).map((candidate) => (
                    <CandidateRow key={candidate.molecule_id} projectId={projectId} candidate={candidate} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </main>
    </div>
  );
}

function Panel({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-cyan-100 bg-white p-6 shadow-sm shadow-cyan-950/5">
      <div className="mb-4 flex items-center gap-2 text-base font-semibold text-slate-950">
        <span className="text-cyan-700">{icon}</span>
        {title}
      </div>
      {children}
    </section>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: 'slate' | 'cyan' | 'emerald' | 'sky' | 'amber' | 'rose';
}) {
  const tones = {
    slate: 'border-slate-200 bg-slate-50 text-slate-900',
    cyan: 'border-cyan-200 bg-cyan-50 text-cyan-800',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    sky: 'border-sky-200 bg-sky-50 text-sky-800',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    rose: 'border-rose-200 bg-rose-50 text-rose-800',
  };

  return (
    <div className={cn('rounded-lg border p-4', tones[tone])}>
      <div className="text-xs font-medium opacity-80">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium', statusTone(status))}>
      {status}
    </span>
  );
}

function StatusChip({
  tone,
  children,
}: {
  tone: 'emerald' | 'slate' | 'amber' | 'rose' | 'cyan';
  children: ReactNode;
}) {
  const tones = {
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    rose: 'border-rose-200 bg-rose-50 text-rose-800',
    cyan: 'border-cyan-200 bg-cyan-50 text-cyan-800',
  };

  return <span className={cn('inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium', tones[tone])}>{children}</span>;
}

function InfoGrid({ items }: { items: Array<[string, ReactNode]> }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-lg border border-cyan-100 bg-cyan-50/30 p-3">
          <div className="text-xs font-medium text-slate-500">{label}</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{value}</div>
        </div>
      ))}
    </div>
  );
}

function BindingSiteCard({ site }: { site: TargetBindingSite }) {
  return (
    <div className="rounded-lg border border-cyan-100 bg-cyan-50/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-950">{site.site_name ?? site.binding_site_id}</div>
        {site.pdb_id && <StatusChip tone="cyan">{site.pdb_id}</StatusChip>}
      </div>
      <div className="mt-2 space-y-1 text-xs text-slate-600">
        {site.reference_ligand && <div>参考配体：{site.reference_ligand}</div>}
        {site.grid_box?.center && <div>中心：{formatVector(site.grid_box.center)}</div>}
        {site.grid_box?.size && <div>尺寸：{formatVector(site.grid_box.size)}</div>}
      </div>
      {site.key_residues && site.key_residues.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {site.key_residues.slice(0, 5).map((residue) => (
            <span key={residue} className="rounded bg-white px-1.5 py-0.5 text-[11px] text-emerald-800">
              {residue}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function SeedLigandCard({ ligand }: { ligand: ReportSeedLigand }) {
  return (
    <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 p-3">
      <div className="text-sm font-semibold text-slate-950">{ligand.name ?? ligand.ligand_id}</div>
      <div className="mt-1 text-[11px] text-slate-500">{ligand.source ?? 'builtin_target_library'}</div>
      <div className="mt-2 rounded bg-white px-2 py-1 font-mono text-[11px] text-slate-700">
        {shortSmiles(ligand.smiles)}
      </div>
    </div>
  );
}

function RuleCard({ rule }: { rule: TargetSarRule }) {
  return (
    <div className="rounded-lg border border-cyan-100 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-950">{rule.title}</div>
          {rule.evidence_level && <div className="mt-1 text-xs text-cyan-700">{rule.evidence_level}</div>}
        </div>
        {rule.rule_id && <StatusChip tone="cyan">{rule.rule_id}</StatusChip>}
      </div>
      <div className="mt-2 grid gap-2 text-sm text-slate-600">
        {rule.rationale && <div>{rule.rationale}</div>}
        {rule.preferred_change && <div><span className="font-medium text-emerald-800">建议：</span>{rule.preferred_change}</div>}
        {rule.avoid && <div><span className="font-medium text-rose-800">避免：</span>{rule.avoid}</div>}
      </div>
    </div>
  );
}

function RuleFindingCard({ finding }: { finding: RuleFilterSummary }) {
  return (
    <div className="rounded-lg border border-cyan-100 bg-white p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold text-slate-900">{finding.molecule_id}</div>
        <StatusChip tone={decisionTone(finding.decision)}>{finding.decision}</StatusChip>
      </div>
      <div className="mt-1 text-slate-600">规则集：{finding.rule_set}</div>
      {finding.failed_rules.length > 0 && <div className="mt-1 text-slate-600">失败规则：{finding.failed_rules.join('，')}</div>}
      {finding.labels.length > 0 && <div className="mt-1 text-slate-600">标签：{finding.labels.join('，')}</div>}
    </div>
  );
}

function CountList({ title, counts }: { title: string; counts?: Record<string, number> }) {
  const entries = Object.entries(counts ?? {});
  return (
    <div>
      <div className="text-sm font-semibold text-slate-950">{title}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {entries.length > 0 ? entries.map(([label, count]) => <StatusChip key={label} tone="slate">{label} {count}</StatusChip>) : (
          <span className="text-sm text-slate-500">暂无</span>
        )}
      </div>
    </div>
  );
}

function AdmetRiskCard({ risk }: { risk: TargetAdmetRisk }) {
  return (
    <div className="rounded-lg border border-amber-100 bg-amber-50/50 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-950">{risk.category}</div>
        {risk.severity && <StatusChip tone={risk.severity === 'high' ? 'rose' : 'amber'}>{risk.severity}</StatusChip>}
      </div>
      {risk.signal && <div className="mt-2 text-sm leading-6 text-slate-600">{risk.signal}</div>}
      {risk.mitigation && <div className="mt-2 text-xs leading-5 text-emerald-800">缓解：{risk.mitigation}</div>}
    </div>
  );
}

function AdmetSummaryCard({ item }: { item: AdmetSummary }) {
  return (
    <div className="rounded-lg border border-cyan-100 bg-white p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold text-slate-900">{item.molecule_id}</div>
        <StatusChip tone={decisionTone(item.hERG?.risk ?? item.Ames?.risk ?? 'unknown')}>
          {item.hERG?.risk ?? item.Ames?.risk ?? 'unknown'}
        </StatusChip>
      </div>
      <div className="mt-1 text-slate-600">hERG：{item.hERG?.risk ?? '-'}</div>
      <div className="mt-1 text-slate-600">Ames：{item.Ames?.risk ?? '-'}</div>
      <div className="mt-1 text-slate-600">溶解度：{item.solubility ?? '-'}</div>
    </div>
  );
}

function SynthesisRouteCard({ route }: { route: SynthesisSummary }) {
  const plan = route.route_plan ?? [];
  return (
    <div className="rounded-lg border border-cyan-100 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-950">{route.molecule_id}</div>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            {route.route_summary ?? (route.route_found ? '已找到代理路线。' : '未找到可信代理路线。')}
          </p>
        </div>
        <StatusChip tone={route.route_found ? 'emerald' : 'rose'}>
          {route.route_found ? '可合成' : '需重设'}
        </StatusChip>
      </div>
      {route.starting_materials && route.starting_materials.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {route.starting_materials.map((material) => (
            <span key={material} className="rounded-md bg-cyan-50 px-2 py-0.5 text-[11px] text-cyan-800">
              {material}
            </span>
          ))}
        </div>
      )}
      {plan.length > 0 && (
        <div className="mt-3 space-y-2">
          {plan.map((step) => (
            <div key={`${route.molecule_id}-${step.step}`} className="rounded-lg border border-cyan-50 bg-cyan-50/40 p-3">
              <div className="text-xs font-semibold text-cyan-900">
                Step {step.step}: {step.stage}
              </div>
              <div className="mt-1 text-xs leading-5 text-slate-600">{step.operation}</div>
              <div className="mt-1 text-[11px] text-slate-500">输出: {step.output}</div>
            </div>
          ))}
        </div>
      )}
      {route.route_risks && route.route_risks.length > 0 && (
        <div className="mt-3 space-y-1 text-xs text-amber-800">
          {route.route_risks.map((risk) => (
            <div key={risk}>风险: {risk}</div>
          ))}
        </div>
      )}
      {route.route_note && <div className="mt-3 text-[11px] leading-5 text-slate-500">{route.route_note}</div>}
    </div>
  );
}

function CandidateRow({
  projectId,
  candidate,
}: {
  projectId: string;
  candidate: ReportCandidate;
}) {
  return (
    <tr className="border-b border-cyan-50 hover:bg-cyan-50/30">
      <td className="px-3 py-2 font-medium text-slate-900">#{candidate.rank}</td>
      <td className="px-3 py-2">
        <Link to={`/workspace/${projectId}/molecules/${candidate.molecule_id}`} className="text-cyan-700 hover:underline">
          {candidate.molecule_id}
        </Link>
        <div className="mt-1 max-w-md truncate font-mono text-[11px] text-slate-500">{shortSmiles(candidate.smiles)}</div>
      </td>
      <td className="px-3 py-2 text-slate-700">{formatNumber(candidate.overall_score, 2)}</td>
      <td className="px-3 py-2">
        <StatusChip tone={decisionTone(candidate.final_decision)}>{candidate.final_decision}</StatusChip>
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {candidate.rule_filter?.length ? (
            <StatusChip tone="cyan">{candidate.rule_filter[0].decision}</StatusChip>
          ) : (
            <span className="text-slate-500">-</span>
          )}
        </div>
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {candidate.admet?.hERG?.risk && <StatusChip tone={decisionTone(candidate.admet.hERG.risk)}>{candidate.admet.hERG.risk}</StatusChip>}
          {!candidate.admet?.hERG?.risk && <span className="text-slate-500">-</span>}
        </div>
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {candidate.synthesis ? (
            <StatusChip tone={candidate.synthesis.route_found ? 'emerald' : 'slate'}>
              {candidate.synthesis.route_found ? `${candidate.synthesis.route_steps ?? '-'} 步` : '未找到'}
            </StatusChip>
          ) : (
            <span className="text-slate-500">-</span>
          )}
        </div>
      </td>
    </tr>
  );
}

function MiniLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-cyan-100 bg-white px-3 py-2">
      <span className="text-slate-500">{label}</span>
      <span className="font-medium text-slate-900">{value}</span>
    </div>
  );
}

function Badge({ children, tone }: { children: ReactNode; tone: 'cyan' | 'emerald' | 'slate' | 'amber' | 'rose' }) {
  const tones = {
    cyan: 'border-cyan-200 bg-cyan-50 text-cyan-800',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    rose: 'border-rose-200 bg-rose-50 text-rose-800',
  };

  return (
    <span className={cn('inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium', tones[tone])}>
      {children}
    </span>
  );
}

function statusTone(status: string) {
  const normalized = status.toLowerCase();
  if (normalized.includes('completed') || normalized.includes('pass') || normalized.includes('recommend') || normalized.includes('found')) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-800';
  }
  if (normalized.includes('failed') || normalized.includes('reject') || normalized.includes('high_risk')) {
    return 'border-rose-200 bg-rose-50 text-rose-800';
  }
  if (normalized.includes('running') || normalized.includes('warn') || normalized.includes('reserve')) {
    return 'border-amber-200 bg-amber-50 text-amber-800';
  }
  return 'border-cyan-200 bg-cyan-50 text-cyan-800';
}

function shortSmiles(smiles: string | null) {
  if (!smiles) return '-';
  return smiles.length > 64 ? `${smiles.slice(0, 64)}...` : smiles;
}

function formatVector(values?: number[] | null) {
  if (!values?.length) return '-';
  return values.map((value) => value.toFixed(2)).join(', ');
}

function safeFilename(value: string) {
  return value
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\s+/g, '_')
    .replace(/^_+|_+$/g, '') || 'project';
}

function getRiskCount(counts: Record<string, Record<string, number>> | undefined, key: string) {
  if (!counts?.[key]) return 0;
  return Object.values(counts[key]).reduce((sum, value) => sum + value, 0);
}
