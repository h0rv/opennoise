import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

const { outputFiles } = await build({
  entryPoints: [new URL('../src/navigation.ts', import.meta.url).pathname],
  bundle: true,
  format: 'esm',
  write: false,
  plugins: [
    {
      name: 'mock-panzoom',
      setup(build) {
        build.onResolve({ filter: /^@panzoom\/panzoom$/ }, () => ({
          path: 'panzoom',
          namespace: 'mock',
        }));
        build.onLoad({ filter: /.*/, namespace: 'mock' }, () => ({
          contents: 'export default (...args) => globalThis.makePanzoom(...args)',
        }));
      },
    },
  ],
});
const { createNavigation } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}`
);

function setup(t, scale = 2) {
  const frames = new Map();
  let next = 0;
  t.mock.method(globalThis, 'requestAnimationFrame', (callback) => {
    frames.set(++next, callback);
    return next;
  });
  t.mock.method(globalThis, 'cancelAnimationFrame', (id) => frames.delete(id));
  const panzoom = {
    getScale: () => scale,
    pan: t.mock.fn(),
    zoomToPoint: t.mock.fn(),
    destroy: t.mock.fn(),
  };
  globalThis.makePanzoom = () => panzoom;
  t.after(() => delete globalThis.makePanzoom);
  const viewport = Object.assign(new EventTarget(), {
    clientWidth: 800,
    clientHeight: 600,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 800, bottom: 600 }),
  });
  const navigation = createNavigation(new EventTarget(), viewport, {
    camera: { x: 0, y: 0, scale },
    minScale: 0.2,
    maxScale: 4,
    excludeClass: 'tree-node',
    onReset() {},
  });
  panzoom.pan.mock.resetCalls();
  t.after(() => navigation.destroy());
  return {
    ...navigation,
    frames,
    wheel(values) {
      const event = Object.assign(new Event('wheel', { cancelable: true }), {
        deltaX: 0,
        deltaY: 0,
        deltaMode: 0,
        ...values,
      });
      viewport.dispatchEvent(event);
      return event.defaultPrevented;
    },
    flush() {
      const callbacks = [...frames.values()];
      frames.clear();
      callbacks.forEach((callback) => callback());
    },
  };
}

globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};

test('tree wheel batches scrolling in screen pixels without zooming', (t) => {
  const nav = setup(t);
  assert.equal(nav.wheel({ deltaY: 80 }), true);
  nav.wheel({ deltaX: 20, deltaY: 16 });
  assert.equal(nav.frames.size, 1);
  nav.flush();
  assert.deepEqual(nav.panzoom.pan.mock.calls[0].arguments, [-10, -48, { relative: true }]);
  nav.wheel({ deltaY: -32 });
  nav.flush();
  assert.deepEqual(nav.panzoom.pan.mock.calls[1].arguments, [-0, 16, { relative: true }]);
  assert.equal(nav.panzoom.zoomToPoint.mock.callCount(), 0);
});

test('tree handles line, page and shift-wheel scrolling at different zoom levels', (t) => {
  const nav = setup(t, 0.5);
  nav.wheel({ deltaX: 2, deltaY: 3, deltaMode: 1 });
  nav.flush();
  assert.deepEqual(nav.panzoom.pan.mock.calls[0].arguments, [-64, -96, { relative: true }]);
  nav.wheel({ deltaX: -1, deltaY: 1, deltaMode: 2 });
  nav.flush();
  assert.deepEqual(nav.panzoom.pan.mock.calls[1].arguments, [1600, -1200, { relative: true }]);
  nav.wheel({ deltaY: 50, shiftKey: true });
  nav.flush();
  assert.deepEqual(nav.panzoom.pan.mock.calls[2].arguments, [-100, -0, { relative: true }]);
});

test('browser wheel modifiers and explicit tree zoom remain available; destroy cancels work', (t) => {
  const nav = setup(t);
  for (const modifier of ['ctrlKey', 'metaKey', 'altKey']) {
    assert.equal(nav.wheel({ deltaY: 100, [modifier]: true }), false);
  }
  assert.equal(nav.frames.size, 0);
  nav.zoomBy(1.5);
  assert.deepEqual(nav.panzoom.zoomToPoint.mock.calls[0].arguments, [
    3,
    { clientX: 400, clientY: 300 },
    { animate: false },
  ]);
  nav.wheel({ deltaY: 100 });
  nav.destroy();
  assert.equal(nav.frames.size, 0);
  assert.equal(nav.wheel({ deltaY: 100 }), false);
  nav.flush();
  assert.equal(nav.panzoom.pan.mock.callCount(), 0);
});
