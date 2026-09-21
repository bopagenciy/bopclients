'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useI18n } from '@/lib/i18n/context';

interface BrandLogoProps {
  className?: string;
  collapsed?: boolean;
  locale?: string;
  fallbackOnly?: boolean;
}

export function BrandLogo({
  className = '',
  collapsed = false,
  locale = 'en',
  fallbackOnly = false,
}: BrandLogoProps) {
  const { t } = useI18n();
  const [assetLoadFailed, setAssetLoadFailed] = useState(false);

  const homeLabel = t ? t('brand.home_label') : 'BopClients Home';

  const showImage = !fallbackOnly && !assetLoadFailed;

  return (
    <Link
      href={`/${locale}/dashboard`}
      className={`flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-gold rounded-md ${className}`}
      aria-label={homeLabel}
    >
      {showImage ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={collapsed ? '/brand/bop-clients-mark.png' : '/brand/bop-clients-wordmark.png'}
          alt="BopClients"
          className={collapsed ? 'h-7 w-auto object-contain shrink-0' : 'h-8 w-auto object-contain shrink-0'}
          onError={() => setAssetLoadFailed(true)}
        />
      ) : (
        /* Strict Typographic Fallback (NO fabricated icons or node artwork) */
        <div className="flex items-center tracking-tight select-none py-1">
          <span className="font-extrabold text-foreground tracking-wider font-sans text-lg">
            BOP
          </span>
          {!collapsed && (
            <>
              {/* Provisional Gold Separator (#C5A059) */}
              <span className="text-brand-gold mx-1.5 font-light text-xl">|</span>
              <span className="font-semibold text-foreground-muted tracking-widest text-sm uppercase">
                CLIENTS
              </span>
            </>
          )}
        </div>
      )}
    </Link>
  );
}
