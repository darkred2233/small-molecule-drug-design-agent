export interface ExecutionProgress {
  percent?: number | null;
}

export function isActiveRound(status: string | null | undefined): boolean {
  return status === 'queued' || status === 'running';
}

export function currentStageProgress(
  roundStatus: string | null | undefined,
  executionProgress: ExecutionProgress | null | undefined,
): number {
  if (roundStatus === 'completed') return 100;
  const percent = executionProgress?.percent;
  if (typeof percent !== 'number' || !Number.isFinite(percent)) return 0;
  return Math.max(0, Math.min(99, Math.round(percent)));
}
