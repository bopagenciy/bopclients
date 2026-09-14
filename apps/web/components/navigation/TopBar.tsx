'use client';

import React from 'react';
import { useAuth } from '../../lib/auth/context';
import { LocaleSwitcher } from './LocaleSwitcher';
import { UserMenu } from './UserMenu';
import { ShieldCheck, Shield } from 'lucide-react';
import { Badge } from '../ui/Badge';

export function TopBar() {
  const { activeOrg, activeRole } = useAuth();

  return (
    <header className="h-16 border-b border-border bg-surface px-6 flex items-center justify-between shrink-0 sticky top-0 z-20 shadow-xs">
      {/* Active Organization & Context */}
      <div className="flex items-center gap-3">
        {activeOrg && (
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-foreground">
              {activeOrg.name}
            </span>
            <span className="text-border">/</span>
            <Badge size="sm" variant="gold">
              <Shield className="w-3 h-3 mr-1 inline" />
              {activeRole || 'VIEWER'}
            </Badge>
          </div>
        )}
      </div>

      {/* Action Controls */}
      <div className="flex items-center gap-4">
        <div className="hidden sm:flex items-center gap-1.5 px-2 py-1 rounded bg-surface-subtle border border-border/70 text-[11px] text-foreground-muted font-mono">
          <ShieldCheck className="w-3.5 h-3.5 text-brand-gold" />
          <span>BFF HttpOnly Active</span>
        </div>

        <LocaleSwitcher />

        <div className="h-5 w-px bg-border" />

        <UserMenu />
      </div>
    </header>
  );
}
