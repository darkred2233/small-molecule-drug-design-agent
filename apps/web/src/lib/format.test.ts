import { describe, expect, it } from 'vitest';
import { campaignCount, methodLabel, statusLabel, statusTone } from '@/lib/format';

describe('workbench formatting', () => {
  it('uses Chinese labels for workflow status and generation methods', () => {
    expect(statusLabel('running')).toBe('执行中');
    expect(methodLabel('crem')).toBe('CReM 片段编辑');
  });

  it('keeps campaign count compatible with every generation config', () => {
    expect(campaignCount({ num_molecules: 80 })).toBe(80);
    expect(campaignCount({ sample_count: 120 })).toBe(120);
  });

  it('maps terminal failure to the danger tone', () => {
    expect(statusTone('failed')).toBe('danger');
  });

  it('labels disabled and skipped stages without reporting them as failures', () => {
    expect(statusLabel('disabled')).toBe('未启用');
    expect(statusLabel('skipped')).toBe('已跳过');
    expect(statusTone('disabled')).toBe('neutral');
    expect(statusTone('skipped')).toBe('neutral');
  });
});
