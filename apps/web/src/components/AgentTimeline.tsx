/**
 * Agent Timeline Component
 *
 * Display agent execution timeline with status
 */

import { useQuery } from '@tanstack/react-query';
import { projectsApi } from '@/api';
import { CheckCircle, Circle, XCircle, Loader2, Clock } from 'lucide-react';
import { cn, formatDate } from '@/utils/helpers';
import type { AgentRun } from '@/types/api';

interface AgentTimelineProps {
  projectId: string;
}

type TimelineRun = AgentRun & {
  aggregate_count?: number;
  aggregate_retrieved_chunks?: number;
  aggregate_evidence_ids?: number;
};

type RunProgress = {
  stage?: string;
  phase?: string;
  message?: string;
  total_molecules?: number;
  completed_molecules?: number;
  percent?: number;
  current_molecule_id?: string | null;
  adapter_mode?: string;
  external_tools_enabled?: boolean;
  warnings?: string[];
};

export default function AgentTimeline({ projectId }: AgentTimelineProps) {
  // Poll status while pipeline is running - increased frequency for better responsiveness
  const { data: status } = useQuery({
    queryKey: ['project-status', projectId],
    queryFn: () => projectsApi.getStatus(projectId),
    refetchInterval: (query) =>
      query.state.data?.status === 'pipeline_running' ? 1000 : false, // Changed from 2000ms to 1000ms
  });

  if (!status || !status.agent_runs || status.agent_runs.length === 0) {
    return (
      <div className="text-sm text-gray-500 text-center py-4">
        暂无执行记录
      </div>
    );
  }

  // Group runs by iteration for better multi-round display
  const runsByIteration = status.agent_runs.reduce((acc, run) => {
    const iteration = run.iteration ?? 1;
    if (!acc[iteration]) {
      acc[iteration] = [];
    }
    acc[iteration].push(run);
    return acc;
  }, {} as Record<number, typeof status.agent_runs>);

  const iterations = Object.keys(runsByIteration)
    .map(Number)
    .sort((a, b) => b - a); // Sort descending to show latest first

  const successfulStatuses = new Set(['completed', 'success', 'succeeded']);
  const failedStatuses = new Set(['failed', 'error']);
  const runningStatuses = new Set(['running', 'retrying', 'in_progress']);
  const waitingStatuses = new Set(['pending', 'queued', 'created', 'waiting', 'not_started']);

  const getStatusIcon = (agentStatus: string) => {
    if (successfulStatuses.has(agentStatus)) {
      return <CheckCircle className="w-5 h-5 text-emerald-600" />;
    }
    if (runningStatuses.has(agentStatus)) {
      return <Loader2 className="w-5 h-5 text-cyan-600 animate-spin" />;
    }
    if (failedStatuses.has(agentStatus)) {
      return <XCircle className="w-5 h-5 text-rose-600" />;
    }
    return <Circle className="w-5 h-5 text-slate-400" />;
  };

  const getTimelineStatusClass = (agentStatus: string) => {
    if (successfulStatuses.has(agentStatus)) return 'completed';
    if (runningStatuses.has(agentStatus)) return 'running';
    if (failedStatuses.has(agentStatus)) return 'failed';
    return 'pending';
  };

  const getStatusMeta = (agentStatus: string) => {
    const meta: Record<string, { label: string; className: string }> = {
      completed: {
        label: '已完成',
        className: 'border-emerald-200 bg-emerald-50 text-emerald-700',
      },
      success: {
        label: '已完成',
        className: 'border-emerald-200 bg-emerald-50 text-emerald-700',
      },
      succeeded: {
        label: '已完成',
        className: 'border-emerald-200 bg-emerald-50 text-emerald-700',
      },
      running: {
        label: '执行中',
        className: 'border-cyan-200 bg-cyan-50 text-cyan-700',
      },
      retrying: {
        label: '重试中',
        className: 'border-amber-200 bg-amber-50 text-amber-700',
      },
      in_progress: {
        label: '执行中',
        className: 'border-cyan-200 bg-cyan-50 text-cyan-700',
      },
      queued: {
        label: '排队中',
        className: 'border-slate-200 bg-slate-50 text-slate-600',
      },
      pending: {
        label: '等待执行',
        className: 'border-slate-200 bg-slate-50 text-slate-600',
      },
      created: {
        label: '已创建',
        className: 'border-slate-200 bg-slate-50 text-slate-600',
      },
      waiting: {
        label: '等待执行',
        className: 'border-slate-200 bg-slate-50 text-slate-600',
      },
      not_started: {
        label: '未开始',
        className: 'border-slate-200 bg-slate-50 text-slate-600',
      },
      skipped: {
        label: '已跳过',
        className: 'border-amber-200 bg-amber-50 text-amber-700',
      },
      failed: {
        label: '失败',
        className: 'border-rose-200 bg-rose-50 text-rose-700',
      },
      error: {
        label: '失败',
        className: 'border-rose-200 bg-rose-50 text-rose-700',
      },
    };

    return (
      meta[agentStatus] || {
        label: agentStatus ? `状态: ${agentStatus}` : '状态未知',
        className: 'border-slate-200 bg-slate-50 text-slate-600',
      }
    );
  };

  const getAgentLabel = (agentName: string) => {
    const labels: Record<string, string> = {
      knowledge_ingestion_agent: '知识导入',
      molecule_import_agent: '分子导入',
      conversation_agent: '自然语言对话',
      rag_builder_agent: 'RAG 索引构建',
      rag_collection_agent: '知识包采集',
      target_agent: '靶点解析',
      sar_agent: 'SAR 分析',
      generator_agent: '分子生成',
      conformer_agent: '构象生成',
      validation_agent: '结构校验',
      filter_agent: '规则过滤',
      rag_agent: 'RAG 证据检索',
      candidate_assessment_agent: '候选评估',
      docking_agent: '分子对接',
      admet_agent: 'ADMET 预测',
      synthesis_agent: '逆合成分析',
      self_refutation_agent: '自我反驳',
      ranking_agent: '候选排序',
      ranker_agent: '综合排序',
      advisor_agent: 'Advisor',
      advisor_apply_agent: 'Advisor 应用',
      decision_card_agent: '决策卡片',
      report_agent: '报告生成',
    };
    return labels[agentName] || agentName;
  };

  const getDuration = (run: AgentRun) => {
    if (!run.started_at || !run.ended_at) return null;
    const start = new Date(run.started_at);
    const end = new Date(run.ended_at);
    const duration = (end.getTime() - start.getTime()) / 1000;
    return duration.toFixed(1) + 's';
  };

  return (
    <div className="space-y-4">
      {iterations.map((iteration) => {
        const iterationRuns = aggregateTimelineRuns(runsByIteration[iteration]);

        return (
          <div key={iteration} className="space-y-1">
            {iterations.length > 1 && (
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-600">
                <div className="h-px flex-1 bg-slate-200"></div>
                <span>第 {iteration} 轮</span>
                <div className="h-px flex-1 bg-slate-200"></div>
              </div>
            )}

            {iterationRuns.map((run, index) => {
              const statusMeta = getStatusMeta(run.status);
              const duration = getDuration(run);
              const progress = getRunProgress(run);

              return (
                <div
                  key={run.agent_run_id}
                  className={cn(
                    'agent-timeline-item relative',
                    index === iterationRuns.length - 1 && 'pb-0'
                  )}
                >
                  {/* Timeline dot */}
                  <div className={cn('agent-timeline-dot', getTimelineStatusClass(run.status))}>
                    {getStatusIcon(run.status)}
                  </div>

                  {/* Content */}
                  <div className="ml-8">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="font-medium text-sm">
                        {getAgentLabel(run.agent_name)}
                        {run.aggregate_count && run.aggregate_count > 1 && (
                          <span className="ml-2 rounded-full bg-cyan-50 px-2 py-0.5 text-[11px] font-medium text-cyan-700">
                            {run.aggregate_count} 次
                          </span>
                        )}
                      </div>
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      'rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4',
                      statusMeta.className
                    )}
                  >
                    {statusMeta.label}
                  </span>
                  {duration && (
                    <div className="flex items-center gap-1 text-xs text-gray-500">
                      <Clock className="w-3 h-3" />
                      {duration}
                    </div>
                  )}
                </div>
              </div>

              {run.model_name && (
                <div className="text-xs text-gray-500 mt-0.5">模型: {run.model_name}</div>
              )}

              {progress && (
                <div className="mt-2 rounded-lg border border-cyan-100 bg-cyan-50/50 p-2">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className="font-medium text-cyan-900">
                      {progress.stage ?? getAgentLabel(run.agent_name)}
                    </span>
                    <span className="text-cyan-700">
                      {formatProgressPercent(progress.percent)}%
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white">
                    <div
                      className="h-full rounded-full bg-cyan-600 transition-all"
                      style={{ width: `${formatProgressPercent(progress.percent)}%` }}
                    />
                  </div>
                  {progress.message && (
                    <div className="mt-1 text-xs leading-5 text-slate-600">{progress.message}</div>
                  )}
                  <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-slate-500">
                    {typeof progress.completed_molecules === 'number' &&
                      typeof progress.total_molecules === 'number' && (
                        <span>
                          {progress.completed_molecules}/{progress.total_molecules} 分子
                        </span>
                      )}
                    {progress.current_molecule_id && (
                      <span className="font-mono">{progress.current_molecule_id}</span>
                    )}
                    {progress.adapter_mode && <span>{progress.adapter_mode}</span>}
                    {progress.external_tools_enabled && <span>外部工具已启用</span>}
                  </div>
                  {progress.warnings && progress.warnings.length > 0 && (
                    <div className="mt-1 text-[11px] leading-4 text-amber-700">
                      {translateWarning(progress.warnings[0])}
                    </div>
                  )}
                </div>
              )}

              {run.agent_name === 'rag_agent' && run.aggregate_count && run.aggregate_count > 1 && (
                <div className="mt-1 text-xs text-slate-500">
                  已合并 {run.aggregate_count} 次检索
                  {run.aggregate_retrieved_chunks ? `，命中 ${run.aggregate_retrieved_chunks} 条片段` : ''}
                  {run.aggregate_evidence_ids ? `，形成 ${run.aggregate_evidence_ids} 条证据` : ''}
                </div>
              )}

              {runningStatuses.has(run.status) && (
                <div className="text-xs text-cyan-700 mt-1">
                  {run.status === 'retrying' ? '正在重试...' : '执行中...'}
                </div>
              )}

              {waitingStatuses.has(run.status) && (
                <div className="text-xs text-slate-500 mt-1">
                  等待上游步骤或外部科学工具返回结果
                </div>
              )}

              {successfulStatuses.has(run.status) && run.ended_at && (
                <div className="text-xs text-gray-400 mt-1">
                  完成于 {formatDate(run.ended_at)}
                </div>
              )}

              {failedStatuses.has(run.status) && run.error_message && (
                <div className="text-xs text-red-600 mt-1 bg-red-50 p-2 rounded">
                  {run.error_message}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
        );
      })}
    </div>
  );
}

function aggregateTimelineRuns(runs: AgentRun[]): TimelineRun[] {
  const ragRuns = runs.filter((run) => run.agent_name === 'rag_agent');
  if (ragRuns.length <= 1) return runs;

  const firstRagIndex = runs.findIndex((run) => run.agent_name === 'rag_agent');
  const aggregatedRag: TimelineRun = {
    ...ragRuns[ragRuns.length - 1],
    agent_run_id: ragRuns.map((run) => run.agent_run_id).join('__'),
    status: aggregateStatus(ragRuns),
    model_name: Array.from(new Set(ragRuns.map((run) => run.model_name).filter(Boolean))).join(' / '),
    aggregate_count: ragRuns.length,
    aggregate_retrieved_chunks: ragRuns.reduce(
      (sum, run) => sum + countArray(run.output_json?.retrieved_chunks),
      0
    ),
    aggregate_evidence_ids: ragRuns.reduce(
      (sum, run) => sum + countArray(run.output_json?.evidence_ids),
      0
    ),
  };

  return runs.reduce<TimelineRun[]>((items, run, index) => {
    if (run.agent_name !== 'rag_agent') {
      items.push(run);
    } else if (index === firstRagIndex) {
      items.push(aggregatedRag);
    }
    return items;
  }, []);
}

function aggregateStatus(runs: AgentRun[]) {
  const statuses = runs.map((run) => run.status);
  if (statuses.some((status) => ['failed', 'error'].includes(status))) return 'failed';
  if (statuses.some((status) => ['running', 'retrying', 'in_progress'].includes(status))) return 'running';
  if (statuses.every((status) => ['completed', 'success', 'succeeded'].includes(status))) return 'completed';
  return statuses[statuses.length - 1] ?? 'pending';
}

function countArray(value: unknown) {
  return Array.isArray(value) ? value.length : 0;
}

function getRunProgress(run: AgentRun): RunProgress | null {
  const progress = run.output_json?.progress;
  if (!progress || typeof progress !== 'object') return null;
  return progress as RunProgress;
}

function formatProgressPercent(value: unknown) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function translateWarning(value: string) {
  const translations: Record<string, string> = {
    external_docking_skipped_by_assessment_mode: '当前评估深度跳过外部对接。',
    external_retrosynthesis_skipped_by_assessment_mode: '当前评估深度跳过外部逆合成。',
    protein_file_required_for_external_docking: '缺少受体文件，外部对接无法运行。',
    grid_center_and_grid_size_required_for_external_docking: '缺少对接盒中心或大小，外部对接无法运行。',
    external_retrosynthesis_tools_not_installed: '外部逆合成工具不可用，将使用替代评估。',
    external_docking_tools_not_installed: '外部对接工具不可用，将使用替代评估。',
  };
  if (value.startsWith('coarse_screen_failed_skip_external=')) {
    const count = value.split('=')[1] ?? '0';
    return `粗筛未通过的 ${count} 个分子已跳过外部细筛。`;
  }
  return translations[value] ?? value;
}
