import assert from 'node:assert/strict';
import test from 'node:test';
import {
  LabelGrid,
  baseName,
  claimName,
  labelBox,
  priority,
  visibleDepth,
} from '../src/label-grid.ts';

test('only the first priority instance claims a base name for this frame', () => {
  const names = new Set();
  assert.equal(baseName('shoegaze · Slowdive'), 'shoegaze');
  assert.equal(claimName('shoegaze · Slowdive', names), true);
  assert.equal(claimName('Shoegaze · Ride', names), false);
  assert.equal(claimName('drill', names), true);
  assert.equal(claimName('shoegaze', new Set()), true);
  assert.equal(baseName(''), '');
});

test('collision grid checks every intersecting cell, allowing touching boxes', () => {
  const grid = new LabelGrid(8);
  assert.equal(grid.place({ left: 1, top: 1, right: 30, bottom: 20 }), true);
  assert.equal(grid.place({ left: 29, top: 19, right: 70, bottom: 30 }), false);
  assert.equal(grid.place({ left: 30, top: 1, right: 40, bottom: 20 }), true);
  assert.equal(grid.place({ left: -20, top: -20, right: -10, bottom: -10 }), true);
});

test('invalid and nonfinite rectangles fail rather than hanging the grid', () => {
  for (const size of [0, -1, NaN, Infinity]) assert.throws(() => new LabelGrid(size), RangeError);
  for (const box of [
    { left: 0, top: 0, right: Infinity, bottom: 1 },
    { left: 1, top: 0, right: 0, bottom: 1 },
  ])
    assert.throws(() => new LabelGrid().place(box), RangeError);
});

test('boxes remain screen-sized at every world zoom and are clipped completely', () => {
  const viewport = { width: 1000, height: 600 };
  const expected = labelBox(500, 300, 90, 14, viewport);
  for (const zoom of [0.5, 1, 5, 100]) {
    const screenX = (500 / zoom) * zoom;
    assert.deepEqual(labelBox(screenX, 300, 90, 14, viewport), expected);
  }
  assert.equal(labelBox(-100, 20, 80, 14, viewport), null);
  assert.equal(labelBox(50, 20, 10000, 14, viewport), null);
});

test('genre size wins collisions, selected genre remains reachable, ties are stable', () => {
  const items = [
    { id: 'b', count: 1 },
    { id: 'a', count: 100 },
    { id: 'c', count: 1 },
  ];
  assert.deepEqual(
    items.toSorted((a, b) => priority(a, b, '')).map((x) => x.id),
    ['a', 'b', 'c'],
  );
  assert.deepEqual(
    items.toSorted((a, b) => priority(a, b, 'c')).map((x) => x.id),
    ['c', 'a', 'b'],
  );
  assert.equal(visibleDepth(1, 1), 0);
  assert.equal(visibleDepth(4, 1), 2);
  assert.equal(visibleDepth(64, 1), 6);
});

test('map labels keep breathing room horizontally and vertically', () => {
  const viewport = { width: 1000, height: 600 };
  const grid = new LabelGrid();
  assert.equal(grid.place(labelBox(100, 100, 90, 14, viewport).box), true);
  assert.equal(grid.place(labelBox(210, 100, 90, 14, viewport).box), false);
  assert.equal(grid.place(labelBox(100, 125, 90, 14, viewport).box), false);
  assert.equal(grid.place(labelBox(230, 100, 90, 14, viewport).box), true);
  assert.equal(grid.place(labelBox(100, 140, 90, 14, viewport).box), true);
});

test('full release-sized grid retains only disjoint boxes', () => {
  const grid = new LabelGrid();
  let accepted = 0;
  for (let i = 0; i < 34686; i++)
    accepted += Number(
      grid.place({
        left: (i % 200) * 12,
        top: Math.floor(i / 200) * 12,
        right: (i % 200) * 12 + 8,
        bottom: Math.floor(i / 200) * 12 + 8,
      }),
    );
  assert.equal(accepted, 34686);
});
