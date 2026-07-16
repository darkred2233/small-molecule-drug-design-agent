/**
 * Advisor Panel Component
 *
 * Display optimization suggestions and apply to next round
 */

import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { assessmentApi, projectsApi } from '@/api';
import { ArrowRight, CheckCircle, FlaskConical, Lightbulb, Settings2 } from 'lucide-react';
import {
  DEFAULT_STRATEGY_COUNTS,
  STRATEGY_KEYS,
  STRATEGY_LABELS,
  buildRoundGenerationConfig,
  clampInteger,
  strategyCountsFromConfig,
  sumStrategyCounts,
  updateStrategyCount,
} from '@/utils/generationConfig';
import Button from './ui/Button';

function stringifySuggestion(item: string | Record<string, any>) {
  if (typeof item === 'string') return item;
  return item.summary || item.label || item.action || JSON.stringify(item);
}

function constraintLabel(constraint: Record<string, any>) {
  return constraint.label || constraint.field || constraint.name || '优化约束';
}

function constraintValue(constraint: Record<string, any>) {
  const operator = constraint.operator ? `${constraint.operator} ` : '';
  const value = constraint.value ?? constraint.target ?? constraint.threshold ?? '';
  return `${constraint.field || 'constraint'}: ${operator}${typeof value === 'object' ? JSON.stringify(value) : value}`;
}

export default function AdvisorPanel() {
  const { projectId } = useParams();
  const queryClient = useQueryClient();

  const { data: advice, isLoading } = useQuery({
    queryKey: ['advice', projectId],
    queryFn: () => assessmentApi.getAdvice(projectId!),
    enabled: !!projectId,
  });
  const currentAdvice = advice?.[advice.length - 1];
  const [strategyCounts, setStrategyCounts] = useState(DEFAULT_STRATEGY_COUNTS);
  const [topN, setTopN] = useState(20);
  const generationSize = sumStrategyCounts(strategyCounts);

  useEffect(() => {
    const config = currentAdvice?.suggested_generation_config;
    if (!config) return;
    setStrategyCounts(strategyCountsFromConfig(config));
    if (config.top_n) {
      setTopN(clampInteger(Number(config.top_n), 1, 500));
    }
  }, [currentAdvice?.suggestion_id]);

  const applyAdvice = useMutation({
    mutationFn: () => assessmentApi.applyAdvice(projectId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['constraints', projectId] });
      queryClient.invalidateQueries({ queryKey: ['advice', projectId] });
    },
  });

  const createRound = useMutation({
    mutationFn: (generationConfig: Record<string, any>) =>
      projectsApi.createRound(projectId!, generationConfig),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-status', projectId] });
    },
  });

  const handleApplyAndCreateRound = async () => {
    await applyAdvice.mutateAsync();
    await createRound.mutateAsync(buildRoundGenerationConfig(strategyCounts, topN, 'external'));
  };

  if (isLoading) {
    return (
      <div className="science-card text-sm text-slate-500">
        正在加载 Advisor 优化建议...
      </div>
    );
  }

  if (!advice || advice.length === 0 || !currentAdvice) {
    return (
      <div className="science-card py-10 text-center text-sm text-slate-500">
        <Lightbulb className="mx-auto mb-3 h-12 w-12 text-cyan-200" />
        <p className="font-medium text-slate-700">暂无优化建议</p>
        <p className="mt-1 text-xs">完成一轮分子评估后，Advisor 会给出下一轮设计方向。</p>
      </div>
    );
  }

  const previousCount = Math.max(advice.length - 1, 0);

  return (
    <div className="space-y-5">
      <div className="science-card border-cyan-200 bg-gradient-to-br from-white to-cyan-50/70">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-cyan-600 p-2 text-white shadow-sm shadow-cyan-900/20">
            <Lightbulb className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-slate-950">下一轮优化摘要</h3>
              <span className="chem-badge">Advisor 最新建议</span>
              {previousCount > 0 && (
                <span className="text-xs text-slate-500">另有 {previousCount} 条历史建议</span>
              )}
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-700">{currentAdvice.summary}</p>
          </div>
        </div>
      </div>

      {currentAdvice.suggestions.length > 0 && (
        <section>
          <h3 className="mb-3 text-sm font-semibold text-slate-950">具体设计动作</h3>
          <div className="space-y-2">
            {currentAdvice.suggestions.map((suggestion, idx) => (
              <div
                key={idx}
                className="flex items-start gap-3 rounded-lg border border-emerald-100 bg-white p-3 shadow-sm shadow-cyan-950/5"
              >
                <CheckCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-600" />
                <p className="text-sm leading-6 text-slate-700">{stringifySuggestion(suggestion)}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {currentAdvice.next_round_constraints.length > 0 && (
        <section>
          <h3 className="mb-3 text-sm font-semibold text-slate-950">下一轮约束预览</h3>
          <div className="space-y-2">
            {currentAdvice.next_round_constraints.map((constraint, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-cyan-100 bg-cyan-50/50 p-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-slate-900">{constraintLabel(constraint)}</span>
                  <span className="rounded-full bg-white px-2 py-1 text-xs text-cyan-700 ring-1 ring-cyan-100">
                    priority {constraint.priority ?? '-'}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{constraintValue(constraint)}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {Object.keys(currentAdvice.suggested_generation_config).length > 0 && (
        <section>
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950">
            <Settings2 className="h-4 w-4 text-cyan-600" />
            生成配置建议
          </div>
          <pre className="max-h-48 overflow-auto rounded-lg border border-cyan-100 bg-slate-950 p-3 text-xs text-cyan-50">
            {JSON.stringify(currentAdvice.suggested_generation_config, null, 2)}
          </pre>
        </section>
      )}

      <section className="rounded-lg border border-cyan-100 bg-white p-3 shadow-sm shadow-cyan-950/5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <Settings2 className="h-4 w-4 text-cyan-600" />
            新一轮生成数量
          </div>
          <span className="rounded border border-emerald-100 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800">
            total {generationSize}
          </span>
        </div>
        <div className="grid gap-2 sm:grid-cols-4">
          {STRATEGY_KEYS.map((strategy) => (
            <label key={strategy} className="block text-xs font-medium text-slate-600">
              {STRATEGY_LABELS[strategy]}
              <input
                type="number"
                min={0}
                max={500}
                value={strategyCounts[strategy]}
                onChange={(event) =>
                  setStrategyCounts((current) =>
                    updateStrategyCount(current, strategy, Number(event.target.value))
                  )
                }
                className="mt-1 h-9 w-full rounded-md border border-cyan-200 px-2 text-sm font-semibold text-slate-950 focus:outline-none focus:ring-2 focus:ring-cyan-500"
              />
            </label>
          ))}
          <label className="block text-xs font-medium text-slate-600">
            Top N
            <input
              type="number"
              min={1}
              max={500}
              value={topN}
              onChange={(event) => setTopN(clampInteger(Number(event.target.value), 1, 500))}
              className="mt-1 h-9 w-full rounded-md border border-cyan-200 px-2 text-sm font-semibold text-slate-950 focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </label>
        </div>
      </section>

      <div className="flex items-center gap-3 border-t border-cyan-100 pt-4">
        <Button
          onClick={() => applyAdvice.mutate()}
          disabled={applyAdvice.isPending}
          loading={applyAdvice.isPending}
          variant="outline"
          className="flex-1"
        >
          应用约束
        </Button>
        <Button
          onClick={handleApplyAndCreateRound}
          disabled={applyAdvice.isPending || createRound.isPending || generationSize < 1}
          loading={applyAdvice.isPending || createRound.isPending}
          className="flex-1"
        >
          <FlaskConical className="mr-2 h-4 w-4" />
          应用并启动新一轮
          <ArrowRight className="ml-2 h-4 w-4" />
        </Button>
      </div>

      {applyAdvice.isSuccess && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-center text-sm text-emerald-700">
          约束已应用，可以进入下一轮分子生成。
        </div>
      )}
    </div>
  );
}
