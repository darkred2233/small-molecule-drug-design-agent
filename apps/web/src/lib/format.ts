export function formatNumber(value: number | null | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '—' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export function methodLabel(method: string | null | undefined): string {
  const labels: Record<string, string> = { crem: 'CReM 片段编辑', reinvent4: 'REINVENT4 生成', autogrow4: 'AutoGrow4 生长' };
  return method ? labels[method.toLowerCase()] || method : '未记录';
}

export function statusLabel(status: string | null | undefined): string {
  const labels: Record<string, string> = {
    created: '已创建', draft: '策略草案', pending: '待确认', confirmed: '已确认', running: '执行中', completed: '已完成', failed: '失败',
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
