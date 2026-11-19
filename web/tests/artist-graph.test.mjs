import assert from 'node:assert/strict';
import test from 'node:test';
import { artistNeighbors, layoutArtists } from '../src/artist-graph.ts';

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
