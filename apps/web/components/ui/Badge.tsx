import React from 'react';
import { cn } from '../../lib/utils';

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'gold' | 'outline';
  size?: 'sm' | 'md';
}

export function Badge({
  className,
  variant = 'default',
  size = 'md',
  children,
  ...props
}: BadgeProps) {
  const base =
    'inline-flex items-center font-medium rounded-full border transition-colors select-none';

  const variants = {
    default: 'bg-surface-subtle text-foreground border-border',
    success: 'bg-emerald-50 text-emerald-700 border-emerald-200/80',
    warning: 'bg-amber-50 text-amber-800 border-amber-200/80',
    danger: 'bg-rose-50 text-rose-700 border-rose-200/80',
    info: 'bg-sky-50 text-sky-700 border-sky-200/80',
    gold: 'bg-amber-50/50 text-amber-900 border-brand-gold/40',
    outline: 'bg-transparent text-foreground border-border',
  };

  const sizes = {
    sm: 'text-[11px] px-2 py-0.5 leading-none',
    md: 'text-xs px-2.5 py-1',
  };

  return (
    <div className={cn(base, variants[variant], sizes[size], className)} {...props}>
      {children}
    </div>
  );
}
