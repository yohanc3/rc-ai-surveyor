import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The Python dashboard serves the built output from frontend/dist, so `npm run
// build` is all that is needed to make `python3 run.py` serve this app. During
// development Vite serves the app and proxies the API to the Python process.
const BACKEND = process.env.RC_BACKEND ?? 'http://127.0.0.1:8787';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
