import { useQuery } from '@tanstack/react-query';
import { projectsApi } from '@/api';
import { CheckCircle, Circle, XCircle, Loader2 } from 'lucide-react';
import { cn } from '@/utils/helpers';
import type { AgentRun, RunPlan } from '@/types/api';

interface AgentTimelineProps {
  projectId: string;
}

type TimelineItem = {
  id: string;
  label: string;
  status: string;
  meta?: string;
  modelName?: string | null;
  error?: string | null;
};

const TOOL_MODEL_NAMES = new Set([
  'tool-adapter',
  'deterministic-orchestrator',
  'heuristic-ranker',
  'heuristic_self_refutation',
  'rule_based',
]);

export default function AgentTimeline({ projectId }: AgentTimelineProps) {
  const { data: status } = useQuery({
    queryKey: ['project-status', projectId],
    queryFn: () => projectsApi.getStatus(projectId),
    refetchInterval: (query) => {
      const value = query.state.data?.status;
      return value === 'pipeline_running' || value === 'iterative_running' ? 1000 : false;
    },
  });

  const { data: runPlan } = useQuery({
    queryKey: ['run-plan', projectId],
    queryFn: () => projectsApi.getRunPlan(projectId),
    enabled: !!projectId,
  });

  if (!status || !status.agent_runs || status.agent_runs.length === 0) {
    return <div className="py-4 text-center text-sm text-gray-500">暂无执行记录</div>;
  }

  const orchestratorRun = latestRunByName(status.agent_runs, 'iterative_orchestrator_agent');
  const roundView = orchestratorRun ? buildCurrentRoundView(orchestratorRun, runPlan) : null;
  const timelineItems = roundView
    ? roundView.items
    : status.agent_runs.slice(-8).map((run) => runToTimelineItem(run));

  return (
    <div className="space-y-3">
      {roundView && (
        <div className="rounded-lg border border-cyan-100 bg-cyan-50/60 px-3 py-2">
          <div className="text-sm font-semibold text-slate-950">
            第 {roundView.round} / {roundView.maxRounds} 轮
          </div>
          <div className="mt-0.5 text-xs text-cyan-800">{roundView.phase}</div>
        </div>
      )}

      <div className="space-y-1">
        {timelineItems.map((item, index) => {
          const statusMeta = getStatusMeta(item.status);
          return (
            <div
              key={item.id}
              className={cn('agent-timeline-item relative', index === timelineItems.length - 1 && 'pb-0')}
            >
              <div className={cn('agent-timeline-dot', getTimelineStatusClass(item.status))}>
                {getStatusIcon(item.status)}
              </div>

              <div className="ml-8">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm font-medium text-slate-900">{item.label}</div>
                  <span className={cn('rounded-full border px-2 py-0.5 text-[11px] font-medium', statusMeta.className)}>
                    {statusMeta.label}
                  </span>
                </div>

                {item.modelName && shouldShowModel(item.modelName) && (
                  <div className="mt-0.5 text-xs text-gray-500">模型: {item.modelName}</div>
                )}

                {item.meta && <div className="mt-1 text-xs leading-5 text-slate-500">{item.meta}</div>}

                {item.error && (
                  <div className="mt-1 rounded bg-red-50 p-2 text-xs text-red-600">{item.error}</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function buildCurrentRoundView(orchestratorRun: AgentRun, runPlan?: RunPlan | null) {
  const rounds = Array.isArray(orchestratorRun.output_json?.rounds) ? orchestratorRun.output_json.rounds : [];
  const numericRounds = rounds.filter((round) => typeof round?.round === 'number');
  const latestRound = numericRounds[numericRounds.length - 1];
  const maxRounds = runPlan?.max_rounds ?? Number(orchestratorRun.input_json?.run_plan?.max_rounds ?? 1);

  if (!latestRound) {
    return {
      round: 1,
      maxRounds,
      phase: orchestratorRun.status === 'running' ? '初始化' : statusText(orchestratorRun.status),
      items: [
        {
          id: orchestratorRun.agent_run_id,
          label: '迭代编排',
          status: orchestratorRun.status,
          meta: statusText(orchestratorRun.output_json?.status ?? orchestratorRun.status),
          modelName: orchestratorRun.model_name,
        },
      ],
    };
  }

  const items: TimelineItem[] = [];
  const agents = Array.isArray(latestRound.agents) ? latestRound.agents : [];
  agents.forEach((agent: Record<string, any>, index: number) => {
    const agentName = String(agent.agent ?? 'generation');
    items.push({
      id: String(agent.agent_run_id ?? `${latestRound.round}-${agentName}-${index}`),
      label: generationAgentLabel(agentName),
      status: normalizeAgentStatus(agent.status),
      meta: [
        typeof agent.requested_count === 'number' ? `请求 ${agent.requested_count}` : '',
        typeof agent.stored_count === 'number' ? `入库 ${agent.stored_count}` : '',
        typeof agent.proposed_count === 'number' ? `候选 ${agent.proposed_count}` : '',
        agent.failure_reason ? `原因 ${agent.failure_reason}` : '',
      ]
        .filter(Boolean)
        .join(' · '),
    });
  });

  pushSummaryItem(items, latestRound, 'validation', '结构校验');
  pushSummaryItem(items, latestRound, 'filtering', '规则过滤');
  pushSummaryItem(items, latestRound, 'assessment', '候选评估');
  pushSummaryItem(items, latestRound, 'advisor', '下一轮建议');

  if (items.length === 0) {
    items.push({
      id: `${orchestratorRun.agent_run_id}-round-${latestRound.round}`,
      label: '迭代编排',
      status: orchestratorRun.status,
      meta: '等待本轮 agent 返回',
      modelName: orchestratorRun.model_name,
    });
  }

  return {
    round: latestRound.round as number,
    maxRounds,
    phase: currentPhase(latestRound, orchestratorRun.status),
    items,
  };
}

function pushSummaryItem(items: TimelineItem[], round: Record<string, any>, key: string, label: string) {
  const summary = round[key];
  if (!summary) return;
  items.push({
    id: `${round.round}-${key}`,
    label,
    status: 'completed',
    meta: summarizeObject(summary),
  });
}

function summarizeObject(value: unknown) {
  if (!value || typeof value !== 'object') return undefined;
  const record = value as Record<string, any>;
  const keys = [
    'validated_count',
    'passed_count',
    'assessed_count',
    'ranking_count',
    'suggestion_count',
    'external_synthesis_routes_enabled',
  ];
  return keys
    .filter((key) => record[key] !== undefined)
    .map((key) => `${translateSummaryKey(key)} ${String(record[key])}`)
    .join(' · ');
}

function currentPhase(round: Record<string, any>, orchestratorStatus: string) {
  if (round.stop_reason) return `停止原因: ${round.stop_reason}`;
  if (round.advisor) return '本轮建议完成';
  if (round.assessment) return '候选评估完成';
  if (round.filtering) return '规则过滤完成';
  if (round.validation) return '结构校验完成';
  if (Array.isArray(round.agents) && round.agents.length > 0) return '分子生成完成';
  if (orchestratorStatus === 'running') return '分子生成中';
  return statusText(orchestratorStatus);
}

function latestRunByName(runs: AgentRun[], agentName: string) {
  return [...runs].reverse().find((run) => run.agent_name === agentName);
}

function runToTimelineItem(run: AgentRun): TimelineItem {
  return {
    id: run.agent_run_id,
    label: runLabel(run.agent_name),
    status: run.status,
    modelName: run.model_name,
    error: run.error_message,
  };
}

function generationAgentLabel(agentName: string) {
  const labels: Record<string, string> = {
    reinvent4: '全局生成 agent',
    crem: '局部替换 agent',
    autogrow4: '对接引导 agent',
  };
  return labels[agentName] ?? runLabel(agentName);
}

function runLabel(agentName: string) {
  const labels: Record<string, string> = {
    iterative_orchestrator_agent: '迭代编排',
    reinvent4_agent: '全局生成 agent',
    crem_agent: '局部替换 agent',
    autogrow4_agent: '对接引导 agent',
    molecule_generation_tool_agent: '分子生成',
    validation_agent: '结构校验',
    filter_agent: '规则过滤',
    candidate_assessment_agent: '候选评估',
    docking_agent: '分子对接',
    admet_agent: 'ADMET 预测',
    synthesis_agent: '合成评估',
    ranking_agent: '候选排序',
    ranker_agent: '候选排序',
    advisor_agent: '下一轮建议',
    molecule_narrative_agent: '分子解读',
    final_report_agent: '总报告',
  };
  return labels[agentName] || agentName;
}

function normalizeAgentStatus(status: unknown) {
  if (status === 'completed') return 'completed';
  if (status === 'skipped') return 'skipped';
  if (status === 'failed') return 'failed';
  if (typeof status === 'string') return status;
  return 'pending';
}

function shouldShowModel(modelName: string) {
  const normalized = modelName.trim().toLowerCase();
  if (!normalized) return false;
  if (TOOL_MODEL_NAMES.has(normalized)) return false;
  return !normalized.includes('heuristic') && !normalized.includes('tool');
}

function getStatusIcon(agentStatus: string) {
  if (['completed', 'success', 'succeeded'].includes(agentStatus)) {
    return <CheckCircle className="h-5 w-5 text-emerald-600" />;
  }
  if (['running', 'retrying', 'in_progress'].includes(agentStatus)) {
    return <Loader2 className="h-5 w-5 animate-spin text-cyan-600" />;
  }
  if (['failed', 'error'].includes(agentStatus)) {
    return <XCircle className="h-5 w-5 text-rose-600" />;
  }
  return <Circle className="h-5 w-5 text-slate-400" />;
}

function getTimelineStatusClass(agentStatus: string) {
  if (['completed', 'success', 'succeeded'].includes(agentStatus)) return 'completed';
  if (['running', 'retrying', 'in_progress'].includes(agentStatus)) return 'running';
  if (['failed', 'error'].includes(agentStatus)) return 'failed';
  return 'pending';
}

function getStatusMeta(agentStatus: string) {
  const meta: Record<string, { label: string; className: string }> = {
    completed: { label: '已完成', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
    success: { label: '已完成', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
    succeeded: { label: '已完成', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
    running: { label: '执行中', className: 'border-cyan-200 bg-cyan-50 text-cyan-700' },
    retrying: { label: '重试中', className: 'border-amber-200 bg-amber-50 text-amber-700' },
    in_progress: { label: '执行中', className: 'border-cyan-200 bg-cyan-50 text-cyan-700' },
    skipped: { label: '已跳过', className: 'border-amber-200 bg-amber-50 text-amber-700' },
    failed: { label: '失败', className: 'border-rose-200 bg-rose-50 text-rose-700' },
    error: { label: '失败', className: 'border-rose-200 bg-rose-50 text-rose-700' },
    pending: { label: '等待执行', className: 'border-slate-200 bg-slate-50 text-slate-600' },
  };
  return meta[agentStatus] || {
    label: statusText(agentStatus),
    className: 'border-slate-200 bg-slate-50 text-slate-600',
  };
}

function statusText(status: unknown) {
  if (typeof status !== 'string' || !status) return '状态未知';
  return status;
}

function translateSummaryKey(key: string) {
  const labels: Record<string, string> = {
    validated_count: '校验',
    passed_count: '通过',
    assessed_count: '评估',
    ranking_count: '排序',
    suggestion_count: '建议',
    external_synthesis_routes_enabled: '路线预测',
  };
  return labels[key] ?? key;
}
