import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

const { outputFiles } = await build({
  entryPoints: [new URL('../src/artist-graph.ts', import.meta.url).pathname],
  bundle: true,
  format: 'esm',
  write: false,
});
const { artistNeighbors, layoutArtists } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}`
);

test('less familiar reranks neighbors without changing published scores', () => {
  const data = {
    artist: { id: 'root' },
    similar: [
      { artist: { id: 'popular', listeners: 10000 }, score: 1 },
      { artist: { id: 'rare', listeners: null }, score: 0.9 },
    ],
  };
  assert.deepEqual(
    artistNeighbors(data, true).map((m) => m.artist.id),
    ['rare', 'popular'],
  );
  assert.equal(data.similar[0].artist.id, 'popular');
  assert.deepEqual(artistNeighbors({ artist: { id: 'root' }, similar: [] }, true), []);
});

test('deduplicates neighbors and excludes self without changing rank', () => {
  const artist = (id) => ({ id, name: id });
  assert.deepEqual(
    artistNeighbors({
      artist: artist('a'),
      similar: ['a', 'b', 'b', 'c'].map((id) => ({ artist: artist(id), score: 0.5 })),
    }).map(({ artist }) => artist.id),
    ['b', 'c'],
  );
  assert.deepEqual(artistNeighbors({ artist: artist('a'), similar: null }), []);
});

test('higher similarity stays closer to the center deterministically', () => {
  const nodes = Array.from({ length: 4 }, () => ({ width: 60, height: 24 }));
  const edges = [1, 0.5, 0].map((score, i) => ({ a: 0, b: i + 1, score }));
  const points = layoutArtists(nodes, edges, 1000, 800);
  const distances = points.slice(1).map(({ x, y }) => Math.hypot(x - points[0].x, y - points[0].y));
  assert.ok(distances[0] < distances[1]);
  assert.ok(distances[1] < distances[2]);
  assert.deepEqual(points, layoutArtists(nodes, edges, 1000, 800));
});

test('handles empty graphs, missing edges and out-of-range scores', () => {
  assert.deepEqual(layoutArtists([], [], 400, 500), []);
  assert.deepEqual(layoutArtists([{ width: 80, height: 24 }], [], 400, 500), [{ x: 200, y: 250 }]);
  const nodes = Array.from({ length: 3 }, () => ({ width: 60, height: 24 }));
  for (const points of [
    layoutArtists(nodes, [], 390, 600),
    layoutArtists(
      nodes,
      [
        { a: 0, b: 1, score: -5 },
        { a: 0, b: 2, score: 10 },
      ],
      390,
      600,
    ),
  ]) {
    for (const { x, y } of points)
      assert.ok(
        Number.isFinite(x) && Number.isFinite(y) && x >= 42 && x <= 348 && y >= 24 && y <= 576,
      );
  }
});
