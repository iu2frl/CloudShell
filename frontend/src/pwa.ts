export type RegisterSW = (options?: {
  immediate?: boolean;
  onNeedRefresh?: () => void;
  onOfflineReady?: () => void;
  onRegisterError?: (error: unknown) => void;
}) => unknown;

export const PWA_UPDATE_READY_EVENT = 'cloudshell:pwa-update-ready';

export interface PwaUpdateReadyDetail {
  applyUpdate: () => void;
}

export interface PwaInitOptions {
  isProd?: boolean;
  hasServiceWorker?: boolean;
}

/**
 * Registers the service worker only in production and only when the browser
 * supports service workers.
 */
export function initPwa(
  registerSW: RegisterSW,
  options: PwaInitOptions = {}
): boolean {
  const isProd = options.isProd ?? import.meta.env.PROD;
  const hasServiceWorker = options.hasServiceWorker ?? (
    typeof navigator !== 'undefined' && 'serviceWorker' in navigator
  );

  if (!isProd || !hasServiceWorker) {
    return false;
  }

  const updateSW = registerSW({
    immediate: true,
    onNeedRefresh: () => {
      window.dispatchEvent(new CustomEvent<PwaUpdateReadyDetail>(PWA_UPDATE_READY_EVENT, {
        detail: {
          applyUpdate: () => {
            if (typeof updateSW === 'function') {
              (updateSW as (reloadPage?: boolean) => Promise<void> | void)(true);
            } else {
              window.location.reload();
            }
          },
        },
      }));
    },
    onOfflineReady: () => {
      console.info('CloudShell is ready to work offline.');
    },
    onRegisterError: (error) => {
      console.error('CloudShell service worker registration failed.', error);
    },
  });

  return true;
}
