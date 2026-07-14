export function decisionTone(value: string) {
  const normalized = value.toLowerCase();
  if (normalized.includes('reject') || normalized.includes('fail') || normalized.includes('high_risk')) {
    return 'rose';
  }
  if (normalized.includes('warn') || normalized.includes('medium') || normalized.includes('reserve')) {
    return 'amber';
  }
  if (normalized.includes('recommend') || normalized.includes('pass') || normalized.includes('found') || normalized.includes('low_risk')) {
    return 'emerald';
  }
  if (normalized.includes('risk')) {
    return 'rose';
  }
  return 'cyan';
}
