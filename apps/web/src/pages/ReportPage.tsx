import { type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  ArrowLeft,
  BookOpen,
  Box,
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
  PoseCoordinates,
  ProjectReport,
  ReportCandidate,
  ReportEvidenceLink,
  ReportSeedLigand,
  RuleFilterSummary,
  SynthesisSummary,
  TargetAdmetRisk,
  TargetBindingSite,
  TargetSarRule,
} from '@/types/api';
import { cn, formatNumber } from '@/utils/helpers';
import {
  bestPoseConfirmed,
  decisionTone,
  evidenceExcerpt,
  formatBestPose,
  formatEvidenceCitation,
  formatEvidenceSourceLabel,
  poseFilename,
} from '@/utils/reportPresentation';

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

          {report.final_report?.executive_summary?.length ? (
            <div className="mt-5 rounded-lg border border-cyan-100 bg-cyan-50/40 p-4">
              <div className="text-sm font-semibold text-cyan-900">最终中文摘要</div>
              <ul className="mt-2 space-y-2 text-sm leading-6 text-slate-700">
                {report.final_report.executive_summary.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
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
                  label="未外部确认"
                  value={synthesisOverview?.route_missing_count ?? 0}
                  tone="amber"
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
                    {(synthesisOverview?.routes ?? []).map((route) => {
                      const status = synthesisStatus(route);
                      return (
                        <tr key={route.molecule_id} className="border-b border-cyan-50">
                          <td className="px-3 py-2 font-medium text-slate-900">{route.molecule_id}</td>
                          <td className="px-3 py-2">
                            <StatusChip tone={status.tone}>{status.label}</StatusChip>
                          </td>
                          <td className="px-3 py-2">{route.route_steps ?? route.estimated_route_steps ?? '-'}</td>
                          <td className="px-3 py-2">
                            {formatNumber(route.route_confidence ?? route.estimated_route_confidence, 3)}
                          </td>
                          <td className="px-3 py-2">
                            {route.buyable_building_blocks ?? route.estimated_buyable_building_blocks ?? '-'}
                          </td>
                        </tr>
                      );
                    })}
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
                  {report.final_report?.title ??
                    '这个报告已经把靶点、口袋、SAR、ADMET 和合成路线聚合到同一个视图里。'}
                </div>
                {report.final_report?.next_steps?.length ? (
                  <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 p-3">
                    <div className="text-sm font-semibold text-emerald-900">下一步建议</div>
                    <ul className="mt-2 space-y-1 text-xs leading-5 text-slate-700">
                      {report.final_report.next_steps.slice(0, 4).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
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
                    {topCandidate.narrative?.summary && (
                      <p className="mt-3 text-sm leading-6 text-emerald-950">
                        {topCandidate.narrative.summary}
                      </p>
                    )}
                  </div>
                  <div className="space-y-2 text-sm">
                    <MiniLine label="正向证据分" value={formatNumber(topCandidate.pro_score, 2)} />
                    <MiniLine label="风险证据分" value={formatNumber(topCandidate.con_score, 2)} />
                    <MiniLine
                      label="证据完整度"
                      value={formatNumber(topCandidate.evidence_confidence, 3)}
                    />
                    <MiniLine label="SAR 结果" value={topCandidate.rule_filter?.[0]?.decision ?? '未评估'} />
                    <MiniLine
                      label="ADMET"
                      value={topCandidate.admet?.hERG?.risk ?? topCandidate.admet?.Ames?.risk ?? '未评估'}
                    />
                    <MiniLine
                      label="ADMET 计算"
                      value={formatAdmetRuntime(topCandidate.admet)}
                    />
                    <MiniLine label="最佳 Pose" value={formatBestPose(topCandidate.docking)} />
                    <MiniLine
                      label="合成"
                      value={topCandidate.synthesis ? synthesisStatus(topCandidate.synthesis).detail : '未评估'}
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
                    <th className="px-3 py-2">生成方式</th>
                    <th className="px-3 py-2">得分</th>
                    <th className="px-3 py-2">决策</th>
                    <th className="px-3 py-2">最佳 Pose</th>
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

        <Panel title="Top5 分子详情" icon={<CheckCircle2 className="h-4 w-4" />}>
          {report.top_candidates.length === 0 ? (
            <div className="text-sm text-slate-500">暂无排名结果。</div>
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              {report.top_candidates.slice(0, 5).map((candidate) => (
                <TopCandidateDetailCard
                  key={`${candidate.molecule_id}-detail`}
                  projectId={projectId}
                  candidate={candidate}
                />
              ))}
            </div>
          )}
        </Panel>

        <Panel title="最佳 Pose 与文献证据" icon={<BookOpen className="h-4 w-4" />}>
          {report.top_candidates.length === 0 ? (
            <div className="text-sm text-slate-500">暂无候选证据。</div>
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              {report.top_candidates.slice(0, 10).map((candidate) => (
                <CandidateEvidenceCard
                  key={`${candidate.molecule_id}-evidence`}
                  projectId={projectId}
                  candidate={candidate}
                />
              ))}
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

type ChipTone = 'emerald' | 'slate' | 'amber' | 'rose' | 'cyan';

function StatusChip({
  tone,
  children,
}: {
  tone: ChipTone;
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
  const status = synthesisStatus(route);
  return (
    <div className="rounded-lg border border-cyan-100 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-950">{route.molecule_id}</div>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            {route.route_summary ?? (route.route_found ? '已找到代理路线。' : '未找到可信代理路线。')}
          </p>
        </div>
        <StatusChip tone={status.tone}>{status.cardLabel}</StatusChip>
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

function TopCandidateDetailCard({
  projectId,
  candidate,
}: {
  projectId: string;
  candidate: ReportCandidate;
}) {
  const synthesis = candidate.synthesis ? synthesisStatus(candidate.synthesis) : null;

  return (
    <article className="rounded-lg border border-cyan-100 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-950">
            #{candidate.rank} {candidate.molecule_id}
          </div>
          <div className="mt-1 max-w-full truncate font-mono text-[11px] text-slate-500">
            {shortSmiles(candidate.smiles)}
          </div>
        </div>
        <StatusChip tone={decisionTone(candidate.final_decision)}>
          {candidate.final_decision}
        </StatusChip>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Datum label="总分" value={formatNumber(candidate.overall_score, 2)} />
        <Datum label="证据完整度" value={formatNumber(candidate.evidence_confidence, 3)} />
        <Datum label="最佳 Pose" value={formatBestPose(candidate.docking)} />
        <Datum label="合成" value={synthesis?.detail ?? '未评估'} />
      </div>

      <MoleculeNarrativeBlock candidate={candidate} />
      <CandidateEvidenceBlock projectId={projectId} candidate={candidate} />
    </article>
  );
}

function MoleculeNarrativeBlock({ candidate }: { candidate: ReportCandidate }) {
  const narrative = candidate.narrative;
  if (!narrative) {
    return null;
  }

  return (
    <section className="mt-4 rounded-lg border border-emerald-100 bg-emerald-50/40 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold text-emerald-900">中文解读</div>
        <StatusChip tone="emerald">
          {narrative.evidence_refs.length} 条证据
        </StatusChip>
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-700">{narrative.summary}</p>
      {narrative.why_it_matters && (
        <p className="mt-2 text-xs leading-5 text-slate-600">{narrative.why_it_matters}</p>
      )}
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <NarrativeList title="优势" items={narrative.strengths} tone="emerald" />
        <NarrativeList title="风险" items={narrative.risks} tone="amber" />
        <NarrativeList title="下一轮" items={narrative.next_round_suggestions} tone="cyan" />
      </div>
      {narrative.evidence_refs.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {narrative.evidence_refs.slice(0, 5).map((item, index) => (
            <Badge key={`${item.type}-${item.source ?? index}`} tone="slate">
              {formatNarrativeEvidenceType(item.type)}
            </Badge>
          ))}
        </div>
      )}
    </section>
  );
}

function NarrativeList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: 'cyan' | 'emerald' | 'amber';
}) {
  return (
    <div>
      <div className="mb-1">
        <Badge tone={tone}>{title}</Badge>
      </div>
      {items.length ? (
        <ul className="space-y-1 text-xs leading-5 text-slate-600">
          {items.slice(0, 3).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <div className="text-xs text-slate-500">暂无</div>
      )}
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
      <td className="px-3 py-2">
        <StatusChip tone="slate">{formatGenerationMethod(candidate.generation_method)}</StatusChip>
      </td>
      <td className="px-3 py-2 text-slate-700">
        <div>{formatNumber(candidate.overall_score, 2)}</div>
        <div className="mt-1 whitespace-nowrap text-[11px] text-slate-500">
          正向 {formatNumber(candidate.pro_score, 1)} / 风险 {formatNumber(candidate.con_score, 1)}
        </div>
        <div className="whitespace-nowrap text-[11px] text-slate-500">
          证据 {formatNumber(candidate.evidence_confidence, 2)}
        </div>
      </td>
      <td className="px-3 py-2">
        <StatusChip tone={decisionTone(candidate.final_decision)}>{candidate.final_decision}</StatusChip>
      </td>
      <td className="px-3 py-2 text-xs text-slate-700">
        <div className="max-w-48 whitespace-normal leading-5">{formatBestPose(candidate.docking)}</div>
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
        {candidate.admet?.compute_device && (
          <div className="mt-1 text-[11px] uppercase text-slate-500">
            {candidate.admet.compute_device}
          </div>
        )}
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {candidate.synthesis ? (
            <StatusChip tone={synthesisStatus(candidate.synthesis).tone}>
              {synthesisStatus(candidate.synthesis).compact}
            </StatusChip>
          ) : (
            <span className="text-slate-500">-</span>
          )}
        </div>
      </td>
    </tr>
  );
}

function CandidateEvidenceCard({
  projectId,
  candidate,
}: {
  projectId: string;
  candidate: ReportCandidate;
}) {
  return (
    <article className="rounded-lg border border-cyan-100 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-950">
            #{candidate.rank} {candidate.molecule_id}
          </div>
          <div className="mt-1 max-w-full truncate font-mono text-[11px] text-slate-500">
            {shortSmiles(candidate.smiles)}
          </div>
        </div>
        <StatusChip tone={decisionTone(candidate.final_decision)}>
          {candidate.final_decision}
        </StatusChip>
      </div>

      <CandidateEvidenceBlock projectId={projectId} candidate={candidate} />
    </article>
  );
}

function CandidateEvidenceBlock({
  projectId,
  candidate,
}: {
  projectId: string;
  candidate: ReportCandidate;
}) {
  const evidence = candidate.evidence_chain ?? [];
  return (
    <div className="mt-4 space-y-4">
      <BestPoseCard projectId={projectId} candidate={candidate} />
      <EvidenceList evidence={evidence} />
    </div>
  );
}

function BestPoseCard({
  projectId,
  candidate,
}: {
  projectId: string;
  candidate: ReportCandidate;
}) {
  const docking = candidate.docking;
  if (!docking) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500">
        暂无对接 Pose
      </div>
    );
  }

  const confirmed = bestPoseConfirmed(docking);
  const canDownload = confirmed && Boolean(docking.pose_file);

  return (
    <div className="rounded-lg border border-cyan-100 bg-cyan-50/30 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold text-cyan-800">
            <Box className="h-3.5 w-3.5" />
            最佳 Pose
          </div>
          <div className="mt-1 text-sm font-semibold leading-5 text-slate-950">
            {formatBestPose(docking)}
          </div>
        </div>
        <StatusChip tone={confirmed ? 'emerald' : 'amber'}>
          {confirmed ? '已确认' : '未确认'}
        </StatusChip>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Datum label="Pose 文件" value={poseFilename(docking.pose_file) || '-'} mono />
        <Datum label="选择方法" value={docking.pose_selection_method ?? '-'} />
        <Datum
          label="Pose 排名"
          value={docking.selected_pose_rank == null ? '-' : `#${docking.selected_pose_rank}`}
        />
        <Datum label="文件状态" value={docking.pose_artifact_available ? '可用' : '不可用'} />
      </div>

      {docking.pose_file && (
        <div
          className="mt-3 truncate rounded-md bg-white px-2 py-1 font-mono text-[11px] text-slate-500"
          title={docking.pose_file}
        >
          {docking.pose_file}
        </div>
      )}

      <PoseCoordinateTable coordinates={docking.pose_coordinates} />

      {canDownload && (
        <a
          href={reportsApi.poseDownloadUrl(projectId, candidate.molecule_id)}
          download={`${candidate.molecule_id}_best_pose`}
          className="mt-3 inline-flex items-center gap-2 rounded-md border border-cyan-200 bg-white px-3 py-1.5 text-xs font-medium text-cyan-800 hover:border-cyan-300 hover:bg-cyan-50"
        >
          <Download className="h-3.5 w-3.5" />
          下载 Pose
        </a>
      )}
    </div>
  );
}

function PoseCoordinateTable({ coordinates }: { coordinates?: PoseCoordinates | null }) {
  const atoms = coordinates?.atoms ?? [];
  if (atoms.length === 0) {
    return null;
  }

  return (
    <section className="mt-3 overflow-hidden rounded-md border border-cyan-100 bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-cyan-100 px-3 py-2">
        <div>
          <h5 className="text-xs font-semibold text-slate-700">最佳 Pose XYZ 坐标</h5>
          <div className="mt-0.5 text-[11px] text-slate-500">
            {coordinates?.format?.toUpperCase()} · {coordinates?.atom_count ?? atoms.length} atoms
          </div>
        </div>
        {coordinates?.truncated && (
          <div className="text-right text-[11px] text-amber-700">
            仅显示前 {coordinates.returned_atom_count} / {coordinates.atom_count} 个原子
          </div>
        )}
      </div>
      <div className="max-h-72 overflow-auto">
        <table className="w-full min-w-[360px] text-left text-[11px]">
          <thead className="sticky top-0 bg-slate-50 text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">Atom</th>
              <th className="px-3 py-2 text-right font-medium">X</th>
              <th className="px-3 py-2 text-right font-medium">Y</th>
              <th className="px-3 py-2 text-right font-medium">Z</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 font-mono text-slate-700">
            {atoms.map((atom) => (
              <tr key={atom.index}>
                <td className="px-3 py-1.5">{atom.index}</td>
                <td className="px-3 py-1.5">{atom.element}</td>
                <td className="px-3 py-1.5 text-right">{formatNumber(atom.x, 4)}</td>
                <td className="px-3 py-1.5 text-right">{formatNumber(atom.y, 4)}</td>
                <td className="px-3 py-1.5 text-right">{formatNumber(atom.z, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function EvidenceList({ evidence }: { evidence: ReportEvidenceLink[] }) {
  if (evidence.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500">
        暂无 RAG 文献证据
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {evidence.slice(0, 4).map((item) => (
        <EvidenceCard key={item.evidence_id} evidence={item} />
      ))}
      {evidence.length > 4 && (
        <div className="text-xs text-slate-500">还有 {evidence.length - 4} 条证据已写入报告 JSON。</div>
      )}
    </div>
  );
}

function EvidenceCard({ evidence }: { evidence: ReportEvidenceLink }) {
  return (
    <div className="rounded-lg border border-cyan-100 bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-950">
            {formatEvidenceSourceLabel(evidence)}
          </div>
          <div className="mt-1 text-xs text-slate-500">{formatEvidenceCitation(evidence)}</div>
        </div>
        <StatusChip tone="cyan">{evidence.claim_type}</StatusChip>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-600">{evidenceExcerpt(evidence)}</p>
      {evidence.rationale && (
        <div className="mt-2 rounded-md bg-cyan-50 px-2 py-1 text-[11px] leading-5 text-cyan-900">
          {evidence.rationale}
        </div>
      )}
      <div className="mt-2 font-mono text-[11px] text-slate-400">{evidence.evidence_id}</div>
    </div>
  );
}

function Datum({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-md bg-white px-2 py-1">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={cn('mt-0.5 truncate text-xs font-medium text-slate-900', mono && 'font-mono')}>
        {value}
      </div>
    </div>
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

function synthesisStatus(route: SynthesisSummary): {
  tone: ChipTone;
  label: string;
  cardLabel: string;
  compact: string;
  detail: string;
} {
  const labels = route.labels ?? [];
  const isSurrogate =
    route.adapter_mode === 'rdkit_surrogate_synthesis' ||
    route.result_kind === 'non_retrosynthesis_coarse_estimate' ||
    labels.includes('rdkit_surrogate_synthesis');
  const steps = route.route_steps ?? route.estimated_route_steps;
  const confidence = route.route_confidence ?? route.estimated_route_confidence;
  const stepText = steps == null ? null : `${steps} 步`;
  const confidenceText = confidence == null ? null : `置信 ${formatNumber(confidence, 2)}`;

  if (route.route_found) {
    return {
      tone: 'emerald',
      label: '找到',
      cardLabel: '可合成',
      compact: stepText ?? '找到',
      detail: ['已找到路线', stepText, confidenceText].filter(Boolean).join(' · '),
    };
  }

  if (isSurrogate) {
    const feasible = route.estimated_route_feasible;
    const label = feasible === true ? '粗筛可行' : '待复核';
    return {
      tone: 'amber',
      label,
      cardLabel: label,
      compact: stepText ? `${label} ${stepText}` : label,
      detail: [label, stepText, confidenceText, '待外部逆合成确认'].filter(Boolean).join(' · '),
    };
  }

  return {
    tone: 'rose',
    label: '未找到',
    cardLabel: '需重设',
    compact: '未找到',
    detail: '未找到可信路线',
  };
}

function formatAdmetRuntime(admet?: AdmetSummary | null) {
  if (!admet) return '未评估';

  const model = admet.model_name ?? admet.tool_name ?? admet.adapter_mode ?? '模型未记录';
  const device = admet.compute_device ? admet.compute_device.toUpperCase() : '设备未记录';
  return `${model} / ${device}`;
}

function formatNarrativeEvidenceType(type: string) {
  const labels: Record<string, string> = {
    ranking_score: '排序',
    docking_pose: 'Pose',
    admet_prediction: 'ADMET',
    synthesis_score: '合成',
    rag_reference: '文献',
  };
  return labels[type] ?? type;
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

function formatGenerationMethod(method?: string | null) {
  if (!method) return '-';
  const labels: Record<string, string> = {
    reinvent4: 'REINVENT4',
    crem: 'CREM',
    autogrow4: 'AutoGrow4',
    seed_ligand_import: '种子导入',
  };
  return labels[method] ?? method;
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
