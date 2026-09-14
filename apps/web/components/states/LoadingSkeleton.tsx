import React from 'react';
import { cn } from '../../lib/utils';

export function LoadingSkeleton({
  className,
  rows = 4,
}: {
  className?: string;
  rows?: number;
}) {
  return (
    <div className={cn('w-full space-y-3 animate-pulse', className)}>
      <div className="h-6 bg-surface-subtle rounded w-1/3" />
      <div className="space-y-2 pt-2">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-10 bg-surface-subtle/80 rounded w-full border border-border/40"
          />
        ))}
      </div>
    </div>
  );
}
