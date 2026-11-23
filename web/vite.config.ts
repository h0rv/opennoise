import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const { CATALOG_SOURCE_COMMIT: commit } = loadEnv(mode, '.', 'CATALOG_SOURCE_COMMIT');
  const source =
    commit && /^[a-f0-9]{40}$/.test(commit)
      ? ` Source: <a href="https://github.com/h0rv/opennoise/tree/${commit}">commit ${commit.slice(0, 7)}</a>.`
      : '';

  return {
    publicDir: '../tests/fixtures',
    build: { rollupOptions: { input: ['index.html', 'about.html'] } },
    plugins: [
      {
        name: 'catalog-source',
        transformIndexHtml: (html) => html.replace('<span data-catalog-source></span>', source),
      },
    ],
  };
});
