/**
 * Decision Card Component
 *
 * Display decision cards with support/risk/next sections
 */

import type { DecisionCard as DecisionCardType } from '@/types/api';
import { AlertCircle, CheckCircle, ExternalLink, Lightbulb } from 'lucide-react';
import { getConfidenceColor, getConfidenceLabel } from '@/utils/helpers';
import { cn } from '@/utils/helpers';
import { useWorkspaceStore } from '@/state/workspaceStore';

interface DecisionCardProps {
  card: DecisionCardType;
  className?: string;
}

function confidenceText(confidence: number | null) {
  if (confidence === null) return '待评估';
  return `${(confidence * 100).toFixed(0)}%`;
}

function SectionList({
  title,
  items,
  icon,
}: {
  title: string;
  items: string[];
  icon: React.ReactNode;
}) {
  if (items.length === 0) return null;

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        {icon}
        <span className="text-sm font-medium text-slate-700">{title}</span>
      </div>
      <ul className="ml-6 space-y-1">
        {items.map((item, idx) => (
          <li key={idx} className="list-disc text-sm leading-6 text-slate-600">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function DecisionCard({ card, className }: DecisionCardProps) {
  const { openEvidenceDrawer } = useWorkspaceStore();
  const confidenceLabel = getConfidenceLabel(card.confidence);

  return (
    <div
      className={cn(
        'decision-card space-y-4',
        confidenceLabel === 'unknown' ? 'border-cyan-100 bg-white' : `confidence-${confidenceLabel}`,
        className
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-950">{card.title}</h3>
            <span className="chem-badge">{card.card_type}</span>
          </div>
          {card.summary && (
            <p className="mt-2 text-sm leading-6 text-slate-700">{card.summary}</p>
          )}
          {card.decision && (
            <p className="mt-2 text-xs font-medium uppercase tracking-wide text-cyan-700">
              {card.decision}
            </p>
          )}
        </div>
        <span
          className={cn(
            'shrink-0 rounded-full px-2.5 py-1 text-xs font-medium',
            getConfidenceColor(card.confidence)
          )}
        >
          {confidenceText(card.confidence)}
        </span>
      </div>

      <SectionList
        title="支持因素"
        items={card.support}
        icon={<CheckCircle className="h-4 w-4 text-emerald-600" />}
      />
      <SectionList
        title="风险因素"
        items={card.risk}
        icon={<AlertCircle className="h-4 w-4 text-rose-600" />}
      />
      <SectionList
        title="下一步建议"
        items={card.next_steps}
        icon={<Lightbulb className="h-4 w-4 text-cyan-600" />}
      />

      {card.evidence_ids.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-cyan-100 pt-3">
          {card.evidence_ids.map((evidenceId) => (
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
      )}
    </div>
  );
}
