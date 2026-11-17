import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { build } from 'esbuild';

const { outputFiles } = await build({
  entryPoints: [new URL('../src/map-canvas.ts', import.meta.url).pathname],
  bundle: true,
  format: 'esm',
  write: false,
});
const { MapCanvas } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}`
);
const genres = JSON.parse(
  await readFile(new URL('../../tests/fixtures/catalog/genres.json', import.meta.url), 'utf8'),
);

test('returning to a map reuses its scene without sharing camera or selection state', (t) => {
  globalThis.window = { devicePixelRatio: 1 };
  globalThis.requestAnimationFrame = () => 1;
  globalThis.cancelAnimationFrame = () => {};
  globalThis.ResizeObserver = class {
    observe() {}
    disconnect() {}
  };
  t.after(() => {
    delete globalThis.window;
    delete globalThis.requestAnimationFrame;
    delete globalThis.cancelAnimationFrame;
    delete globalThis.ResizeObserver;
  });
  let measured = 0;
  const create = (data, layout, camera) =>
    new MapCanvas(
      Object.assign(new EventTarget(), {
        clientWidth: 800,
        clientHeight: 500,
        getContext: () => ({ measureText: () => (++measured, { width: 60 }) }),
      }),
      data,
      layout,
      () => {},
      {},
      camera,
    );
  const first = create(genres, 'axes');
  assert.ok(measured > 0);
  const initialMeasurements = measured;
  first.selection('jazz');
  first.destroy();
  const camera = { x: 10, y: 20, scale: 2 };
  const second = create(genres, 'axes', camera);
  assert.equal(measured, initialMeasurements);
  assert.equal(second.items, first.items);
  assert.equal(second.points, first.points);
  assert.deepEqual(second.camera, camera);
  second.camera.x++;
  assert.equal(camera.x, 10);
  assert.equal(second.selected, '');
  second.destroy();
  create(genres, 'islands').destroy();
  assert.ok(measured > initialMeasurements);
  const bothLayouts = measured;
  create(genres, 'islands').destroy();
  assert.equal(measured, bothLayouts);
  create(structuredClone(genres), 'axes').destroy();
  assert.ok(measured > bothLayouts);
});
