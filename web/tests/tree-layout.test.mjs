import assert from 'node:assert/strict';
import test from 'node:test';
import { layoutTree } from '../src/tree-layout.ts';

function branch(key, depth, fanout) {
  return {
    key,
    value: key,
    width: 50 + (key.length % 5) * 37,
    children: depth
      ? Array.from({ length: fanout }, (_, index) => branch(`${key}.${index}`, depth - 1, fanout))
      : [],
  };
}

test('tree edges retain the exact parent; depth columns and 32px rows do not overlap', () => {
  for (const depth of [0, 1, 2, 3, 4])
    for (const fanout of [1, 2, 3, 4]) {
      const roots = [branch('a', depth, fanout), branch('b', depth, fanout)];
      const layout = layoutTree(roots);
      const keys = new Map(layout.nodes.map((node) => [node.key, node]));
      for (const node of layout.nodes) {
        assert.equal(node.parent, node.depth ? node.key.slice(0, node.key.lastIndexOf('.')) : null);
        assert.equal(node.value, node.key);
        assert.ok(node.x >= 28 && node.y >= 32);
        assert.ok(node.x + node.width <= layout.width);
        assert.ok(node.y + 22 <= layout.height);
        if (node.parent) {
          const parent = keys.get(node.parent);
          assert.equal(node.depth, parent.depth + 1);
          assert.ok(node.x >= parent.x + parent.width + 64);
        }
      }
      for (const a of layout.nodes)
        for (const b of layout.nodes) {
          if (a.key === b.key) continue;
          assert.ok(a.x + a.width <= b.x || b.x + b.width <= a.x || Math.abs(a.y - b.y) >= 32);
        }
    }
});

test('collapsed roots and expanded leaves use the same compact 32px row spacing', () => {
  const roots = Array.from({ length: 1000 }, (_, index) => branch(String(index), 0, 0));
  const collapsed = layoutTree(roots);
  const expanded = layoutTree([branch('parent', 1, 1000)]);
  for (const rows of [collapsed.nodes, expanded.nodes.filter((node) => node.depth === 1)]) {
    assert.equal(rows.length, 1000);
    for (let index = 1; index < rows.length; index++)
      assert.equal(rows[index].y - rows[index - 1].y, 32);
  }
  assert.equal(collapsed.height, 32032);
  assert.equal(expanded.height, collapsed.height);
});

test('collapse only removes descendants; camera delta preserves the toggled node at every zoom', () => {
  const roots = [branch('a', 3, 3), branch('b', 2, 2)];
  const expanded = layoutTree(roots);
  const collapsed = layoutTree([{ ...roots[0], children: [] }, roots[1]]);
  assert.deepEqual(
    collapsed.nodes.map((node) => node.key),
    ['a', ...expanded.nodes.filter((node) => node.key.startsWith('b')).map((node) => node.key)],
  );
  const before = expanded.nodes[0],
    after = collapsed.nodes[0];
  for (const scale of [0.2, 0.75, 1, 2, 4]) {
    const pan = { x: -33, y: 98 };
    const next = { x: pan.x + before.x - after.x, y: pan.y + before.y - after.y };
    assert.equal((before.x + pan.x) * scale, (after.x + next.x) * scale);
    assert.equal((before.y + pan.y) * scale, (after.y + next.y) * scale);
  }
});

test('wide 5,100-node forest has one connected edge per non-root node', () => {
  const roots = Array.from({ length: 100 }, (_, index) => branch(String(index), 1, 50));
  const { nodes } = layoutTree(roots);
  assert.equal(nodes.length, 5100);
  assert.equal(nodes.filter((node) => node.parent !== null).length, 5000);
  assert.equal(new Set(nodes.map((node) => node.key)).size, 5100);
});

test('empty hierarchy remains a finite empty scene', () => {
  assert.deepEqual(layoutTree([]), { nodes: [], width: 1, height: 1 });
});
