import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import '../globals.css';
import { Locale, DEFAULT_LOCALE } from '@/lib/i18n/types';
import { isValidLocale } from '@/lib/i18n';
import { I18nProvider } from '@/lib/i18n/context';
import { AuthProvider } from '@/lib/auth/context';
import { ToastProvider } from '@/components/ui/Toast';
import { notFound } from 'next/navigation';
import { cookies } from 'next/headers';
import { SessionContext } from '@/lib/api/types';

const inter = Inter({ subsets: ['latin'], display: 'swap' });

export const metadata: Metadata = {
  title: {
    template: '%s | BopClients',
    default: 'BopClients — Autonomous Prospecting Platform',
  },
  description: 'Enterprise B2B prospecting, ICP discovery, signal enrichment, and lead qualification',
  applicationName: 'BopClients',
  icons: {
    icon: '/brand/bop-clients-icon.png',
    shortcut: '/favicon.ico',
    apple: '/brand/bop-clients-icon.png',
  },
};

export function generateStaticParams() {
  return [{ locale: 'en' }, { locale: 'es' }];
}

async function getInitialSession(): Promise<SessionContext | null> {
  const cookieStore = cookies();
  const accessToken = cookieStore.get('bop_access_token')?.value;
  const sessionToken = cookieStore.get('bop_session_token')?.value;

  if (!accessToken && !sessionToken) {
    return null;
  }

  const apiBase = process.env.BOPCLIENTS_API_URL || 'http://127.0.0.1:8100';
  try {
    const res = await fetch(`${apiBase}/api/v1/me`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
      cache: 'no-store',
    });

    if (res.ok) {
      const userData = await res.json();
      const activeOrgBopId = cookieStore.get('bop_active_org')?.value;
      const orgs = userData.organizations || [];
      let activeOrg = orgs.find((o: any) => o.bop_organization_id === activeOrgBopId);
      if (!activeOrg && orgs.length > 0) {
        activeOrg = orgs[0];
      }

      return {
        user: {
          id: userData.id,
          email: userData.email,
          full_name: userData.full_name || userData.name,
          locale: userData.locale,
          is_active: userData.is_active,
          is_superuser: userData.is_superuser,
          created_at: userData.created_at,
        },
        active_organization: activeOrg
          ? {
              id: activeOrg.id,
              bop_organization_id: activeOrg.bop_organization_id,
              name: activeOrg.name,
              slug: activeOrg.slug,
              role: activeOrg.role,
            }
          : null as any,
        active_role: activeOrg ? activeOrg.role : 'VIEWER',
        organizations: orgs,
      };
    }
  } catch {
    // Return null if backend is unreachable during initial load
  }

  return null;
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { locale: string };
}) {
  const locale = isValidLocale(params.locale) ? (params.locale as Locale) : DEFAULT_LOCALE;

  const initialSession = await getInitialSession();

  return (
    <I18nProvider locale={locale}>
      <AuthProvider initialSession={initialSession}>
        <ToastProvider>{children}</ToastProvider>
      </AuthProvider>
    </I18nProvider>
  );
}
