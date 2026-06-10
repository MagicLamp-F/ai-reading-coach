import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': process.env.ARC_API_PROXY_TARGET || 'http://127.0.0.1:8000',
      '/feedback': process.env.ARC_FEEDBACK_PROXY_TARGET || 'http://127.0.0.1:8002',
    },
  },
});
