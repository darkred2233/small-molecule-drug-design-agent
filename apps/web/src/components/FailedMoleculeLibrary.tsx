import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ExternalLink, FlaskConical, ShieldX } from 'lucide-react';
import { moleculesApi } from '@/api';
import type { Molecule, RuleFilterSummary } from '@/types/api';
import { cn, getStatusColor } from '@/utils/helpers';

const FAILURE_STATUSES = new Set(['failed_filter', 'invalid_structure', 'critic_rejected']);
const PASS_DECISIONS = new Set(['passed', 'passed_with_warnings']);

export default function FailedMoleculeLibrary() {
  const { projectId } = useParams();
  const [reasonFilter, setReasonFilter] = useState('all');

  const { data: molecules } = useQuery({
    queryKey: ['molecules', projectId],
    queryFn: () => moleculesApi.list(projectId!),
    enabled: !!projectId,
  });

  const { data: filterResults } = useQuery({
    queryKey: ['rule-filter-results', projectId],
    queryFn: () => moleculesApi.getRuleFilterResults(projectId!),
    enabled: !!projectId,
  });

  const summary = useMemo(
    () => buildFailureSummary(molecules ?? [], filterResults ?? []),
    [molecules, filterResults]
  );

  const reasonOptions = useMemo(() => {
    const reasons = new Set<string>();
    summary.failedMolecules.forEach((item) => item.reasons.forEach((reason) => reasons.add(reason)));
    return ['all', ...Array.from(reasons).sort()];
  }, [summary.failedMolecules]);

  const visibleFailures = useMemo(() => {
    if (reasonFilter === 'all') return summary.failedMolecules;
    return summary.failedMolecules.filter((item) => item.reasons.includes(reasonFilter));
  }, [reasonFilter, summary.failedMolecules]);

  if (!molecules || !filterResults) {
    return (
      <div className="science-card py-8 text-center text-sm text-slate-500">
        <FlaskConical className="mx-auto mb-3 h-9 w-9 animate-pulse text-cyan-200" />
        正在读取筛选结果
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <FailureMetric label="总候选" value={summary.totalCount} tone="slate" />
        <FailureMetric label="通过" value={summary.passedCount} tone="emerald" />
        <FailureMetric label="带警告通过" value={summary.warningCount} tone="amber" />
        <FailureMetric label="被筛除" value={summary.failedCount} tone="rose" />
      </div>

      <div className="rounded-lg border border-cyan-100 bg-cyan-50/50 p-3 text-xs leading-5 text-slate-600">
        失败库只收纳硬性规则失败、结构无效或被反驳淘汰的分子；带 SAR/ADMET 警告但仍可继续优化的分子不会算作筛除。
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-slate-600">原因筛选:</span>
        {reasonOptions.map((reason) => (
          <button
            key={reason}
            onClick={() => setReasonFilter(reason)}
            className={cn(
              'rounded-full px-3 py-1 text-xs font-medium transition-colors',
              reasonFilter === reason
                ? 'bg-rose-600 text-white shadow-sm shadow-rose-900/20'
                : 'border border-rose-100 bg-white text-slate-700 hover:bg-rose-50'
            )}
          >
            {reason === 'all' ? '全部原因' : reason}
          </button>
        ))}
      </div>

      {visibleFailures.length === 0 ? (
        <div className="science-card py-10 text-center text-sm text-slate-500">
          <ShieldX className="mx-auto mb-3 h-10 w-10 text-emerald-300" />
          <p className="font-medium text-slate-700">暂无被硬筛除的分子</p>
          <p className="mt-1 text-xs">当前筛选结果主要是通过或警告通过。</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-rose-100 bg-white shadow-sm shadow-rose-950/5">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-rose-100 bg-rose-50/70">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-slate-700">分子 ID</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-700">状态</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-700">失败原因</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-700">SMILES</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-700">操作</th>
                </tr>
              </thead>
              <tbody>
                {visibleFailures.map(({ molecule, result, reasons }) => (
                  <tr key={molecule.molecule_id} className="border-b border-rose-50 hover:bg-rose-50/40">
                    <td className="px-4 py-3">
                      <code className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">
                        {molecule.molecule_id}
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn('rounded-full px-2.5 py-1 text-xs font-medium', getStatusColor(molecule.status))}>
                        {result?.decision ?? molecule.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {reasons.map((reason) => (
                          <span key={reason} className="rounded-md border border-rose-100 bg-rose-50 px-2 py-0.5 text-[11px] font-medium text-rose-700">
                            {reason}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <code className="block max-w-md truncate text-xs text-slate-600">{molecule.smiles}</code>
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        to={`/workspace/${projectId}/molecules/${molecule.molecule_id}`}
                        className="inline-flex items-center gap-1 text-cyan-700 hover:text-cyan-800"
                      >
                        查看详情
                        <ExternalLink className="h-3 w-3" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-amber-100 bg-amber-50/60 p-3 text-xs leading-5 text-amber-800">
        <div className="mb-1 flex items-center gap-2 font-semibold">
          <AlertTriangle className="h-4 w-4" />
          筛选严谨性
        </div>
        当前硬筛规则来自 Lipinski/Veber 极限、结构有效性和 RDKit 警报；靶点允许的药效团警报会保留为警告，避免把可优化的 HDAC/药化候选过早淘汰。
      </div>
    </div>
  );
}

function FailureMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: 'slate' | 'emerald' | 'amber' | 'rose';
}) {
  const tones = {
    slate: 'border-slate-200 bg-slate-50 text-slate-900',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-800',
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

function buildFailureSummary(molecules: Molecule[], filterResults: RuleFilterSummary[]) {
  const resultByMolecule = new Map<string, RuleFilterSummary>();
  filterResults.forEach((result) => resultByMolecule.set(result.molecule_id, result));

  const failedMolecules = molecules
    .map((molecule) => {
      const result = resultByMolecule.get(molecule.molecule_id);
      const failedByDecision = result ? !PASS_DECISIONS.has(result.decision) : false;
      const failedByStatus = FAILURE_STATUSES.has(molecule.status);
      if (!failedByDecision && !failedByStatus) return null;
      return {
        molecule,
        result,
        reasons: failureReasons(molecule, result),
      };
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item));

  const warningCount = filterResults.filter((result) => result.decision === 'passed_with_warnings').length;
  const passedCount = filterResults.filter((result) => PASS_DECISIONS.has(result.decision)).length;

  return {
    totalCount: molecules.length,
    passedCount,
    warningCount,
    failedCount: failedMolecules.length,
    failedMolecules,
  };
}

function failureReasons(molecule: Molecule, result?: RuleFilterSummary) {
  const reasons = new Set<string>();
  result?.failed_rules?.forEach((rule) => reasons.add(rule));
  if (result?.decision === 'skipped_invalid_structure' || molecule.status === 'invalid_structure') {
    reasons.add('结构校验失败');
  }
  if (result?.decision === 'needs_properties') {
    reasons.add('缺少物化性质');
  }
  if (molecule.status === 'critic_rejected') {
    reasons.add('自我反驳淘汰');
  }
  if (reasons.size === 0 && result?.decision) {
    reasons.add(result.decision);
  }
  if (reasons.size === 0) {
    reasons.add(molecule.status);
  }
  return Array.from(reasons);
}
