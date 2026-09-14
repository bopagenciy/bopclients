import React from 'react';
import { cn } from '../../lib/utils';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, hint, id, ...props }, ref) => {
    const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);

    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label htmlFor={inputId} className="block text-xs font-semibold text-foreground">
            {label}
          </label>
        )}
        <input
          id={inputId}
          ref={ref}
          className={cn(
            'flex h-10 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground placeholder:text-foreground-muted/60 transition-colors focus:outline-none focus:ring-2 focus:ring-brand-dark focus:border-transparent disabled:cursor-not-allowed disabled:opacity-50',
            error && 'border-status-danger focus:ring-status-danger',
            className
          )}
          {...props}
        />
        {hint && !error && (
          <p className="text-xs text-foreground-muted">{hint}</p>
        )}
        {error && (
          <p className="text-xs text-status-danger font-medium">{error}</p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';
