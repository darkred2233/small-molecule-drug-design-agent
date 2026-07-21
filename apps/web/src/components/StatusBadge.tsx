import { Circle } from 'lucide-react';
import { statusLabel, statusTone } from '@/lib/format';

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const tone = statusTone(status);
  return <span className={`badge badge-${tone}`}><Circle size={7} fill="currentColor" strokeWidth={0} />{statusLabel(status)}</span>;
}
