import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import config from '../vite.config.ts';

test('About names the build’s catalog source commit and omits it for fixture builds', async (t) => {
  const previous = process.env.CATALOG_SOURCE_COMMIT;
  t.after(() => {
    if (previous === undefined) delete process.env.CATALOG_SOURCE_COMMIT;
    else process.env.CATALOG_SOURCE_COMMIT = previous;
  });
  const html = await readFile(new URL('../about.html', import.meta.url), 'utf8');
  const render = () =>
    config({ command: 'build', mode: 'production' }).plugins[0].transformIndexHtml(html);

  const commit = 'abcdef0123456789abcdef0123456789abcdef01';
  process.env.CATALOG_SOURCE_COMMIT = commit;
  assert.ok(
    render().includes(
      `rebuild it. Source: <a href="https://github.com/h0rv/opennoise/tree/${commit}">commit abcdef0</a>.`,
    ),
  );

  delete process.env.CATALOG_SOURCE_COMMIT;
  assert.doesNotMatch(render(), /Source:|data-catalog-source/);
});
