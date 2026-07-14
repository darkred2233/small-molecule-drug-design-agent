/**
 * Molecule Detail Page
 *
 * Detailed view of a single molecule with all assessment results
 */

import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { assessmentApi, moleculesApi } from '@/api';
import { ArrowLeft, Copy, Download, FlaskConical, Route } from 'lucide-react';
import { formatNumber, getStatusColor, copyToClipboard } from '@/utils/helpers';
import MoleculeStructure from '@/components/MoleculeStructure';
import DecisionCard from '@/components/DecisionCard';
import ReasoningTracePanel from '@/components/ReasoningTracePanel';
import { cn } from '@/utils/helpers';
import type { SynthesisRoute } from '@/types/api';

export default function MoleculeDetailPage() {
  const { projectId, moleculeId } = useParams();

  const { data: molecule } = useQuery({
    queryKey: ['molecule', projectId, moleculeId],
    queryFn: () => moleculesApi.get(projectId!, moleculeId!),
  });

  const { data: properties } = useQuery({
    queryKey: ['molecule-properties', projectId, moleculeId],
    queryFn: () => moleculesApi.getProperties(projectId!, moleculeId!),
    enabled: !!molecule,
  });

  const { data: decisionCards } = useQuery({
    queryKey: ['decision-cards', projectId, moleculeId],
    queryFn: () => moleculesApi.getDecisionCards(projectId!, moleculeId!),
    enabled: !!molecule,
  });

  const { data: synthesisRoutes } = useQuery({
    queryKey: ['synthesis-routes', projectId],
    queryFn: () => assessmentApi.getSynthesisRoutes(projectId!),
    enabled: !!molecule,
  });

  if (!molecule) {
    return (
      <div className="app-shell flex h-screen items-center justify-center">
        <div className="text-slate-500">加载中...</div>
      </div>
    );
  }

  const rotatableBonds =
    properties?.tool_metadata?.rotatable_bond_count ??
    properties?.tool_metadata?.rotatable_bonds ??
    properties?.tool_metadata?.RotB;
  const qed = properties?.tool_metadata?.qed ?? properties?.tool_metadata?.QED;
  const synthesisRoute = synthesisRoutes?.find((route) => route.molecule_id === molecule.molecule_id);

  const handleCopySmiles = () => {
    copyToClipboard(molecule.smiles);
  };

  return (
    <div className="app-shell h-screen overflow-y-auto">
      <div className="sticky top-0 z-10 border-b border-cyan-100 bg-white/95 backdrop-blur">
        <div className="mx-auto max-w-7xl px-6 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-4">
              <Link
                to={`/workspace/${projectId}`}
                className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-cyan-800"
              >
                <ArrowLeft className="h-4 w-4" />
                返回
              </Link>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <FlaskConical className="h-5 w-5 text-cyan-600" />
                  <h1 className="truncate text-xl font-semibold text-slate-950">{molecule.molecule_id}</h1>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className={cn('rounded-full px-2.5 py-1 text-xs font-medium', getStatusColor(molecule.status))}>
                    {molecule.status}
                  </span>
                  {molecule.source_agent && (
                    <span className="text-sm text-slate-500">来源: {molecule.source_agent}</span>
                  )}
                </div>
              </div>
            </div>
            <Link
              to={`/workspace/${projectId}/report`}
              className="inline-flex items-center gap-2 rounded-md bg-cyan-600 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-cyan-900/20 hover:bg-cyan-700"
            >
              <Download className="h-4 w-4" />
              查看报告
            </Link>
          </div>
        </div>
      </div>

      <main className="mx-auto max-w-7xl px-6 py-6">
        <div className="grid gap-6 xl:grid-cols-[20rem_minmax(0,1fr)_24rem]">
          <div className="space-y-6">
            <div className="science-card">
              <h2 className="mb-3 text-sm font-semibold text-slate-950">分子结构</h2>
              <MoleculeStructure smiles={molecule.smiles} width={300} height={300} />
            </div>

            <div className="science-card">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-950">SMILES</h2>
                <button
                  onClick={handleCopySmiles}
                  className="rounded-md p-1 text-slate-400 hover:bg-cyan-50 hover:text-cyan-700"
                  title="复制"
                >
                  <Copy className="h-4 w-4" />
                </button>
              </div>
              <code className="block break-all rounded-lg border border-cyan-100 bg-cyan-50/50 p-3 text-xs leading-5 text-slate-700">
                {molecule.smiles}
              </code>
            </div>

            {molecule.scaffold && (
              <div className="science-card">
                <h2 className="mb-2 text-sm font-semibold text-slate-950">骨架</h2>
                <p className="break-all text-sm leading-6 text-slate-700">{molecule.scaffold}</p>
              </div>
            )}
          </div>

          <div className="space-y-6">
            {properties && (
              <div className="science-card">
                <h2 className="mb-3 text-sm font-semibold text-slate-950">物化性质</h2>
                <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                  <Property label="MW" value={formatNumber(properties.mw)} />
                  <Property label="LogP" value={formatNumber(properties.logp)} />
                  <Property label="TPSA" value={formatNumber(properties.tpsa)} />
                  <Property label="HBD" value={properties.hbd ?? '-'} />
                  <Property label="HBA" value={properties.hba ?? '-'} />
                  <Property label="RotB" value={rotatableBonds ?? '-'} />
                  <Property label="QED" value={qed == null ? '-' : formatNumber(Number(qed), 3)} />
                  <Property label="SA Score" value={formatNumber(properties.sa_score)} />
                </div>
              </div>
            )}

            {decisionCards && decisionCards.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-slate-950">决策卡片</h2>
                  <span className="chem-badge">{decisionCards.length} 张</span>
                </div>
                {decisionCards.map((card) => (
                  <DecisionCard key={card.decision_id} card={card} />
                ))}
              </div>
            )}

            {synthesisRoute && <SynthesisRoutePanel route={synthesisRoute} />}
          </div>

          <div>
            <ReasoningTracePanel projectId={projectId!} moleculeId={moleculeId!} />
          </div>
        </div>
      </main>
    </div>
  );
}

function SynthesisRoutePanel({ route }: { route: SynthesisRoute }) {
  const routeJson = route.route_json ?? {};
  const plan = routeJson.route_plan ?? [];
  const risks = routeJson.route_risks ?? [];
  const startingMaterials = routeJson.starting_materials ?? [];

  return (
    <div className="science-card">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Route className="h-4 w-4 text-cyan-700" />
          <h2 className="text-sm font-semibold text-slate-950">合成路线</h2>
        </div>
        <span
          className={cn(
            'rounded-full border px-2.5 py-1 text-xs font-medium',
            route.route_found
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-rose-200 bg-rose-50 text-rose-700'
          )}
        >
          {route.route_found ? '可合成' : '需重设'}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-3 text-sm">
        <Property label="Steps" value={route.route_steps ?? '-'} />
        <Property label="Confidence" value={formatNumber(route.route_confidence, 3)} />
        <Property label="Blocks" value={route.buyable_building_blocks ?? '-'} />
      </div>

      {routeJson.route_summary && (
        <p className="mt-3 rounded-lg border border-cyan-100 bg-cyan-50/50 p-3 text-sm leading-6 text-slate-700">
          {routeJson.route_summary}
        </p>
      )}

      {startingMaterials.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {startingMaterials.map((material: string) => (
            <span key={material} className="rounded-md bg-cyan-50 px-2 py-0.5 text-[11px] text-cyan-800">
              {material}
            </span>
          ))}
        </div>
      )}

      {plan.length > 0 && (
        <div className="mt-4 space-y-2">
          {plan.map((step) => (
            <div key={step.step} className="rounded-lg border border-cyan-100 bg-white p-3">
              <div className="text-xs font-semibold text-cyan-900">
                Step {step.step}: {step.stage}
              </div>
              <div className="mt-1 text-xs leading-5 text-slate-600">{step.operation}</div>
              <div className="mt-1 text-[11px] text-slate-500">输出: {step.output}</div>
            </div>
          ))}
        </div>
      )}

      {risks.length > 0 && (
        <div className="mt-4 space-y-1 rounded-lg border border-amber-100 bg-amber-50/60 p-3 text-xs leading-5 text-amber-800">
          {risks.map((risk: string) => (
            <div key={risk}>风险: {risk}</div>
          ))}
        </div>
      )}

      {routeJson.route_note && <p className="mt-3 text-xs leading-5 text-slate-500">{routeJson.route_note}</p>}
    </div>
  );
}

function Property({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-cyan-100 bg-cyan-50/40 p-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 font-semibold text-slate-950">{value}</div>
    </div>
  );
}
