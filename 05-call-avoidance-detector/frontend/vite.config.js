import { defineConfig } from 'vite';

export default defineConfig({
  build: { target: 'es2022', sourcemap: false },
  server: { proxy: { '/api': process.env.CALL_REVIEW_API || 'http://127.0.0.1:8505' } },
});
