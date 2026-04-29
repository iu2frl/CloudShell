import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Login } from '../pages/Login';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    login: vi.fn().mockResolvedValue(undefined),
  };
});

describe('Login', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        json: async () => ({ version: 'test' }),
      }),
    );
  });

  it('submits when Enter is pressed in password field', async () => {
    const onLogin = vi.fn();
    const { login } = await import('../api/client');

    render(<Login onLogin={onLogin} />);

    await userEvent.type(screen.getByPlaceholderText('admin'), 'admin');
    await userEvent.type(screen.getByPlaceholderText('••••••••'), 'secret{Enter}');

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith('admin', 'secret', undefined, false);
      expect(onLogin).toHaveBeenCalledOnce();
    });
  });
});
