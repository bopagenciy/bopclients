'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { User, Organization, Role, SessionContext } from '../api/types';
import { useRouter } from 'next/navigation';

interface AuthContextType {
  user: User | null;
  activeOrg: Organization | null;
  activeRole: Role | null;
  organizations: Organization[];
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (credentials: { email: string; password: string }) => Promise<void>;
  logout: () => Promise<void>;
  switchOrg: (bopOrganizationId: string) => Promise<void>;
  hasRole: (allowedRoles: Role[]) => boolean;
  refreshSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const ROLE_HIERARCHY: Record<Role, number> = {
  OWNER: 4,
  ADMIN: 3,
  MEMBER: 2,
  VIEWER: 1,
};

export function AuthProvider({
  children,
  initialSession,
}: {
  children: React.ReactNode;
  initialSession?: SessionContext | null;
}) {
  const [user, setUser] = useState<User | null>(initialSession?.user || null);
  const [activeOrg, setActiveOrg] = useState<Organization | null>(
    initialSession?.active_organization || null
  );
  const [activeRole, setActiveRole] = useState<Role | null>(
    initialSession?.active_role || null
  );
  const [organizations, setOrganizations] = useState<Organization[]>(
    initialSession?.organizations || []
  );
  const [isLoading, setIsLoading] = useState<boolean>(!initialSession);
  const router = useRouter();

  const refreshSession = useCallback(async () => {
    try {
      const res = await fetch('/api/auth/session', {
        credentials: 'include',
        cache: 'no-store',
      });
      if (res.ok) {
        const data: SessionContext = await res.json();
        setUser(data.user);
        setActiveOrg(data.active_organization);
        setActiveRole(data.active_role);
        setOrganizations(data.organizations || []);
      } else {
        setUser(null);
        setActiveOrg(null);
        setActiveRole(null);
        setOrganizations([]);
      }
    } catch {
      setUser(null);
      setActiveOrg(null);
      setActiveRole(null);
      setOrganizations([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!initialSession) {
      refreshSession();
    }
  }, [initialSession, refreshSession]);

  const login = async (credentials: { email: string; password: string }) => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(credentials),
        credentials: 'include',
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Authentication failed' }));
        throw new Error(err.detail || 'Authentication failed');
      }

      const data = await res.json();
      setUser(data.user);
      setActiveOrg(data.active_organization);
      setActiveRole(data.active_organization?.role || 'MEMBER');
      setOrganizations(data.organizations || []);
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    setIsLoading(true);
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'include',
      });
    } finally {
      setUser(null);
      setActiveOrg(null);
      setActiveRole(null);
      setOrganizations([]);
      setIsLoading(false);
      const isEs = window.location.pathname.startsWith('/es');
      router.push(isEs ? '/es/login' : '/en/login');
    }
  };

  const switchOrg = async (bopOrganizationId: string) => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/auth/switch-org', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bop_organization_id: bopOrganizationId }),
        credentials: 'include',
      });

      if (!res.ok) {
        throw new Error('Failed to switch organization');
      }

      await refreshSession();
      router.refresh();
    } finally {
      setIsLoading(false);
    }
  };

  const hasRole = (allowedRoles: Role[]): boolean => {
    if (!activeRole) return false;
    return allowedRoles.includes(activeRole);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        activeOrg,
        activeRole,
        organizations,
        isLoading,
        isAuthenticated: !!user,
        login,
        logout,
        switchOrg,
        hasRole,
        refreshSession,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
