import { describe, expect, it } from 'vitest';
import { formatNumber, getConfidenceColor, getConfidenceLabel, getStatusColor } from './helpers';

describe('frontend helper utilities', () => {
  it('formats nullable scientific values safely', () => {
    expect(formatNumber(312.456)).toBe('312.46');
    expect(formatNumber(0.8764, 3)).toBe('0.876');
    expect(formatNumber(null)).toBe('-');
    expect(formatNumber(undefined)).toBe('-');
  });

  it('labels confidence values including missing model scores', () => {
    expect(getConfidenceLabel(0.9)).toBe('high');
    expect(getConfidenceLabel(0.6)).toBe('medium');
    expect(getConfidenceLabel(0.2)).toBe('low');
    expect(getConfidenceLabel(null)).toBe('unknown');
    expect(getConfidenceColor(undefined)).toContain('slate');
  });

  it('returns themed status classes for pipeline and molecule states', () => {
    expect(getStatusColor('pipeline_completed')).toContain('emerald');
    expect(getStatusColor('pipeline_failed')).toContain('rose');
    expect(getStatusColor('generated')).toContain('cyan');
    expect(getStatusColor('not_a_known_status')).toContain('slate');
  });
});
