import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { renderToString } from 'react-dom/server';
import { PermissionGate } from '../components/navigation/PermissionGate';
import * as AuthContext from '../lib/auth/context';

describe('PermissionGate Component', () => {
  it('renders children when user role is allowed', () => {
    vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
      user: { id: '1', email: 'admin@bop.com', is_active: true, is_superuser: false, created_at: '' },
      activeOrg: null,
      activeRole: 'ADMIN',
      organizations: [],
      isLoading: false,
      isAuthenticated: true,
      login: vi.fn(),
      logout: vi.fn(),
      switchOrg: vi.fn(),
      hasRole: (roles) => roles.includes('ADMIN'),
      refreshSession: vi.fn(),
    });

    const html = renderToString(
      <PermissionGate allowedRoles={['OWNER', 'ADMIN']} fallback={<div>Restricted</div>}>
        <div>Admin Exclusive Action</div>
      </PermissionGate>
    );

    expect(html).toContain('Admin Exclusive Action');
    expect(html).not.toContain('Restricted');
  });

  it('renders fallback when user role is not allowed', () => {
    vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
      user: { id: '1', email: 'viewer@bop.com', is_active: true, is_superuser: false, created_at: '' },
      activeOrg: null,
      activeRole: 'VIEWER',
      organizations: [],
      isLoading: false,
      isAuthenticated: true,
      login: vi.fn(),
      logout: vi.fn(),
      switchOrg: vi.fn(),
      hasRole: (roles) => roles.includes('VIEWER'),
      refreshSession: vi.fn(),
    });

    const html = renderToString(
      <PermissionGate allowedRoles={['OWNER', 'ADMIN']} fallback={<div>Access Restricted</div>}>
        <div>Admin Exclusive Action</div>
      </PermissionGate>
    );

    expect(html).toContain('Access Restricted');
    expect(html).not.toContain('Admin Exclusive Action');
  });
});
