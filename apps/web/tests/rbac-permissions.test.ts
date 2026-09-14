import { describe, it, expect } from 'vitest';
import { hasPermission, ROLE_PERMISSIONS } from '../lib/permissions';

describe('Frontend RBAC Matching Backend P19 Policy', () => {
  it('allows MEMBER to execute standard operational actions (campaigns, ICPs, discovery)', () => {
    expect(hasPermission('MEMBER', 'campaign.create')).toBe(true);
    expect(hasPermission('MEMBER', 'campaign.update')).toBe(true);
    expect(hasPermission('MEMBER', 'icp.manage')).toBe(true);
    expect(hasPermission('MEMBER', 'target_market.create')).toBe(true);
    expect(hasPermission('MEMBER', 'target_market.manage')).toBe(true);
    expect(hasPermission('MEMBER', 'prospect.update')).toBe(true);
    expect(hasPermission('MEMBER', 'research.run')).toBe(true);
  });

  it('denies MEMBER from administrative tenant/member/integration management', () => {
    expect(hasPermission('MEMBER', 'members.manage')).toBe(false);
    expect(hasPermission('MEMBER', 'organization.manage')).toBe(false);
    expect(hasPermission('MEMBER', 'organization.delete')).toBe(false);
    expect(hasPermission('MEMBER', 'integration.manage')).toBe(false);
  });

  it('denies VIEWER from any mutations (read-only)', () => {
    // VIEWER read is allowed
    expect(hasPermission('VIEWER', 'campaign.read')).toBe(true);
    expect(hasPermission('VIEWER', 'prospect.read')).toBe(true);
    expect(hasPermission('VIEWER', 'icp.read')).toBe(true);

    // VIEWER mutations MUST be denied
    expect(hasPermission('VIEWER', 'campaign.create')).toBe(false);
    expect(hasPermission('VIEWER', 'campaign.update')).toBe(false);
    expect(hasPermission('VIEWER', 'campaign.delete')).toBe(false);
    expect(hasPermission('VIEWER', 'icp.manage')).toBe(false);
    expect(hasPermission('VIEWER', 'target_market.create')).toBe(false);
    expect(hasPermission('VIEWER', 'prospect.update')).toBe(false);
    expect(hasPermission('VIEWER', 'research.run')).toBe(false);
    expect(hasPermission('VIEWER', 'members.manage')).toBe(false);
    expect(hasPermission('VIEWER', 'integration.manage')).toBe(false);
  });

  it('grants ADMIN and OWNER administrative permissions', () => {
    expect(hasPermission('ADMIN', 'campaign.create')).toBe(true);
    expect(hasPermission('ADMIN', 'members.manage')).toBe(true);
    expect(hasPermission('ADMIN', 'integration.manage')).toBe(true);

    expect(hasPermission('OWNER', 'campaign.create')).toBe(true);
    expect(hasPermission('OWNER', 'members.manage')).toBe(true);
    expect(hasPermission('OWNER', 'organization.delete')).toBe(true);
    expect(hasPermission('OWNER', 'owner.transfer')).toBe(true);
  });
});
