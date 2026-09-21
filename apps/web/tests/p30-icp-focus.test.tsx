import React, { useState } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import * as ReactDOMClient from 'react-dom/client';

// @ts-ignore
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
import { Modal } from '../components/ui/Modal';
import ICPsPage from '../app/[locale]/(app)/icps/page';
import { I18nProvider } from '../lib/i18n/context';
import { AuthProvider } from '../lib/auth/context';

// Mock Next.js navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/en/icps',
  useSearchParams: () => new URLSearchParams(),
}));

const mockSession = {
  user: {
    id: 'user-1',
    email: 'admin@bopagencia.local',
    full_name: 'Admin Bop Agencia',
    locale: 'en',
    is_active: true,
    is_superuser: false,
    created_at: '2026-09-01T00:00:00Z',
  },
  active_organization: {
    id: 'org-1',
    bop_organization_id: 'bop-org-1',
    name: 'Bop Agencia',
    slug: 'bop-agencia',
    role: 'ADMIN',
  },
  active_role: 'ADMIN',
  organizations: [],
};

function setInputValue(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype = el instanceof HTMLInputElement ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype;
  const nativeSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
  if (nativeSetter) {
    nativeSetter.call(el, value);
  } else {
    el.value = value;
  }
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

describe('P30.4 ICP Form Input Focus Regression Suite', () => {
  let container: HTMLDivElement;
  let root: ReactDOMClient.Root;

  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0 }),
    });

    container = document.createElement('div');
    document.body.appendChild(container);
    root = ReactDOMClient.createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('Modal does not steal focus when parent re-renders with changing onClose callback', () => {
    function ParentComponent() {
      const [isOpen, setIsOpen] = useState(true);
      const [text, setText] = useState('');

      return (
        <Modal
          isOpen={isOpen}
          onClose={() => setIsOpen(false)} // Unstable inline arrow function
          title="Focus Test Modal"
        >
          <input
            data-testid="test-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </Modal>
      );
    }

    act(() => {
      root.render(<ParentComponent />);
    });

    const input = container.querySelector('input[data-testid="test-input"]') as HTMLInputElement;
    expect(input).not.toBeNull();

    // Focus input
    act(() => {
      input.focus();
    });
    expect(document.activeElement).toBe(input);

    // Type character 1
    act(() => {
      setInputValue(input, 'A');
    });
    // Focus MUST remain on input, NOT jump to modal dialog
    expect(document.activeElement).toBe(input);

    // Type character 2
    act(() => {
      setInputValue(input, 'As');
    });
    expect(document.activeElement).toBe(input);

    // Type character 3
    act(() => {
      setInputValue(input, 'Aso');
    });
    expect(document.activeElement).toBe(input);
  });

  it('ICPsPage retains focus continuously when typing into Profile Name and Description', async () => {
    await act(async () => {
      root.render(
        <I18nProvider locale="en">
          <AuthProvider initialSession={mockSession as any}>
            <ICPsPage />
          </AuthProvider>
        </I18nProvider>
      );
    });

    // Open modal
    const createBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.includes('Create')
    );
    expect(createBtn).toBeDefined();

    act(() => {
      createBtn!.click();
    });

    // Locate Name input and Description textarea
    const nameInput = container.querySelector('input[required]') as HTMLInputElement;
    const descTextarea = container.querySelector('textarea') as HTMLTextAreaElement;
    expect(nameInput).not.toBeNull();
    expect(descTextarea).not.toBeNull();

    // Focus name input
    act(() => {
      nameInput.focus();
    });
    expect(document.activeElement).toBe(nameInput);

    // Type continuous string into Name input
    const testName = 'Asociaciones';
    for (let i = 1; i <= testName.length; i++) {
      act(() => {
        setInputValue(nameInput, testName.slice(0, i));
      });
      // Verify focus is strictly retained on every single keystroke
      expect(document.activeElement).toBe(nameInput);
    }
    expect(nameInput.value).toBe('Asociaciones');

    // Focus description textarea
    act(() => {
      descTextarea.focus();
    });
    expect(document.activeElement).toBe(descTextarea);

    // Type continuous string into Description
    const testDesc = 'Asociaciones y organizaciones profesionales';
    for (let i = 1; i <= testDesc.length; i++) {
      act(() => {
        setInputValue(descTextarea, testDesc.slice(0, i));
      });
      expect(document.activeElement).toBe(descTextarea);
    }
    expect(descTextarea.value).toBe(testDesc);

    // Test modal cancel closes dialog
    const cancelBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.includes('Cancel')
    );
    expect(cancelBtn).toBeDefined();
    act(() => {
      cancelBtn!.click();
    });

    expect(container.querySelector('div[role="dialog"]')).toBeNull();

    // Test reopening resets form
    act(() => {
      createBtn!.click();
    });
    const reopenedInput = container.querySelector('input[required]') as HTMLInputElement;
    expect(reopenedInput).not.toBeNull();
    expect(reopenedInput.value).toBe('');
  });
});
