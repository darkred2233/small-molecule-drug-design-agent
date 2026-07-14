/**
 * Generic Badge Component (shadcn-style)
 */

import { HTMLAttributes } from 'react';
import { cn } from '@/utils/helpers';

export interface BadgeProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning';
}

export default function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  return (
    <div
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors',
        {
          'bg-blue-100 text-blue-800': variant === 'default',
          'bg-gray-100 text-gray-800': variant === 'secondary',
          'bg-red-100 text-red-800': variant === 'destructive',
          'bg-green-100 text-green-800': variant === 'success',
          'bg-yellow-100 text-yellow-800': variant === 'warning',
          'border border-gray-300 text-gray-700': variant === 'outline',
        },
        className
      )}
      {...props}
    />
  );
}
