export function formatNumber(value: number | null | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '—' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export function methodLabel(method: string | null | undefined): string {
  const labels: Record<string, string> = { crem: 'CReM 片段编辑', targetdiff: 'TargetDiff 口袋生成', autogrow4: 'AutoGrow4 生长' };
  return method ? labels[method.toLowerCase()] || method : '未记录';
}

export function statusLabel(status: string | null | undefined): string {
  const labels: Record<string, string> = {
    created: '已创建', draft: '策略草案', pending: '待确认', confirmed: '已确认', running: '执行中', completed: '已完成', failed: '失败', disabled: '未启用', skipped: '已跳过',
    pipeline_queued: '已排队', pipeline_running: '执行中', pipeline_completed: '已完成', pipeline_failed: '失败',
  };
  return status ? labels[status.toLowerCase()] || status : '未知';
}

export function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'running' {
  const normalized = status?.toLowerCase() || '';
  if (['completed', 'confirmed', 'success'].includes(normalized)) return 'success';
  if (['running', 'pipeline_running', 'queued', 'pipeline_queued'].includes(normalized)) return 'running';
  if (['failed', 'error'].includes(normalized)) return 'danger';
  if (['draft', 'pending', 'created'].includes(normalized)) return 'warning';
  return 'neutral';
}

export function campaignCount(config: Record<string, unknown> | undefined): number {
  const value = config?.num_molecules ?? config?.sample_count;
  return typeof value === 'number' ? value : 0;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export function campaignDiagnosticSummary(metrics: Record<string, unknown> | null | undefined): string | null {
  const execution = recordValue(metrics?.execution);
  const parts: string[] = [];
  const failureReason = metrics?.failure_reason;
  if (typeof failureReason === 'string' && failureReason) parts.push(failureReason);
  const exitCode = execution?.exit_code;
  if (typeof exitCode === 'number') parts.push(`退出码 ${exitCode}`);
  const stderr = execution?.stderr;
  if (typeof stderr === 'string' && stderr.trim()) {
    const lines = stderr.trim().split(/\r?\n/).filter(Boolean);
    const lastLine = lines[lines.length - 1] || stderr.trim();
    parts.push(lastLine.length > 280 ? `${lastLine.slice(0, 277)}...` : lastLine);
  }
  return parts.length ? parts.join(' · ') : null;
}
