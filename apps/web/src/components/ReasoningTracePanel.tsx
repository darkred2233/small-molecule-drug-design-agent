/**
 * Reasoning Trace Panel Component
 *
 * Display detailed reasoning trace with evidence
 */

import { useQuery } from '@tanstack/react-query';
import { assessmentApi } from '@/api';
import { useWorkspaceStore } from '@/state/workspaceStore';
import { AlertTriangle, Bot, CheckCircle, ExternalLink, Route } from 'lucide-react';
import { getConfidenceColor } from '@/utils/helpers';
import { cn } from '@/utils/helpers';

interface ReasoningTracePanelProps {
  projectId: string;
  moleculeId: string;
}

function confidenceText(confidence: number | null) {
  if (confidence === null) return '待评估';
  return `${(confidence * 100).toFixed(0)}%`;
}

function TraceList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: 'support' | 'risk' | 'next';
}) {
  if (items.length === 0) return null;

  const toneClass = {
    support: 'border-emerald-100 bg-emerald-50/70 text-emerald-800',
    risk: 'border-rose-100 bg-rose-50/70 text-rose-800',
    next: 'border-cyan-100 bg-cyan-50/70 text-cyan-800',
  }[tone];

  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
      <div className="space-y-2">
        {items.map((item, idx) => (
          <div key={idx} className={cn('rounded-lg border p-2 text-sm leading-6', toneClass)}>
            {item}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ReasoningTracePanel({ projectId, moleculeId }: ReasoningTracePanelProps) {
  const { openEvidenceDrawer } = useWorkspaceStore();

  const { data: traces, isLoading } = useQuery({
    queryKey: ['reasoning-traces', projectId, moleculeId],
    queryFn: async () => {
      const allTraces = await assessmentApi.getReasoningTraces(projectId);
      return allTraces.filter((t) => t.molecule_id === moleculeId);
    },
  });

  if (isLoading) {
    return <div className="science-card text-sm text-slate-500">正在加载推理轨迹...</div>;
  }

  if (!traces || traces.length === 0) {
    return (
      <div className="science-card py-8 text-center text-sm text-slate-500">
        <Route className="mx-auto mb-3 h-10 w-10 text-cyan-200" />
        暂无推理轨迹
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-950">推理轨迹</h2>
        <span className="chem-badge">{traces.length} 条</span>
      </div>

      {traces.map((trace) => (
        <div key={trace.trace_id} className="science-card space-y-4">
          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Bot className="h-4 w-4 text-cyan-600" />
                <span className="text-xs font-semibold uppercase tracking-wide text-cyan-700">
                  {trace.trace_type}
                </span>
              </div>
              <span className={cn('rounded-full px-2.5 py-1 text-xs font-medium', getConfidenceColor(trace.confidence))}>
                {confidenceText(trace.confidence)}
              </span>
            </div>
            <h3 className="text-sm font-semibold text-slate-950">结论</h3>
            <p className="mt-2 text-sm leading-6 text-slate-700">{trace.claim}</p>
            <p className="mt-2 text-xs text-slate-500">来源智能体: {trace.source_agent}</p>
          </div>

          <TraceList title="支持因素" items={trace.supporting_factors} tone="support" />
          <TraceList title="风险因素" items={trace.opposing_factors} tone="risk" />

          {trace.uncertainty && (
            <div className="rounded-lg border border-amber-100 bg-amber-50/70 p-3">
              <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-amber-700">
                <AlertTriangle className="h-4 w-4" />
                不确定性
              </div>
              <p className="text-sm leading-6 text-amber-800">{trace.uncertainty}</p>
            </div>
          )}

          <TraceList title="推荐下一步" items={trace.next_actions} tone="next" />

          {trace.evidence_ids.length > 0 && (
            <div className="border-t border-cyan-100 pt-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <CheckCircle className="h-4 w-4 text-emerald-600" />
                证据引用
              </div>
              <div className="flex flex-wrap gap-2">
                {trace.evidence_ids.map((evidenceId) => (
                  <button
                    key={evidenceId}
                    onClick={() => openEvidenceDrawer(evidenceId)}
                    className="inline-flex items-center gap-1 rounded-full border border-cyan-200 bg-white px-2.5 py-1 text-xs font-medium text-cyan-700 hover:bg-cyan-50"
                  >
                    {evidenceId}
                    <ExternalLink className="h-3 w-3" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
