import { Role } from '@/lib/api/types';

export type Permission =
  | 'organization.read'
  | 'organization.manage'
  | 'organization.delete'
  | 'members.read'
  | 'members.manage'
  | 'campaign.read'
  | 'campaign.create'
  | 'campaign.update'
  | 'campaign.delete'
  | 'icp.read'
  | 'icp.manage'
  | 'target_market.read'
  | 'target_market.create'
  | 'target_market.manage'
  | 'prospect.read'
  | 'prospect.update'
  | 'signals.read'
  | 'research.run'
  | 'monitoring.read'
  | 'monitoring.manage'
  | 'integration.read'
  | 'integration.manage'
  | 'owner.transfer';

export const ROLE_PERMISSIONS: Record<Role, Permission[]> = {
  VIEWER: [
    'organization.read',
    'members.read',
    'campaign.read',
    'icp.read',
    'target_market.read',
    'prospect.read',
    'signals.read',
    'monitoring.read',
  ],
  MEMBER: [
    'organization.read',
    'members.read',
    'campaign.read',
    'campaign.create',
    'campaign.update',
    'icp.read',
    'icp.manage',
    'target_market.read',
    'target_market.create',
    'target_market.manage',
    'prospect.read',
    'prospect.update',
    'signals.read',
    'research.run',
    'monitoring.read',
    'monitoring.manage',
  ],
  ADMIN: [
    'organization.read',
    'organization.manage',
    'members.read',
    'members.manage',
    'campaign.read',
    'campaign.create',
    'campaign.update',
    'campaign.delete',
    'icp.read',
    'icp.manage',
    'target_market.read',
    'target_market.create',
    'target_market.manage',
    'prospect.read',
    'prospect.update',
    'signals.read',
    'research.run',
    'monitoring.read',
    'monitoring.manage',
    'integration.read',
    'integration.manage',
  ],
  OWNER: [
    'organization.read',
    'organization.manage',
    'organization.delete',
    'members.read',
    'members.manage',
    'campaign.read',
    'campaign.create',
    'campaign.update',
    'campaign.delete',
    'icp.read',
    'icp.manage',
    'target_market.read',
    'target_market.create',
    'target_market.manage',
    'prospect.read',
    'prospect.update',
    'signals.read',
    'research.run',
    'monitoring.read',
    'monitoring.manage',
    'integration.read',
    'integration.manage',
    'owner.transfer',
  ],
};

export function hasPermission(role: Role | null | undefined, permission: Permission): boolean {
  if (!role) return false;
  const permissions = ROLE_PERMISSIONS[role.toUpperCase() as Role];
  return permissions ? permissions.includes(permission) : false;
}
