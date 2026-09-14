'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useI18n } from '@/lib/i18n/context';

interface BrandLogoProps {
  className?: string;
  collapsed?: boolean;
  locale?: string;
}

export function BrandLogo({ className = '', collapsed = false, locale = 'en' }: BrandLogoProps) {
  const { t } = useI18n();
  // By default, since official logo is not present in repo, fallback starts active.
  // If an official asset is dropped into /brand/bop-clients-logo.svg, it will attempt render.
  const [assetLoadFailed, setAssetLoadFailed] = useState(true);

  const homeLabel = t ? t('brand.home_label') : 'BopClients Home';

  return (
    <Link
      href={`/${locale}/dashboard`}
      className={`flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-gold rounded-md ${className}`}
      aria-label={homeLabel}
    >
      {!assetLoadFailed ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src="/brand/bop-clients-logo.svg"
          alt="BopClients"
          className="h-8 w-auto"
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
