export type RegisterSW = (options?: {
  immediate?: boolean;
  onOfflineReady?: () => void;
  onRegisterError?: (error: unknown) => void;
}) => unknown;

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

  registerSW({
    immediate: true,
    onOfflineReady: () => {
      console.info('CloudShell is ready to work offline.');
    },
    onRegisterError: (error) => {
      console.error('CloudShell service worker registration failed.', error);
    },
  });

  return true;
}
