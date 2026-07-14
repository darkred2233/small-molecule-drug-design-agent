/**
 * Constraint Chips Component
 *
 * Display optimization constraints as chips
 */

import type { OptimizationConstraint } from '@/types/api';
import { X, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/utils/helpers';
import { useState } from 'react';

interface ConstraintChipsProps {
  constraints: OptimizationConstraint[];
  onToggle?: (constraintId: string) => void;
  onRemove?: (constraintId: string) => void;
  editable?: boolean;
}

function getPriorityTone(priority: number) {
  if (priority > 10) {
    if (priority >= 80) return 'high';
    if (priority >= 50) return 'medium';
    return 'low';
  }

  if (priority >= 3) return 'high';
  if (priority >= 2) return 'medium';
  return 'low';
}

function getPriorityColor(priority: number) {
  const tone = getPriorityTone(priority);
  if (tone === 'high') return 'border-rose-200 bg-rose-50 text-rose-700';
  if (tone === 'medium') return 'border-amber-200 bg-amber-50 text-amber-700';
  return 'border-cyan-200 bg-cyan-50 text-cyan-700';
}

export default function ConstraintChips({
  constraints,
  onToggle,
  onRemove,
  editable = false,
}: ConstraintChipsProps) {
  const [expanded, setExpanded] = useState(false);

  const activeConstraints = constraints.filter((c) => c.is_active !== false);
  const displayConstraints = expanded ? activeConstraints : activeConstraints.slice(0, 5);
  const hasMore = activeConstraints.length > 5;

  if (constraints.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-cyan-200 bg-cyan-50/40 py-3 text-center text-sm text-slate-500">
        暂无约束条件
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {displayConstraints.map((constraint) => (
          <div
            key={constraint.constraint_id}
            className={cn(
              'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium shadow-sm transition-all',
              getPriorityColor(constraint.priority),
              constraint.is_active === false && 'opacity-50'
            )}
          >
            {editable && onToggle && (
              <button
                onClick={() => onToggle(constraint.constraint_id)}
                className="hover:opacity-70"
                title={constraint.is_active === false ? '启用' : '禁用'}
              >
                <input
                  type="checkbox"
                  checked={constraint.is_active !== false}
                  onChange={() => {}}
                  className="h-3 w-3 accent-cyan-600"
                />
              </button>
            )}
            <span>{constraint.label}</span>
            {constraint.operator && constraint.value !== undefined && (
              <span className="opacity-75">
                {constraint.operator} {constraint.value}
              </span>
            )}
            <span className="rounded-full bg-white/70 px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
              P{constraint.priority}
            </span>
            {editable && onRemove && (
              <button
                onClick={() => onRemove(constraint.constraint_id)}
                className="hover:opacity-70"
                title="删除"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        ))}
      </div>

      {hasMore && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 text-sm text-cyan-700 hover:text-cyan-800"
        >
          {expanded ? (
            <>
              <ChevronUp className="h-4 w-4" />
              收起
            </>
          ) : (
            <>
              <ChevronDown className="h-4 w-4" />
              显示更多 ({activeConstraints.length - 5} 个)
            </>
          )}
        </button>
      )}
    </div>
  );
}
