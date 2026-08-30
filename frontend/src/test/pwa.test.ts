import { describe, expect, it, vi } from 'vitest';
import { initPwa, type RegisterSW } from '../pwa';

describe('initPwa', () => {
  it('registers service worker in production when supported', () => {
    const registerSW = vi.fn<RegisterSW>();

    const enabled = initPwa(registerSW, {
      isProd: true,
      hasServiceWorker: true,
    });

    expect(enabled).toBe(true);
    expect(registerSW).toHaveBeenCalledTimes(1);
    expect(registerSW).toHaveBeenCalledWith(
      expect.objectContaining({
        immediate: true,
      })
    );
  });

  it('does not register service worker in development', () => {
    const registerSW = vi.fn<RegisterSW>();

    const enabled = initPwa(registerSW, {
      isProd: false,
      hasServiceWorker: true,
    });

    expect(enabled).toBe(false);
    expect(registerSW).not.toHaveBeenCalled();
  });

  it('does not register when service workers are not supported', () => {
    const registerSW = vi.fn<RegisterSW>();

    const enabled = initPwa(registerSW, {
      isProd: true,
      hasServiceWorker: false,
    });

    expect(enabled).toBe(false);
    expect(registerSW).not.toHaveBeenCalled();
  });
});
