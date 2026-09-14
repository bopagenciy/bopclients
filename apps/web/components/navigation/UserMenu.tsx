'use client';

import React, { useState, useRef, useEffect } from 'react';
import { useAuth } from '../../lib/auth/context';
import { useI18n } from '../../lib/i18n/context';
import { LogOut, User as UserIcon, Shield } from 'lucide-react';
import { Badge } from '../ui/Badge';

export function UserMenu() {
  const { user, activeRole, logout } = useAuth();
  const { t } = useI18n();
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  if (!user) return null;

  const initials = (user.full_name || user.email)
    .split(' ')
    .map((n) => n[0])
    .join('')
    .substring(0, 2)
    .toUpperCase();

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 p-1 rounded-full border border-border bg-surface hover:bg-surface-subtle transition-colors focus:outline-none focus:ring-2 focus:ring-brand-dark"
        aria-haspopup="menu"
        aria-expanded={isOpen}
      >
        <div className="w-8 h-8 rounded-full bg-brand-dark text-white flex items-center justify-center text-xs font-semibold">
          {initials}
        </div>
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-64 rounded-xl border border-border bg-surface p-2 shadow-xl z-50 animate-in fade-in zoom-in-95">
          <div className="px-3 py-2 border-b border-border/70">
            <p className="text-sm font-semibold text-foreground truncate">
              {user.full_name || user.email}
            </p>
            <p className="text-xs text-foreground-muted truncate">{user.email}</p>
            <div className="mt-2 flex items-center gap-1.5">
              <Badge size="sm" variant="gold">
                <Shield className="w-3 h-3 mr-1 inline" />
                {activeRole || 'VIEWER'}
              </Badge>
            </div>
          </div>

          <div className="mt-2 pt-1">
            <button
              onClick={() => {
                setIsOpen(false);
                logout();
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-status-danger rounded-md hover:bg-rose-50 transition-colors text-left"
            >
              <LogOut className="w-4 h-4" />
              <span>{t('auth.logout_button')}</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
