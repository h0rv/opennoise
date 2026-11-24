import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

const { outputFiles } = await build({
  entryPoints: [new URL('../src/sonic-map.ts', import.meta.url).pathname],
  bundle: true,
  format: 'esm',
  write: false,
});
const { SonicMap, sonicLabels } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}`
);
const genre = (id, name, count, x, y) => ({
  id,
  name,
  member_count: count,
  parent_id: null,
  positions: { axes: { x, y }, islands: null },
});
const measure = (text) => text.length * 8;

test('Map uses native scrolling without camera controls and keeps genre clicks and search reveal', (t) => {
  const listeners = new Map();
  const nodes = [];
  const scrolls = [];
  const opened = [];
  let resize;
  const create = () => {
    const node = {
      style: {},
      dataset: {},
      children: [],
      clientWidth: 800,
      attributes: {},
      classList: {
        values: new Set(),
        toggle(name, enabled) {
          if (enabled) this.values.add(name);
          else this.values.delete(name);
        },
        contains(name) {
          return this.values.has(name);
        },
      },
      append(child) {
        this.children.push(child);
      },
      replaceChildren(fragment) {
        this.children = fragment.children;
      },
      setAttribute(key, value) {
        this.attributes[key] = value;
      },
      addEventListener(type, callback) {
        listeners.set(type, callback);
      },
      getContext: () => ({ measureText: (text) => ({ width: measure(text) }) }),
      getBoundingClientRect: () => ({ top: 2000, bottom: 2020 }),
      scrollIntoView(options) {
        scrolls.push([node.dataset.id, options]);
      },
      remove() {},
      closest() {
        return this;
      },
    };
    nodes.push(node);
    return node;
  };
  globalThis.document = { createElement: create, createDocumentFragment: create };
  globalThis.window = {
    innerHeight: 600,
    scrollTo: (...args) => scrolls.push(args),
  };
  globalThis.ResizeObserver = class {
    constructor(callback) {
      resize = callback;
    }
    observe() {}
    disconnect() {}
  };
  t.after(() => {
    delete globalThis.document;
    delete globalThis.window;
    delete globalThis.ResizeObserver;
  });
  const element = create();
  const map = new SonicMap(
    element,
    [genre('pop', 'pop', 100, 0.5, 0.8), genre('rock', 'rock', 100, 0.2, 0.2)],
    (...args) => opened.push(args),
    250,
  );
  assert.deepEqual([...listeners.keys()], ['click']);
  assert.equal(element.children.length, 1);
  assert.equal(element.children[0].style.transform, undefined);
  assert.deepEqual(scrolls, [[0, 250]]);
  const button = nodes.find((node) => node.dataset.id === 'pop');
  listeners.get('click')({ target: button });
  assert.deepEqual(opened, [['genre', 'pop']]);
  map.selection('pop', true);
  assert.equal(button.attributes['aria-pressed'], 'true');
  assert.deepEqual(scrolls.at(-1), ['pop', { block: 'center', inline: 'nearest' }]);
  map.selection('missing', true);
  assert.equal(button.attributes['aria-pressed'], 'false');
  map.highlight(['pop', 'unknown']);
  assert(element.classList.contains('artist-highlight'));
  assert(button.classList.contains('artist-genre'));
  const rock = nodes.find((node) => node.dataset.id === 'rock');
  assert(!rock.classList.contains('artist-genre'));
  rock.getBoundingClientRect = () => ({ top: 510, bottom: 530 });
  map.highlight(['pop', 'rock'], true, 500);
  assert.deepEqual(scrolls.at(-1), ['rock', { block: 'center', inline: 'nearest' }]);
  const scrolled = scrolls.length;
  map.highlight(['pop', 'rock'], true);
  assert.equal(scrolls.length, scrolled);
  element.clientWidth = 900;
  resize();
  const resized = element.children[0].children.find((node) => node.dataset.id === 'pop');
  assert(resized.classList.contains('artist-genre'));
  map.highlight(['rock']);
  assert(!resized.classList.contains('artist-genre'));
  map.highlight([]);
  assert(!element.classList.contains('artist-highlight'));
  assert(element.children[0].children.every((node) => !node.classList.contains('artist-genre')));
  map.highlight(['unknown']);
  assert(!element.classList.contains('artist-highlight'));
  assert(element.children[0].children.every((node) => !node.classList.contains('artist-genre')));
  map.highlight([]);
  map.destroy();
  const empty = new SonicMap(create(), [], () => {});
  empty.selection('missing', true);
  empty.highlight([]);
  assert(!empty.element?.classList.contains('artist-highlight'));
  empty.destroy();
});

test('sonic labels exclude artist clusters and unplaced genres, deduplicate names, and size by membership', () => {
  const data = [
    genre('pop', 'pop', 10000, 0.5, 0.5),
    genre('small', 'small', 5, 0.2, 0.7),
    genre('child', 'pop · Björk', 5000, 0.4, 0.3),
    genre('duplicate', 'POP', 50, 0.9, 0.1),
    { ...genre('unplaced', 'unplaced', 50, 0, 0), positions: { axes: null, islands: null } },
  ];
  const scene = sonicLabels(data, 1400, measure);
  assert.deepEqual(
    scene.labels.map((l) => l.id),
    ['pop', 'small'],
  );
  assert(scene.labels[0].size > scene.labels[1].size);
  assert.notEqual(scene.labels[0].color, scene.labels[1].color);
  assert(scene.height >= 1800);
});

test('crowded labels find padded space rather than overlapping, in deterministic priority order', () => {
  const data = Array.from({ length: 30 }, (_, i) =>
    genre(`g-${i}`, `genre ${i}`, 30 - i, 0.5, 0.5),
  );
  const { labels } = sonicLabels(data, 1000, measure);
  assert.equal(labels.length, data.length);
  assert.equal(labels[0].id, 'g-0');
  for (let i = 0; i < labels.length; i++)
    for (const b of labels.slice(i + 1)) {
      const a = labels[i];
      assert(
        a.x + a.width + 12 <= b.x ||
          b.x + b.width + 12 <= a.x ||
          a.y + a.size * 1.25 + 8 <= b.y ||
          b.y + b.size * 1.25 + 8 <= a.y,
      );
    }
  assert.deepEqual(
    sonicLabels([...data].reverse(), 1000, measure),
    sonicLabels(data, 1000, measure),
  );
});

test('more labels get a taller page; edge labels stay in bounds, and empty/narrow layouts are valid', () => {
  const data = Array.from({ length: 10000 }, (_, i) =>
    genre(`g-${i}`, `genre ${i}`, 100, (i % 10) / 9, Math.floor(i / 10) / 999),
  );
  const { labels, height } = sonicLabels(data, 1400, measure);
  assert(height > 10000);
  assert(labels.length > 9000);
  for (const item of labels) {
    assert(item.x >= 8 && item.x + item.width <= 1392);
    assert(item.y >= 8 && item.y + item.size * 1.25 <= height - 8);
  }
  assert.deepEqual(sonicLabels([], 1400, measure), { labels: [], height: 1800 });
  assert.equal(sonicLabels(data, 20, measure).labels.length, 0);
  assert.throws(() => sonicLabels([genre('bad', 'bad', 1, NaN, 0)], 1000, measure), RangeError);
});
