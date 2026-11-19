import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

const { outputFiles } = await build({
  entryPoints: [new URL('../src/sonic-map.ts', import.meta.url).pathname],
  bundle: true,
  format: 'esm',
  write: false,
});
const { sonicLabels } = await import(
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
