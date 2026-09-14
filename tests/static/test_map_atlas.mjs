import assert from 'node:assert/strict';
import test from 'node:test';
import {
  compareCodepoints,
  declutterLabels,
  fitCamera,
  focusCamera,
  appendCirclePath,
  levelForScale,
  normaliseAtlasPayload,
  visibleNodeLabels,
  zoomAt,
} from '../../src/opennoise/static/map-atlas.mjs';

const payload = {
  revision: 'semantic-scatter-map-v2',
  initial_camera: { x0: 0, y0: 0, x1: 16, y1: 9 },
  nodes: [
    { id: 'a', name: 'electronic', x: 2, y: 2, lod: 0, importance: 1 },
    { id: 'b', name: 'idm', x: 4, y: 3, lod: 1, importance: 1, display_parent_id: 'a' },
    { id: 'c', name: 'glitch', x: 5, y: 4, lod: 2, importance: 1, parent_id: 'b' },
    { id: 'd', name: 'micro', x: 6, y: 5, lod: 3, importance: 1, parent_id: 'c' },
  ],
  labels: [
    { level: 0, ids: ['a'] }, { level: 1, ids: ['a', 'b'] },
    { level: 2, ids: ['a', 'b', 'c'] }, { level: 3, ids: ['a', 'b', 'c', 'd'] },
  ],
  aliases: [{ term: 'intelligent dance music', target: 'b' }],
  overview_regions: [{ label: 'Electronic', x: 3, y: 3 }],
};

test('atlas retains monotonic zoom labels and optional region metadata', () => {
  const atlas = normaliseAtlasPayload(payload);
  assert.equal(atlas.regions[0].title, 'Electronic');
  assert.deepEqual(atlas.labels.map((labels) => labels.length), [1, 2, 3, 4]);
  assert.deepEqual(atlas.childrenByParent.get('b'), ['c']);
});

test('fit camera centers a landscape overview and zoom preserves its cursor world point', () => {
  const camera = fitCamera(payload.initial_camera, { width: 1600, height: 900 });
  assert.equal(camera.scale, 94);
  assert.equal(camera.x, 48);
  assert.equal(camera.y, 27);
  const before = { x: (800 - camera.x) / camera.scale, y: (450 - camera.y) / camera.scale };
  const zoomed = zoomAt(camera, { x: 800, y: 450 }, 2, { min: 1, max: 1000 });
  assert.deepEqual({ x: (800 - zoomed.x) / zoomed.scale, y: (450 - zoomed.y) / zoomed.scale }, before);
});

test('focused camera remains centered when its detail scale is clamped', () => {
  const camera = focusCamera(
    { x0: 4, y0: 2, x1: 5, y1: 3 },
    { width: 1000, height: 600 },
    900,
    1200,
  );
  assert.equal(camera.scale, 900);
  assert.equal((4.5 * camera.scale) + camera.x, 500);
  assert.equal((2.5 * camera.scale) + camera.y, 300);
  const anchored = focusCamera(
    { x0: 4, y0: 2, x1: 5, y1: 3 },
    { width: 1000, height: 600 },
    900,
    1200,
    0.72,
    { x: 4, y: 2 },
  );
  assert.equal((4 * anchored.scale) + anchored.x, 500);
  assert.equal((2 * anchored.scale) + anchored.y, 300);
});

test('batched circles are independent subpaths, never connected polygons', () => {
  const commands = [];
  const path = {
    moveTo: (...values) => commands.push(['moveTo', ...values]),
    arc: (...values) => commands.push(['arc', ...values]),
  };
  appendCirclePath(path, 10, 20, 3);
  appendCirclePath(path, 30, 40, 2);
  assert.deepEqual(commands.map(([name]) => name), ['moveTo', 'arc', 'moveTo', 'arc']);
  for (let index = 0; index < commands.length; index += 1) {
    if (commands[index][0] === 'arc') assert.equal(commands[index - 1][0], 'moveTo');
  }
});

test('zoom levels disclose labels monotonically without a focused node', () => {
  const levels = [1, 1.7, 3.5, 8].map((scale) => levelForScale(scale, 1));
  assert.deepEqual(levels, [0, 1, 2, 3]);
});

test('local zoom labels reveal nearby subgenres even when global label sets are sparse', () => {
  const sparse = normaliseAtlasPayload({
    ...payload,
    labels: [
      { level: 0, ids: ['a'] },
      { level: 1, ids: ['a'] },
      { level: 2, ids: ['a'] },
      { level: 3, ids: ['a'] },
    ],
  });
  const project = (node) => ({ x: node.x * 100, y: node.y * 100 });
  const textWidth = (name) => name.length * 7;
  const level1 = visibleNodeLabels(sparse, 1, { width: 1600, height: 900 }, project, textWidth, { maximum: 20 });
  const level2 = visibleNodeLabels(sparse, 2, { width: 1600, height: 900 }, project, textWidth, { maximum: 20 });
  assert.ok(level1.some((item) => item.id === 'b'), 'level one should reveal the nearby subgenre');
  assert.ok(level2.some((item) => item.id === 'c'), 'level two should reveal the deeper subgenre');
});

test('label decluttering is deterministic and keeps the higher-priority name', () => {
  const candidates = [
    { id: 'low', text: 'lower priority', screen: { x: 100, y: 100 }, priority: 20 },
    { id: 'high', text: 'higher priority', screen: { x: 100, y: 100 }, priority: 1 },
  ];
  const options = { maximum: 10, height: 16, padding: 3 };
  const once = declutterLabels(candidates, { width: 800, height: 500 }, (name) => name.length * 7, options);
  const twice = declutterLabels(candidates, { width: 800, height: 500 }, (name) => name.length * 7, options);
  assert.deepEqual(once.map((item) => item.id), ['high', 'low']);
  assert.deepEqual(twice.map((item) => item.id), ['high', 'low']);
  assert.ok(once[0].placement.box.x1 <= once[1].placement.box.x0
    || once[1].placement.box.x1 <= once[0].placement.box.x0
    || once[0].placement.box.y1 <= once[1].placement.box.y0
    || once[1].placement.box.y1 <= once[0].placement.box.y0);
});

test('required edge endpoints and nearest ancestors survive coincident label anchors', () => {
  const atlas = normaliseAtlasPayload({
    ...payload,
    nodes: payload.nodes.map((node) => ({ ...node, x: 3, y: 3 })),
    labels: [{ level: 0, ids: ['a'] }, { level: 1, ids: ['a'] }, { level: 2, ids: ['a'] }, { level: 3, ids: ['a'] }],
  });
  const project = (node) => ({ x: node.x * 100, y: node.y * 100 });
  const labels = visibleNodeLabels(
    atlas,
    1,
    { width: 1600, height: 900 },
    project,
    (name) => name.length * 7,
    { maximum: 20, requiredIds: ['b', 'c'], camera: { x: 0, y: 0, scale: 100 } },
  );
  const ids = new Set(labels.map((item) => item.id));
  assert.ok(ids.has('a'), 'the displayed parent should remain labelled');
  assert.ok(ids.has('b'), 'the focused edge endpoint should remain labelled');
  assert.ok(ids.has('c'), 'a deeper edge endpoint should remain labelled');
  for (let left = 0; left < labels.length; left += 1) {
    for (let right = left + 1; right < labels.length; right += 1) {
      const a = labels[left].placement.box;
      const b = labels[right].placement.box;
      assert.ok(a.x1 <= b.x0 || b.x1 <= a.x0 || a.y1 <= b.y0 || b.y1 <= a.y0);
    }
  }
});

test('label ordering is locale-independent', () => {
  assert.ok(compareCodepoints('z', 'ä') < 0);
  assert.ok(compareCodepoints('😀', 'z') > 0);
  assert.equal(compareCodepoints('same', 'same'), 0);
});

test('spatial index pre-budgets large atlas label candidates', () => {
  const nodes = Array.from({ length: 2945 }, (_, index) => ({
    id: `large-${index}`,
    name: `genre-${index}`,
    x: (index % 65) / 4,
    y: Math.floor(index / 65) / 4,
    lod: 3,
    importance: 1,
  }));
  const atlas = normaliseAtlasPayload({
    initial_camera: { x0: 0, y0: 0, x1: 16, y1: 12 },
    world_bounds: { x0: 0, y0: 0, x1: 16, y1: 12 },
    nodes,
    labels: [],
  });
  let projections = 0;
  const labels = visibleNodeLabels(
    atlas,
    3,
    { width: 1600, height: 1200 },
    (node) => { projections += 1; return { x: node.x * 100, y: node.y * 100 }; },
    (name) => name.length * 6,
    { maximum: 10, candidateLimit: 64, camera: { x: 0, y: 0, scale: 100 } },
  );
  assert.ok(labels.length <= 10);
  assert.ok(projections <= 64, `projected ${projections} nodes instead of the local candidate budget`);
});
