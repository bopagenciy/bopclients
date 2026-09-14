'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useI18n } from '../../lib/i18n/context';
import { BrandLogo } from '../brand/BrandLogo';
import { OrganizationSwitcher } from './OrganizationSwitcher';
import {
  LayoutDashboard,
  Users,
  Megaphone,
  Target,
  Globe2,
  Compass,
  Activity,
  Boxes,
  Settings,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '../../lib/utils';

export function AppSidebar() {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const { locale, t } = useI18n();
  const pathname = usePathname();

  const navItems = [
    {
      label: t('nav.dashboard'),
      href: `/${locale}/dashboard`,
      icon: LayoutDashboard,
    },
    {
      label: t('nav.prospects'),
      href: `/${locale}/prospects`,
      icon: Users,
    },
    {
      label: t('nav.campaigns'),
      href: `/${locale}/campaigns`,
      icon: Megaphone,
    },
    {
      label: t('nav.icps'),
      href: `/${locale}/icps`,
      icon: Target,
    },
    {
      label: t('nav.target_markets'),
      href: `/${locale}/target-markets`,
      icon: Globe2,
    },
    {
      label: t('nav.research'),
      href: `/${locale}/research`,
      icon: Compass,
    },
    {
      label: t('nav.monitoring'),
      href: `/${locale}/monitoring`,
      icon: Activity,
    },
    {
      label: t('nav.integrations'),
      href: `/${locale}/integrations`,
      icon: Boxes,
    },
    {
      label: t('nav.settings'),
      href: `/${locale}/settings`,
      icon: Settings,
    },
  ];

  return (
    <aside
      className={cn(
        'relative flex flex-col h-screen border-r border-border bg-surface transition-all duration-300 z-30 select-none shrink-0',
        isCollapsed ? 'w-18' : 'w-64'
      )}
    >
      {/* Brand Header */}
      <div className="flex items-center justify-between h-16 px-4 border-b border-border/70">
        <BrandLogo collapsed={isCollapsed} locale={locale} />
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="hidden md:flex p-1.5 rounded-md text-foreground-muted hover:bg-surface-subtle hover:text-foreground transition-colors"
          aria-label={isCollapsed ? t('nav.expand_sidebar') : t('nav.collapse_sidebar')}
        >
          {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* Organization Switcher */}
      {!isCollapsed && (
        <div className="p-3 border-b border-border/70">
          <OrganizationSwitcher />
        </div>
      )}

      {/* Navigation List */}
      <nav className="flex-1 overflow-y-auto px-2.5 py-4 space-y-1">
        {navItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== `/${locale}/dashboard` && pathname.startsWith(item.href));
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              title={isCollapsed ? item.label : undefined}
              className={cn(
                'group flex items-center gap-3 px-3 py-2 rounded-md text-xs font-medium transition-all relative',
                isActive
                  ? 'bg-brand-dark text-white shadow-xs font-semibold'
                  : 'text-foreground-muted hover:bg-surface-subtle hover:text-foreground'
              )}
            >
              {isActive && (
                <div className="absolute left-0 top-1.5 bottom-1.5 w-1 bg-brand-gold rounded-r-full" />
              )}
              <Icon
                className={cn(
                  'w-4 h-4 shrink-0 transition-colors',
                  isActive ? 'text-brand-gold' : 'text-foreground-muted group-hover:text-foreground'
                )}
              />
              {!isCollapsed && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Footer Info */}
      {!isCollapsed && (
        <div className="p-3 border-t border-border/70 text-[11px] text-foreground-muted">
          <div className="flex items-center justify-between">
            <span className="font-mono">v1.0.0 (P20)</span>
            <span className="inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span>Online</span>
            </span>
          </div>
        </div>
      )}
    </aside>
  );
}
