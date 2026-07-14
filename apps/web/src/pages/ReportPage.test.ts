import { describe, expect, it } from 'vitest';
import { decisionTone } from '@/utils/reportPresentation';

describe('report status tone mapping', () => {
  it('treats high-risk ADMET labels as risk, not success', () => {
    expect(decisionTone('high_risk')).toBe('rose');
    expect(decisionTone('hERG_high_risk')).toBe('rose');
    expect(decisionTone('low_risk')).toBe('emerald');
  });
});
