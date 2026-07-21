import type { LucideIcon } from 'lucide-react';

export function EmptyState({ icon: Icon, title, detail, action }: { icon: LucideIcon; title: string; detail: string; action?: React.ReactNode }) {
  return <div className="empty-state"><Icon size={30} strokeWidth={1.5} /><div><strong>{title}</strong><div>{detail}</div></div>{action}</div>;
}
