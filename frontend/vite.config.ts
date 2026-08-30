import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'vite.svg'],
      manifest: {
        name: 'CloudShell',
        short_name: 'CloudShell',
        description: 'Self-hosted web SSH, SFTP and FTP(S) gateway.',
        theme_color: '#0f172a',
        background_color: '#0f172a',
        display: 'standalone',
        start_url: '/',
        icons: [
          {
            src: '/favicon.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'any',
          },
          {
            src: '/favicon.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
      },
    }),
  ],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    reporters: ['default', ['junit', { outputFile: 'reports/junit.xml' }]],
    coverage: {
      provider: 'istanbul',
      reporter: ['text', 'html', 'lcov'],
      include: [
        'src/components/splitview/**',
        'src/components/ErrorBoundary.tsx',
        'src/components/Toast.tsx',
        'src/components/DeviceList.tsx',
        'src/components/DeviceListWithFolders.tsx',
        'src/components/DeviceRow.tsx',
        'src/components/DeviceForm.tsx',
        'src/components/FolderModal.tsx',
        'src/components/FolderTreeItem.tsx',
        'src/components/FtpFileManager.tsx',
        'src/api/client.ts',
      ],
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
    rollupOptions: {
      output: {
        manualChunks: (id: string) => {
          if (id.includes('@xterm/xterm') || id.includes('@xterm/addon-fit') || id.includes('@xterm/addon-web-links')) {
            return 'xterm';
          }
          if (id.includes('react') || id.includes('react-dom')) {
            return 'react';
          }
        },
      },
    },
  },
})
