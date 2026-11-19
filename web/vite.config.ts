import { defineConfig } from 'vite';

export default defineConfig({
  publicDir: '../tests/fixtures',
  build: { rollupOptions: { input: ['index.html', 'about.html'] } },
});
