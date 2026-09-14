'use client';

import React from 'react';
import { Role } from '@/lib/api/types';
import { Permission, hasPermission } from '@/lib/permissions';
import { useAuth } from '@/lib/auth/context';

export interface PermissionGateProps {
  permission?: Permission;
  allowedRoles?: Role[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export function PermissionGate({
  permission,
  allowedRoles,
  children,
  fallback = null,
}: PermissionGateProps) {
  const { activeRole } = useAuth();

  let isAllowed = false;

  if (permission) {
    isAllowed = hasPermission(activeRole, permission);
  } else if (allowedRoles) {
    isAllowed = activeRole ? allowedRoles.includes(activeRole) : false;
  }

  if (!isAllowed) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
}
