import assert from 'node:assert/strict';
import test from 'node:test';
import { cameraAt, project, genreLabel, artistLabel, overlap } from '../src/map-geometry.ts';

test('camera centers the requested published point at every viewport size and scale', () => {
  for (const width of [288, 342, 788, 1180])
    for (const height of [320, 420, 620])
      for (const scale of [0.25, 0.76, 1, 2, 5])
        for (const point of [
          { x: 90, y: 65 },
          { x: 500, y: 285 },
          { x: 910, y: 505 },
        ]) {
          const screen = project(point, cameraAt(point, scale, width, height));
          assert.ok(Math.abs(screen.x - width / 2) < 1e-9);
          assert.ok(Math.abs(screen.y - height / 2) < 1e-9);
        }
});

test('complete labels fit inside the viewport, including long names and corners', () => {
  for (const width of [288, 342, 788, 1180])
    for (const height of [320, 420, 620])
      for (const zoom of [0.25, 0.76, 1, 2, 5])
        for (const nameWidth of [32, 80, 240, 800])
          for (const x of [9, width / 2, width - 9])
            for (const y of [11, height / 2, height - 11]) {
              const viewport = { left: 0, right: width, top: 0, bottom: height };
              for (const label of [
                genreLabel({ x, y }, nameWidth, zoom, viewport),
                artistLabel({ x, y }, nameWidth, zoom, viewport, []),
              ]) {
                if (!label) continue;
                assert.ok(label.box.left >= 8 - 1e-9);
                assert.ok(label.box.right <= width - 8 + 1e-9);
                assert.ok(label.box.top >= 8 - 1e-9);
                assert.ok(label.box.bottom <= height - 8 + 1e-9);
                assert.ok(label.scale > 0 && label.scale <= 1);
              }
            }
});

test('offscreen markers cannot leave orphan label fragments', () => {
  const viewport = { left: 16, right: 374, top: 160, bottom: 480 };
  for (const point of [
    { x: -5, y: 300 },
    { x: 422, y: 300 },
    { x: 100, y: 490 },
  ]) {
    assert.equal(genreLabel(point, 80, 1.2, viewport), null);
    assert.equal(artistLabel(point, 80, 1.2, viewport, []), null);
  }
});

test('artist labels choose a non-overlapping candidate when one is available', () => {
  const viewport = { left: 0, right: 342, top: 0, bottom: 320 };
  const obstacle = { left: 100, right: 220, top: 136, bottom: 164 };
  const label = artistLabel({ x: 100, y: 150 }, 110, 1, viewport, [obstacle]);
  assert.ok(label);
  assert.equal(overlap(label.box, obstacle), 0);
});
