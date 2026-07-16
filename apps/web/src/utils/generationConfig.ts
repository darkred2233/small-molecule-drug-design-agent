import type { AssessmentMode } from '@/types/api';

export interface StrategyCounts {
  reinvent4: number;
  crem: number;
  autogrow4: number;
}

export const DEFAULT_STRATEGY_COUNTS: StrategyCounts = {
  reinvent4: 10,
  crem: 10,
  autogrow4: 10,
};

export const STRATEGY_LABELS: Record<keyof StrategyCounts, string> = {
  reinvent4: 'REINVENT4',
  crem: 'CREM',
  autogrow4: 'AutoGrow4',
};

export const STRATEGY_KEYS = Object.keys(DEFAULT_STRATEGY_COUNTS) as Array<keyof StrategyCounts>;

export function clampInteger(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, Math.round(value)));
}

export function sumStrategyCounts(strategyCounts: StrategyCounts) {
  return STRATEGY_KEYS.reduce((sum, strategy) => sum + strategyCounts[strategy], 0);
}

export function updateStrategyCount(
  current: StrategyCounts,
  strategy: keyof StrategyCounts,
  value: number
): StrategyCounts {
  return {
    ...current,
    [strategy]: clampInteger(value, 0, 500),
  };
}

export function buildRoundGenerationConfig(
  strategyCounts: StrategyCounts,
  topN: number,
  assessmentMode: AssessmentMode = 'external'
) {
  const generationSize = sumStrategyCounts(strategyCounts);
  const normalizedTopN = clampInteger(topN, 1, 500);
  return {
    strategy_counts: strategyCounts,
    generation_size: generationSize,
    top_n: normalizedTopN,
    max_assessment_molecules: Math.min(500, Math.max(generationSize, normalizedTopN)),
    assessment_mode: assessmentMode,
    external_top_n: Math.min(100, normalizedTopN),
    generate_when_seeds_exist: true,
  };
}

export function strategyCountsFromConfig(config: Record<string, any> | undefined): StrategyCounts {
  if (!config) return DEFAULT_STRATEGY_COUNTS;

  const rawCounts = config?.strategy_counts;
  if (rawCounts && typeof rawCounts === 'object') {
    return {
      reinvent4: clampInteger(Number(rawCounts.reinvent4), 0, 500),
      crem: clampInteger(Number(rawCounts.crem), 0, 500),
      autogrow4: clampInteger(Number(rawCounts.autogrow4), 0, 500),
    };
  }

  const strategies = Array.isArray(config?.strategies) ? config.strategies : STRATEGY_KEYS;
  const generationSize = config?.generation_size
    ? clampInteger(Number(config.generation_size), 1, 500)
    : sumStrategyCounts(DEFAULT_STRATEGY_COUNTS);
  const selected = STRATEGY_KEYS.filter((strategy) => strategies.includes(strategy));
  if (!selected.length) return DEFAULT_STRATEGY_COUNTS;

  const base = Math.floor(generationSize / selected.length);
  const remainder = generationSize % selected.length;
  const counts: StrategyCounts = { reinvent4: 0, crem: 0, autogrow4: 0 };
  selected.forEach((strategy, index) => {
    counts[strategy] = base + (index < remainder ? 1 : 0);
  });
  return counts;
}
