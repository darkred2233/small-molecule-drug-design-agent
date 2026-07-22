import { describe, expect, it } from 'vitest';
import { currentStageProgress } from '@/lib/round-progress';

describe('round execution progress', () => {
  it('does not report a running round as complete merely because campaign generation has finished', () => {
    expect(currentStageProgress('running', { percent: 30 })).toBe(30);
  });

  it('reports 100 only after the round itself has completed', () => {
    expect(currentStageProgress('completed', { percent: 30 })).toBe(100);
  });
});
