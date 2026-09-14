'use client';

import React, { useState, useRef, useEffect } from 'react';
import { useAuth } from '../../lib/auth/context';
import { useI18n } from '../../lib/i18n/context';
import { Building2, Check, ChevronsUpDown } from 'lucide-react';
import { Badge } from '../ui/Badge';

export function OrganizationSwitcher() {
  const { activeOrg, organizations, switchOrg, isLoading } = useAuth();
  const { t } = useI18n();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelectOrg = async (bopOrgId: string) => {
    if (bopOrgId === activeOrg?.bop_organization_id) {
      setIsOpen(false);
      return;
    }
    setIsOpen(false);
    await switchOrg(bopOrgId);
  };

  return (
    <div className="relative w-full" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={isLoading || organizations.length <= 1}
        className="flex items-center justify-between w-full p-2 rounded-lg border border-border bg-surface-subtle/50 hover:bg-surface-subtle text-left transition-colors focus:outline-none focus:ring-2 focus:ring-brand-dark"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-7 h-7 rounded-md bg-brand-dark/5 border border-border flex items-center justify-center shrink-0">
            <Building2 className="w-4 h-4 text-brand-gold" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-foreground truncate">
              {activeOrg?.name || t('nav.select_organization')}
            </p>
            <p className="text-[11px] text-foreground-muted truncate">
              {activeOrg?.slug || 'tenant'}
            </p>
          </div>
        </div>
        {organizations.length > 1 && (
          <ChevronsUpDown className="w-4 h-4 text-foreground-muted shrink-0 ml-1" />
        )}
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1.5 w-full z-40 rounded-lg border border-border bg-surface p-1 shadow-lg animate-in fade-in zoom-in-95">
          <div className="px-2 py-1 text-[11px] font-semibold text-foreground-muted uppercase tracking-wider">
            {t('nav.switch_organization')}
          </div>
          <div className="mt-1 space-y-0.5 max-h-56 overflow-y-auto">
            {organizations.map((org) => {
              const isSelected = org.bop_organization_id === activeOrg?.bop_organization_id;
              return (
                <button
                  key={org.bop_organization_id}
                  onClick={() => handleSelectOrg(org.bop_organization_id)}
                  className={`flex items-center justify-between w-full px-2.5 py-2 text-xs rounded-md transition-colors text-left ${
                    isSelected
                      ? 'bg-surface-subtle font-medium text-foreground'
                      : 'hover:bg-surface-subtle/80 text-foreground-muted hover:text-foreground'
                  }`}
                >
                  <div className="min-w-0 flex-1 mr-2">
                    <p className="truncate text-xs text-foreground">{org.name}</p>
                    <p className="text-[10px] text-foreground-muted truncate">{org.bop_organization_id}</p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Badge size="sm" variant="outline">
                      {org.role}
                    </Badge>
                    {isSelected && <Check className="w-3.5 h-3.5 text-brand-gold" />}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
