import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Atom,
  Beaker,
  Check,
  ClipboardList,
  GitBranch,
  PencilLine,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Target,
} from 'lucide-react';
import { projectsApi } from '@/api';
import { useWorkspaceStore } from '@/state/workspaceStore';
import type { Project } from '@/types/api';
import {
  DEFAULT_PHYSCHEM_CONSTRAINTS,
  DESIGN_GOALS,
  GENERATION_STRATEGIES,
  OPTIMIZATION_PRIORITIES,
  type DesignGoalId,
  type GenerationStrategyId,
  type OptimizationPriorityId,
  type PhyschemConstraints,
  type SeedMolecule,
  buildDesignPrompt,
  getDefaultPriorityIdsForGoal,
} from '@/utils/designGuidance';
import { cn } from '@/utils/helpers';

interface DesignGuidancePanelProps {
  project: Project | null;
  variant?: 'full' | 'compact';
  onSendPrompt?: (prompt: string) => void;
  className?: string;
}

const WORKFLOW_STEPS = [
  '约束解析',
  '种子导入',
  '分子生成',
  '结构校验',
  'ADMET/对接',
  '逆合成',
  '排序与报告',
];

export default function DesignGuidancePanel({
  project,
  variant = 'full',
  onSendPrompt,
  className,
}: DesignGuidancePanelProps) {
  const setComposerDraftAction = useWorkspaceStore((state) => state.setComposerDraft);
  const [goalId, setGoalId] = useState<DesignGoalId>('lead_optimization');
  const [strategyId, setStrategyId] = useState<GenerationStrategyId>('reinvent4');
  const [priorityIds, setPriorityIds] = useState<OptimizationPriorityId[]>(
    getDefaultPriorityIdsForGoal('lead_optimization')
  );
  const [constraints, setConstraints] = useState<PhyschemConstraints>(
    DEFAULT_PHYSCHEM_CONSTRAINTS
  );
  const [selectedSeedSmiles, setSelectedSeedSmiles] = useState<string[]>([]);
  const [customSeedSmiles, setCustomSeedSmiles] = useState('');

  const { data: targets, isLoading: targetsLoading } = useQuery({
    queryKey: ['builtin-targets'],
    queryFn: projectsApi.getBuiltinTargets,
  });

  const target = useMemo(
    () => targets?.find((item) => item.target_id === project?.target_id) ?? null,
    [project?.target_id, targets]
  );

  const seedOptions = useMemo<SeedMolecule[]>(
    () =>
      target?.drugs
        .filter((drug) => Boolean(drug.smiles))
        .slice(0, 6)
        .map((drug) => ({
          name: drug.drug_name,
          smiles: drug.smiles ?? '',
          note: drug.drug_status ?? undefined,
        })) ?? [],
    [target]
  );

  useEffect(() => {
    setSelectedSeedSmiles(seedOptions.slice(0, 2).map((seed) => seed.smiles));
  }, [seedOptions]);

  const selectedSeeds = useMemo(
    () => seedOptions.filter((seed) => selectedSeedSmiles.includes(seed.smiles)),
    [seedOptions, selectedSeedSmiles]
  );

  const prompt = useMemo(
    () =>
      buildDesignPrompt({
        project,
        target,
        goalId,
        strategyId,
        priorityIds,
        constraints,
        selectedSeeds,
        customSeedSmiles,
      }),
    [constraints, customSeedSmiles, goalId, priorityIds, project, selectedSeeds, strategyId, target]
  );

  const handleGoalSelect = (nextGoalId: DesignGoalId) => {
    setGoalId(nextGoalId);
    setPriorityIds(getDefaultPriorityIdsForGoal(nextGoalId));
    if (nextGoalId === 'scaffold_hopping') {
      setStrategyId('scaffold');
    } else if (nextGoalId === 'hit_finding') {
      setStrategyId('reinvent4');
    }
  };

  const togglePriority = (priorityId: OptimizationPriorityId) => {
    setPriorityIds((current) =>
      current.includes(priorityId)
        ? current.filter((item) => item !== priorityId)
        : [...current, priorityId]
    );
  };

  const toggleSeed = (smiles: string) => {
    setSelectedSeedSmiles((current) =>
      current.includes(smiles)
        ? current.filter((item) => item !== smiles)
        : [...current, smiles]
    );
  };

  const updateConstraint = (key: keyof PhyschemConstraints, value: number) => {
    setConstraints((current) => ({ ...current, [key]: value }));
  };

  const setDraft = (content: string) => {
    if (typeof setComposerDraftAction === 'function') {
      setComposerDraftAction(content);
      return;
    }
    useWorkspaceStore.setState((state) => ({
      composerDraft: {
        content,
        version: (state.composerDraft?.version ?? 0) + 1,
      },
    }));
  };

  const handleFillDraft = () => {
    setDraft(prompt);
  };

  const handleSendPrompt = () => {
    if (onSendPrompt) {
      onSendPrompt(prompt);
      return;
    }
    setDraft(prompt);
  };

  const sectionClass = 'rounded-lg border border-cyan-100 bg-white p-4 shadow-sm shadow-cyan-950/5';
  const compact = variant === 'compact';

  return (
    <div className={cn('space-y-4 text-left', className)}>
      <div className={cn(sectionClass, compact && 'p-4')}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
              <ClipboardList className="h-4 w-4 text-cyan-700" />
              下一轮设计向导
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              这里生成的是设计意图和下一轮偏好；当前运行预算以新建项目和运行配置为准。
            </p>
          </div>
          <span className="chem-badge">Drug Design</span>
        </div>

        <div className="mt-4 rounded-lg border border-cyan-100 bg-cyan-50/60 p-3">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-white p-2 text-cyan-700">
              <Target className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-slate-900">
                {target?.name ?? project?.target_id ?? '未选择靶点'}
              </div>
              <div className="mt-1 text-xs text-slate-600">
                {targetsLoading
                  ? '正在匹配内置靶点库...'
                  : target?.summary ?? project?.objective ?? '可在新建项目时选择靶点，或在对话中补充靶点信息。'}
              </div>
              {target && (
                <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                  <span className="rounded bg-white px-2 py-0.5 text-cyan-700">
                    {target.target_id}
                  </span>
                  {target.uniprot_id && (
                    <span className="rounded bg-white px-2 py-0.5 text-slate-600">
                      UniProt {target.uniprot_id}
                    </span>
                  )}
                  {target.pdb_ids.length > 0 && (
                    <span className="rounded bg-white px-2 py-0.5 text-emerald-700">
                      PDB {target.pdb_ids.slice(0, 3).join(', ')}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className={sectionClass}>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950">
          <Atom className="h-4 w-4 text-cyan-700" />
          1. 选择设计目标
        </div>
        <div className={cn('grid gap-2', compact ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1')}>
          {DESIGN_GOALS.map((goal) => (
            <button
              key={goal.id}
              type="button"
              onClick={() => handleGoalSelect(goal.id)}
              className={cn(
                'min-h-[76px] rounded-lg border p-3 text-left transition-colors',
                goalId === goal.id
                  ? 'border-cyan-500 bg-cyan-50 text-cyan-950 ring-1 ring-cyan-500'
                  : 'border-cyan-100 bg-white text-slate-700 hover:border-cyan-300 hover:bg-cyan-50/50'
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{goal.label}</span>
                {goalId === goal.id && <Check className="h-4 w-4 text-cyan-700" />}
              </div>
              <p className="mt-1 text-xs leading-5 text-slate-500">{goal.description}</p>
            </button>
          ))}
        </div>
      </div>

      <div className={sectionClass}>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950">
          <GitBranch className="h-4 w-4 text-cyan-700" />
          2. 下一轮生成偏好
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {GENERATION_STRATEGIES.map((strategy) => (
            <button
              key={strategy.id}
              type="button"
              onClick={() => setStrategyId(strategy.id)}
              className={cn(
                'min-h-[70px] rounded-lg border px-3 py-2 text-left transition-colors',
                strategyId === strategy.id
                  ? 'border-emerald-500 bg-emerald-50 text-emerald-950 ring-1 ring-emerald-500'
                  : 'border-cyan-100 bg-white text-slate-700 hover:border-emerald-300 hover:bg-emerald-50/50'
              )}
            >
              <div className="text-xs font-semibold">{strategy.label}</div>
              <div className="mt-1 text-[11px] leading-4 text-slate-500">{strategy.description}</div>
            </button>
          ))}
        </div>
      </div>

      <div className={sectionClass}>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950">
          <ShieldCheck className="h-4 w-4 text-cyan-700" />
          3. 优化优先级
        </div>
        <div className="flex flex-wrap gap-2">
          {OPTIMIZATION_PRIORITIES.map((priority) => {
            const selected = priorityIds.includes(priority.id);
            return (
              <button
                key={priority.id}
                type="button"
                onClick={() => togglePriority(priority.id)}
                className={cn(
                  'inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                  selected
                    ? 'border-cyan-500 bg-cyan-600 text-white'
                    : 'border-cyan-100 bg-white text-slate-600 hover:border-cyan-300 hover:bg-cyan-50'
                )}
              >
                {selected && <Check className="h-3 w-3" />}
                {priority.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className={sectionClass}>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950">
          <SlidersHorizontal className="h-4 w-4 text-cyan-700" />
          4. 物化与合成约束
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <NumberField
            label="MW 最小"
            value={constraints.mwMin}
            onChange={(value) => updateConstraint('mwMin', value)}
            min={100}
            max={1000}
            step={10}
          />
          <NumberField
            label="MW 最大"
            value={constraints.mwMax}
            onChange={(value) => updateConstraint('mwMax', value)}
            min={100}
            max={1000}
            step={10}
          />
          <NumberField
            label="cLogP 上限"
            value={constraints.logpMax}
            onChange={(value) => updateConstraint('logpMax', value)}
            min={0}
            max={8}
            step={0.1}
          />
          <NumberField
            label="SA score 上限"
            value={constraints.saScoreMax}
            onChange={(value) => updateConstraint('saScoreMax', value)}
            min={1}
            max={10}
            step={0.1}
          />
          <NumberField
            label="TPSA 最小"
            value={constraints.tpsaMin}
            onChange={(value) => updateConstraint('tpsaMin', value)}
            min={0}
            max={250}
            step={5}
          />
          <NumberField
            label="TPSA 最大"
            value={constraints.tpsaMax}
            onChange={(value) => updateConstraint('tpsaMax', value)}
            min={0}
            max={250}
            step={5}
          />
          <NumberField
            label="HBD 上限"
            value={constraints.hbdMax}
            onChange={(value) => updateConstraint('hbdMax', value)}
            min={0}
            max={12}
            step={1}
          />
          <NumberField
            label="HBA 上限"
            value={constraints.hbaMax}
            onChange={(value) => updateConstraint('hbaMax', value)}
            min={0}
            max={16}
            step={1}
          />
        </div>
      </div>

      <div className={sectionClass}>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950">
          <Beaker className="h-4 w-4 text-cyan-700" />
          5. 种子/参考分子
        </div>
        {seedOptions.length > 0 ? (
          <div className="space-y-2">
            {seedOptions.map((seed) => {
              const selected = selectedSeedSmiles.includes(seed.smiles);
              return (
                <label
                  key={seed.smiles}
                  className={cn(
                    'flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors',
                    selected
                      ? 'border-emerald-300 bg-emerald-50/70'
                      : 'border-cyan-100 bg-white hover:bg-cyan-50/50'
                  )}
                >
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleSeed(seed.smiles)}
                    className="mt-1 h-4 w-4 accent-cyan-600"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-slate-800">{seed.name}</span>
                    <span className="mt-1 block truncate font-mono text-[11px] text-slate-500">
                      {seed.smiles}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-cyan-200 bg-cyan-50/40 p-3 text-sm text-slate-500">
            当前靶点暂无内置参考分子，可以在下方粘贴 SMILES。
          </div>
        )}
        <textarea
          value={customSeedSmiles}
          onChange={(event) => setCustomSeedSmiles(event.target.value)}
          placeholder="可选：每行粘贴一个自定义 seed SMILES"
          rows={3}
          className="mt-3 w-full resize-none rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm shadow-sm shadow-cyan-950/5 focus:outline-none focus:ring-2 focus:ring-cyan-500"
        />
      </div>

      <div className={sectionClass}>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950">
          <ClipboardList className="h-4 w-4 text-cyan-700" />
          推荐执行路径
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {WORKFLOW_STEPS.map((step, index) => (
            <div
              key={step}
              className="flex min-h-[44px] items-center gap-2 rounded-lg border border-cyan-100 bg-cyan-50/40 px-3 py-2 text-xs text-slate-700"
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-[10px] font-semibold text-cyan-700">
                {index + 1}
              </span>
              {step}
            </div>
          ))}
        </div>
      </div>

      <div
        className={cn(
          'rounded-lg border border-cyan-100 bg-white/95 p-3 shadow-lg shadow-cyan-950/10 backdrop-blur',
          !compact && 'sticky bottom-0'
        )}
      >
        {onSendPrompt ? (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleFillDraft}
              className="secondary-action flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium"
            >
              <PencilLine className="h-4 w-4" />
              填入对话
            </button>
            <button
              type="button"
              onClick={handleSendPrompt}
              className="primary-action flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium"
            >
              <Send className="h-4 w-4" />
              发送给 Agent
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={handleFillDraft}
            className="primary-action flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium"
          >
            <PencilLine className="h-4 w-4" />
            填入中间对话
          </button>
        )}
      </div>
    </div>
  );
}

interface NumberFieldProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
}

function NumberField({ label, value, onChange, min, max, step }: NumberFieldProps) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-9 w-full rounded-lg border border-cyan-200 bg-white px-2 text-sm text-slate-800 shadow-sm shadow-cyan-950/5 focus:outline-none focus:ring-2 focus:ring-cyan-500"
      />
    </label>
  );
}
