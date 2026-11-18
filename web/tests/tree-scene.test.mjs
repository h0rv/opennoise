import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { layoutTree } from '../src/tree-layout.ts';

const { outputFiles } = await build({
  entryPoints: [new URL('../src/tree-scene.ts', import.meta.url).pathname],
  bundle: true,
  format: 'esm',
  write: false,
});
const { indexTree } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}`
);

const branch = (key, children = []) => ({ key, width: 80, value: 'same name', children });
const intersects = (a, b) =>
  a.minX <= b.maxX && a.maxX >= b.minX && a.minY <= b.maxY && a.maxY >= b.minY;

test('compact rows have matching non-overlapping hit bounds', () => {
  const { nodes } = layoutTree(Array.from({ length: 100 }, (_, index) => branch(String(index))));
  const { byKey } = indexTree(nodes);
  let bottom = -Infinity;
  for (const node of nodes) {
    const item = byKey.get(node.key);
    assert.equal(item.maxY - item.minY, 32);
    assert.ok(item.minY >= bottom);
    bottom = item.maxY;
  }
});

test('viewport index contains exactly the nodes and connectors from a full-scan reference', () => {
  const roots = Array.from({ length: 40 }, (_, i) =>
    branch(
      String(i),
      Array.from({ length: i % 8 }, (_, j) => branch(`${i}.${j}`)),
    ),
  );
  for (const forest of [
    roots,
    roots.map((root, index) => (index % 3 ? root : { ...root, children: [] })),
  ]) {
    const { nodes } = layoutTree(forest);
    const { tree, byKey } = indexTree(nodes);
    assert.equal(byKey.size, nodes.length, 'equal names must not merge different published IDs');
    let seed = 179488;
    const random = () => (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32;
    for (let step = 0; step < 200; step++) {
      const x = random() * 500 - 100,
        y = random() * 12000 - 100;
      const viewport = {
        minX: x,
        minY: y,
        maxX: x + 20 + random() * 500,
        maxY: y + 20 + random() * 800,
      };
      const expected = tree
        .all()
        .filter((item) => intersects(item, viewport))
        .map((item) => `${item.kind}:${item.key}`)
        .sort();
      const actual = tree
        .search(viewport)
        .map((item) => `${item.kind}:${item.key}`)
        .sort();
      assert.deepEqual(actual, expected);
    }
  }
});

test('one shared spine remains visible even when both endpoint labels are offscreen', () => {
  const { nodes } = layoutTree([
    branch(
      'root',
      Array.from({ length: 1000 }, (_, i) => branch(String(i))),
    ),
  ]);
  const { tree } = indexTree(nodes);
  const spine = tree.all().find((item) => item.kind === 'edge' && item.key === 'spine:root');
  assert.ok(spine);
  const viewport = { minX: spine.minX, maxX: spine.maxX, minY: 400, maxY: 410 };
  const visible = tree.search(viewport);
  assert.ok(visible.some((item) => item.key === 'spine:root'));
  assert.equal(visible.filter((item) => item.kind === 'node').length, 0);
  assert.ok(visible.length < 5, 'shared trunks cannot duplicate one long edge per descendant');
});

test('a 33,053-node / 8,772-root shape mounts a viewport-sized scene, not the catalog', () => {
  const roots = Array.from({ length: 8772 }, (_, i) =>
    branch(
      String(i),
      Array.from({ length: i < 6737 ? 3 : 2 }, (_, j) => branch(`${i}.${j}`)),
    ),
  );
  const layout = layoutTree(roots);
  const { tree } = indexTree(layout.nodes);
  assert.equal(layout.nodes.length, 33053);
  for (const scale of [0.2, 0.75, 1, 4])
    for (const y of [0, layout.height / 2, layout.height - 4000]) {
      const viewport = {
        minX: -96 / scale,
        minY: y - 96 / scale,
        maxX: (1000 + 96) / scale,
        maxY: y + (620 + 96) / scale,
      };
      const visible = tree.search(viewport);
      assert.ok(
        visible.length > 0 && visible.length < 600,
        `bounded scene at scale ${scale}: ${visible.length}`,
      );
    }
});
