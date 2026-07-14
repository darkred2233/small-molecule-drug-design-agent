/**
 * Utility Functions
 */

import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merge Tailwind CSS classes
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format date to localized string
 */
export function formatDate(date: string | Date): string {
  const d = typeof date === 'string' ? new Date(date) : date;
  return d.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Format number with specified decimals
 */
export function formatNumber(num: number | null | undefined, decimals = 2): string {
  if (num === undefined || num === null) return '-';
  return num.toFixed(decimals);
}

/**
 * Get status color class
 */
export function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    created: 'bg-slate-100 text-slate-700 border border-slate-200',
    pipeline_queued: 'bg-cyan-50 text-cyan-700 border border-cyan-200',
    pipeline_running: 'bg-amber-50 text-amber-700 border border-amber-200',
    pipeline_completed: 'bg-emerald-50 text-emerald-700 border border-emerald-200',
    pipeline_failed: 'bg-rose-50 text-rose-700 border border-rose-200',
    passed_filter: 'bg-emerald-50 text-emerald-700 border border-emerald-200',
    failed_filter: 'bg-rose-50 text-rose-700 border border-rose-200',
    recommended: 'bg-emerald-50 text-emerald-700 border border-emerald-200',
    reserve: 'bg-sky-50 text-sky-700 border border-sky-200',
    generated: 'bg-cyan-50 text-cyan-700 border border-cyan-200',
    admet_risky: 'bg-amber-50 text-amber-700 border border-amber-200',
    synthesis_risky: 'bg-amber-50 text-amber-700 border border-amber-200',
    critic_rejected: 'bg-rose-50 text-rose-700 border border-rose-200',
  };
  return colors[status] || 'bg-slate-100 text-slate-700 border border-slate-200';
}

/**
 * Get confidence level label
 */
export function getConfidenceLabel(confidence: number | null | undefined): string {
  if (confidence === undefined || confidence === null) return 'unknown';
  if (confidence >= 0.75) return 'high';
  if (confidence >= 0.5) return 'medium';
  return 'low';
}

/**
 * Get confidence color
 */
export function getConfidenceColor(confidence: number | null | undefined): string {
  if (confidence === undefined || confidence === null) {
    return 'bg-slate-50 text-slate-600 border border-slate-200';
  }
  if (confidence >= 0.75) return 'bg-emerald-50 text-emerald-700 border border-emerald-200';
  if (confidence >= 0.5) return 'bg-amber-50 text-amber-700 border border-amber-200';
  return 'bg-rose-50 text-rose-700 border border-rose-200';
}

/**
 * Truncate text
 */
export function truncate(text: string, length: number): string {
  if (text.length <= length) return text;
  return text.substring(0, length) + '...';
}

/**
 * Copy to clipboard
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    console.error('Failed to copy:', err);
    return false;
  }
}

/**
 * Download text as file
 */
export function downloadAsFile(content: string, filename: string, mimeType = 'text/plain') {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
