import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      include: ['src/components/splitview/**'],
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    // In dev/local: output goes to backend/static for FastAPI to serve
    // In Docker: output goes to dist/ which the Dockerfile copies to backend/static
    outDir: process.env.DOCKER_BUILD ? 'dist' : '../backend/static',
    emptyOutDir: true,
  },
})
