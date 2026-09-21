import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'], display: 'swap' });

export const metadata: Metadata = {
  title: 'BopClients — Autonomous Prospecting Platform',
  description: 'Enterprise B2B prospecting, ICP discovery, signal enrichment, and lead qualification',
  applicationName: 'BopClients',
  icons: {
    icon: '/brand/bop-clients-icon.png',
    shortcut: '/favicon.ico',
    apple: '/brand/bop-clients-icon.png',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.className}>
      <body className="min-h-screen bg-background text-foreground antialiased selection:bg-brand-gold/20 selection:text-brand-dark">
        {children}
      </body>
    </html>
  );
}
