import { Beaker, Loader2, Play, Save, SlidersHorizontal, Sparkles } from 'lucide-react';
import type { AgentName, RunPlan, RunPlanChange } from '@/types/api';

type PresetId = 'fast' | 'standard' | 'deep';

interface AgentControlPanelProps {
  runPlan: RunPlan | null;
  planDiff: RunPlanChange[];
  warnings: string[];
  isSaving: boolean;
  isRunning: boolean;
  onChange: (nextRunPlan: RunPlan) => void;
  onSave: () => void;
  onRun: () => void;
}

const AGENT_LABELS: Record<AgentName, string> = {
  reinvent4: '全局生成 agent',
  crem: '局部替换 agent',
  autogrow4: '对接引导 agent',
};

const PRESETS: Record<
  PresetId,
  {
    label: string;
    rounds: number;
    nextSeedCount: number;
    topN: number;
    exploration: RunPlan['exploration_level'];
    evaluationMode: RunPlan['evaluation']['mode'];
    counts: Record<AgentName, number>;
  }
> = {
  fast: {
    label: '快速探索',
    rounds: 1,
    nextSeedCount: 5,
    topN: 10,
    exploration: 'low',
    evaluationMode: 'fast',
    counts: { reinvent4: 5, crem: 5, autogrow4: 0 },
  },
  standard: {
    label: '标准优化',
    rounds: 3,
    nextSeedCount: 10,
    topN: 20,
    exploration: 'medium',
    evaluationMode: 'external_top_n',
    counts: { reinvent4: 10, crem: 10, autogrow4: 5 },
  },
  deep: {
    label: '深度探索',
    rounds: 5,
    nextSeedCount: 20,
    topN: 50,
    exploration: 'high',
    evaluationMode: 'external_top_n',
    counts: { reinvent4: 30, crem: 20, autogrow4: 10 },
  },
};

const CONSTRAINT_FIELDS = [
  { key: 'min_mw', label: 'MW 最小', min: 0, max: 1000, step: 1, fallback: 200 },
  { key: 'max_mw', label: 'MW 最大', min: 0, max: 1000, step: 1, fallback: 500 },
  { key: 'max_logp', label: 'cLogP 上限', min: -5, max: 10, step: 0.1, fallback: 4.5 },
  { key: 'max_sa_score', label: 'SA score 上限', min: 1, max: 10, step: 0.1, fallback: 4.5 },
  { key: 'min_tpsa', label: 'TPSA 最小', min: 0, max: 250, step: 1, fallback: 40 },
  { key: 'max_tpsa', label: 'TPSA 最大', min: 0, max: 250, step: 1, fallback: 120 },
  { key: 'max_hbd', label: 'HBD 上限', min: 0, max: 20, step: 1, fallback: 4 },
  { key: 'max_hba', label: 'HBA 上限', min: 0, max: 30, step: 1, fallback: 10 },
] as const;

export default function AgentControlPanel({
  runPlan,
  planDiff,
  warnings,
  isSaving,
  isRunning,
  onChange,
  onSave,
  onRun,
}: AgentControlPanelProps) {
  if (!runPlan) {
    return (
      <div className="rounded-lg border border-cyan-100 bg-white px-4 py-3 text-sm text-slate-500">
        加载 RunPlan...
      </div>
    );
  }

  const totalCount = (Object.keys(AGENT_LABELS) as AgentName[]).reduce(
    (sum, agentName) =>
      sum + (runPlan.agents[agentName]?.enabled === false ? 0 : runPlan.agents[agentName]?.requested_count ?? 0),
    0
  );

  const applyPreset = (presetId: PresetId) => {
    const preset = PRESETS[presetId];
    onChange({
      ...runPlan,
      max_rounds: preset.rounds,
      next_round_seed_count: preset.nextSeedCount,
      exploration_level: preset.exploration,
      agents: mapAgents(runPlan, (agentName, agentConfig) => ({
        ...agentConfig,
        requested_count: preset.counts[agentName],
        budget: preset.exploration,
        enabled:
          preset.counts[agentName] <= 0
            ? false
            : agentName === 'autogrow4'
              ? 'conditional'
              : true,
      })),
      evaluation: {
        ...runPlan.evaluation,
        mode: preset.evaluationMode,
        top_n: preset.topN,
        use_docking: preset.evaluationMode !== 'fast',
        use_admet: true,
        use_synthesis: true,
        synthesis_route_scope: 'final_round_top_n',
      },
      stopping: {
        ...runPlan.stopping,
        min_score_improvement: 0,
      },
    });
  };

  const updateAgentCount = (agentName: AgentName, value: number) => {
    const requestedCount = clampInteger(value, 0, 500);
    onChange({
      ...runPlan,
      agents: {
        ...runPlan.agents,
        [agentName]: {
          ...runPlan.agents[agentName],
          requested_count: requestedCount,
          enabled: requestedCount <= 0 ? false : agentName === 'autogrow4' ? 'conditional' : true,
        },
      },
    });
  };

  const updateNumber = (key: 'max_rounds' | 'next_round_seed_count', value: number, min: number, max: number) => {
    onChange({
      ...runPlan,
      [key]: clampInteger(value, min, max),
    });
  };

  const updateEvaluation = (key: keyof RunPlan['evaluation'], value: RunPlan['evaluation'][keyof RunPlan['evaluation']]) => {
    onChange({
      ...runPlan,
      evaluation: {
        ...runPlan.evaluation,
        [key]: value,
      },
    });
  };

  const updateConstraint = (key: string, value: number) => {
    onChange({
      ...runPlan,
      constraints: {
        ...runPlan.constraints,
        [key]: value,
      },
    });
  };

  const updateSeedText = (value: string) => {
    onChange({
      ...runPlan,
      seed_smiles: value
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean),
    });
  };

  return (
    <section className="rounded-lg border border-cyan-100 bg-white px-4 py-3 shadow-sm shadow-cyan-950/5">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-cyan-700" />
            <h2 className="text-sm font-semibold text-slate-950">Agent 操控台</h2>
            <span className="rounded-full border border-cyan-100 bg-cyan-50 px-2 py-0.5 text-[11px] font-medium text-cyan-800">
              {totalCount} / 轮
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {(Object.keys(PRESETS) as PresetId[]).map((presetId) => (
              <button
                key={presetId}
                type="button"
                onClick={() => applyPreset(presetId)}
                className="secondary-action rounded-lg px-3 py-1.5 text-xs font-medium"
              >
                {PRESETS[presetId].label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onSave}
            disabled={isSaving}
            className="secondary-action inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium disabled:cursor-not-allowed"
          >
            {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            保存计划
          </button>
          <button
            type="button"
            onClick={onRun}
            disabled={isRunning || totalCount < 1}
            className="primary-action inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium disabled:cursor-not-allowed"
          >
            {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            运行当前计划
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,0.7fr)]">
        <div className="space-y-3">
          <div className="grid gap-2 md:grid-cols-3">
            {(Object.keys(AGENT_LABELS) as AgentName[]).map((agentName) => (
              <NumberInput
                key={agentName}
                label={AGENT_LABELS[agentName]}
                value={runPlan.agents[agentName]?.requested_count ?? 0}
                min={0}
                max={500}
                step={1}
                onChange={(value) => updateAgentCount(agentName, value)}
              />
            ))}
          </div>

          <div className="grid gap-2 md:grid-cols-4">
            <NumberInput
              label="生成轮数"
              value={runPlan.max_rounds}
              min={1}
              max={20}
              step={1}
              onChange={(value) => updateNumber('max_rounds', value, 1, 20)}
            />
            <NumberInput
              label="Top N"
              value={runPlan.evaluation.top_n}
              min={1}
              max={500}
              step={1}
              onChange={(value) => updateEvaluation('top_n', clampInteger(value, 1, 500))}
            />
            <NumberInput
              label="下一轮 Top seed"
              value={runPlan.next_round_seed_count}
              min={1}
              max={100}
              step={1}
              onChange={(value) => updateNumber('next_round_seed_count', value, 1, 100)}
            />
            <label className="block rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <span className="block text-[11px] font-medium text-slate-500">评估模式</span>
              <select
                value={runPlan.evaluation.mode}
                onChange={(event) =>
                  updateEvaluation('mode', event.target.value as RunPlan['evaluation']['mode'])
                }
                className="mt-1 h-8 w-full rounded border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-500"
              >
                <option value="fast">快速</option>
                <option value="external_top_n">Top N 细筛</option>
                <option value="full">全量细筛</option>
              </select>
            </label>
          </div>

          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-700">
              <SlidersHorizontal className="h-3.5 w-3.5 text-cyan-700" />
              物化与合成约束
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {CONSTRAINT_FIELDS.map((field) => (
                <NumberInput
                  key={field.key}
                  label={field.label}
                  value={Number(runPlan.constraints[field.key] ?? field.fallback)}
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  onChange={(value) => updateConstraint(field.key, value)}
                />
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <label className="block rounded-lg border border-slate-200 bg-slate-50 p-3">
            <span className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-700">
              <Beaker className="h-3.5 w-3.5 text-cyan-700" />
              额外 seed SMILES
            </span>
            <textarea
              value={(runPlan.seed_smiles ?? []).join('\n')}
              onChange={(event) => updateSeedText(event.target.value)}
              rows={6}
              className="w-full resize-none rounded border border-slate-200 bg-white px-3 py-2 font-mono text-xs leading-5 text-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </label>

          <div className="grid grid-cols-2 gap-2 text-xs">
            <ToggleField
              label="Docking"
              checked={runPlan.evaluation.use_docking}
              onChange={(checked) => updateEvaluation('use_docking', checked)}
            />
            <ToggleField
              label="ADMET"
              checked={runPlan.evaluation.use_admet}
              onChange={(checked) => updateEvaluation('use_admet', checked)}
            />
            <ToggleField
              label="合成可行性"
              checked={runPlan.evaluation.use_synthesis}
              onChange={(checked) => updateEvaluation('use_synthesis', checked)}
            />
            <ToggleField
              label="规则过滤"
              checked={runPlan.evaluation.use_filters}
              onChange={(checked) => updateEvaluation('use_filters', checked)}
            />
          </div>

          <label className="block rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <span className="block text-[11px] font-medium text-slate-500">合成路线预测</span>
            <select
              value={runPlan.evaluation.synthesis_route_scope}
              onChange={(event) =>
                updateEvaluation(
                  'synthesis_route_scope',
                  event.target.value as RunPlan['evaluation']['synthesis_route_scope']
                )
              }
              className="mt-1 h-8 w-full rounded border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-500"
            >
              <option value="final_round_top_n">最终轮 Top N</option>
              <option value="every_round_top_n">每轮 Top N</option>
              <option value="disabled">不预测路线</option>
            </select>
          </label>
        </div>
      </div>

      {(planDiff.length > 0 || warnings.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          {planDiff.slice(0, 5).map((change) => (
            <span key={`${change.path}-${String(change.new_value)}`} className="rounded-full bg-cyan-50 px-2 py-1 text-cyan-800">
              {change.path}
            </span>
          ))}
          {warnings.map((warning) => (
            <span key={warning} className="rounded-full bg-amber-50 px-2 py-1 text-amber-800">
              {warning}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function NumberInput({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block rounded-lg border border-slate-200 bg-white px-3 py-2">
      <span className="block text-[11px] font-medium text-slate-500">{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : min}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-1 h-8 w-full rounded border border-slate-200 px-2 text-xs font-semibold text-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-500"
      />
    </label>
  );
}

function ToggleField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <span className="font-medium text-slate-700">{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
      />
    </label>
  );
}

function mapAgents(
  runPlan: RunPlan,
  mapper: (agentName: AgentName, agentConfig: RunPlan['agents'][AgentName]) => RunPlan['agents'][AgentName]
) {
  return (Object.keys(runPlan.agents) as AgentName[]).reduce<RunPlan['agents']>((agents, agentName) => {
    agents[agentName] = mapper(agentName, runPlan.agents[agentName]);
    return agents;
  }, {} as RunPlan['agents']);
}

function clampInteger(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(Math.round(value), max));
}
