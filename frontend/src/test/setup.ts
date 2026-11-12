/**
 * Vitest global setup — imported before every test file.
 * Extends expect() with @testing-library/jest-dom matchers.
 */
import '@testing-library/jest-dom/vitest';

/**
 * React (in development mode) re-throws component render errors through
 * a synthetic DOM event so the browser devtools can report them. In jsdom
 * this surfaces as noisy "Error: Uncaught [Error: ...]" lines on stderr for
 * every test that intentionally exercises an error boundary or a hook-outside-
 * provider guard.
 *
 * The errors are already asserted on by the tests themselves (via
 * `expect(...).toThrow(...)` or by checking the error-boundary fallback UI).
 * Suppressing them here keeps the test output clean without hiding any real
 * failures.
 */
window.addEventListener('error', (event) => {
  const msg = event.message ?? '';
  if (
    msg.includes('useToast must be used inside <ToastProvider>') ||
    msg.includes('Test render error')
  ) {
    event.preventDefault();
  }
});
