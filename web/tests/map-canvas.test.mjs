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
  const first = create(genres, 'islands');
  assert.ok(measured > 0);
  const initialMeasurements = measured;
  first.selection('jazz');
  first.destroy();
  const camera = { x: 10, y: 20, scale: 2 };
  const second = create(genres, 'islands', camera);
  assert.equal(measured, initialMeasurements);
  assert.equal(second.items, first.items);
  assert.equal(second.points, first.points);
  assert.deepEqual(second.camera, camera);
  second.camera.x++;
  assert.equal(camera.x, 10);
  assert.equal(second.selected, '');
  second.destroy();
  create(genres, 'islands').destroy();
  assert.equal(measured, initialMeasurements);
  create(structuredClone(genres), 'islands').destroy();
  assert.ok(measured > initialMeasurements);
});

test('zoom is bounded and points remain visible when labels collide or share a base name', (t) => {
  globalThis.window = { devicePixelRatio: 1 };
  globalThis.document = {};
  globalThis.requestAnimationFrame = () => 1;
  globalThis.cancelAnimationFrame = () => {};
  let resize;
  globalThis.ResizeObserver = class {
    constructor(callback) {
      resize = callback;
    }
    observe() {}
    disconnect() {}
  };
  t.after(() => {
    delete globalThis.window;
    delete globalThis.document;
    delete globalThis.requestAnimationFrame;
    delete globalThis.cancelAnimationFrame;
    delete globalThis.ResizeObserver;
  });
  let dots = 0;
  let text = [];
  const context = {
    measureText: (label) => ({ width: label.length * 8 }),
    setTransform() {},
    clearRect() {},
    beginPath() {},
    fill() {},
    strokeText() {},
    arc() {
      dots++;
    },
    fillText(label) {
      text.push(label);
    },
  };
  const canvas = Object.assign(new EventTarget(), {
    clientWidth: 1000,
    clientHeight: 570,
    getContext: () => context,
  });
  const data = ['rock', 'rock · A', 'rock · B', 'jazz', 'ROCK'].map((name, i) => ({
    id: String(i),
    name,
    parent_id: i === 1 || i === 2 ? '0' : null,
    member_count: 100 - i,
    positions: {
      islands: { x: [0.5, 0.4, 0.6, 0.5, 0.6][i], y: i === 4 ? 0.55 : 0.5 },
      axes: null,
    },
  }));
  const status = {};
  const map = new MapCanvas(canvas, data, 'islands', () => {}, status);
  assert.equal(map.camera.scale / map.home.scale, 1);
  const initial = { ...map.camera };
  map.draw();
  assert.equal(dots, 3);
  assert.equal(map.labels.length, 1);
  assert.equal(
    status.textContent,
    '1 labels · 5 genres. Zoom for more; search genres and artists.',
  );
  assert.deepEqual(text, ['rock']);
  map.zoom(4);
  dots = 0;
  text = [];
  map.draw();
  assert.equal(dots, 5);
  assert.deepEqual(text, ['rock', 'rock · A', 'rock · B']);
  map.zoom(1000);
  assert.equal(map.camera.scale / map.home.scale, 256);
  const camera = { ...map.camera };
  map.zoom(84);
  assert.deepEqual(map.camera, camera);
  map.center(200, 300);
  map.reset();
  assert.deepEqual(map.camera, initial);
  map.zoom(1000);
  canvas.clientWidth /= 2;
  canvas.clientHeight /= 2;
  resize();
  assert.equal(map.camera.scale / map.home.scale, 256);
  map.zoom(0.0001);
  assert.equal(map.camera.scale / map.home.scale, 0.5);
  map.destroy();
  const restored = new MapCanvas(canvas, [], 'islands', () => {}, undefined, {
    x: 1,
    y: 1,
    scale: 1000,
  });
  assert.equal(restored.camera.scale / restored.home.scale, 256);
  dots = 0;
  restored.draw();
  assert.equal(dots, 0);
  restored.destroy();
});
