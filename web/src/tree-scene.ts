import RBush, { type BBox } from 'rbush';
import { TREE_ROW_HEIGHT, type TreeNode } from './tree-layout';

type NodeItem<T> = BBox & { kind: 'node'; key: string; node: TreeNode<T>; order: number };
type EdgeItem = BBox & { kind: 'edge'; key: string; path: string };
export type SceneItem<T> = NodeItem<T> | EdgeItem;

export function indexTree<T>(nodes: TreeNode<T>[]) {
  const items: SceneItem<T>[] = [];
  const byKey = new Map<string, NodeItem<T>>();
  const children = new Map<string, TreeNode<T>[]>();
  nodes.forEach((node, order) => {
    const item: NodeItem<T> = {
      kind: 'node',
      key: node.key,
      node,
      order,
      minX: node.x,
      maxX: node.x + node.width,
      minY: node.y - TREE_ROW_HEIGHT / 2,
      maxY: node.y + TREE_ROW_HEIGHT / 2,
    };
    items.push(item);
    byKey.set(node.key, item);
    if (node.parent !== null) {
      const siblings = children.get(node.parent) || [];
      siblings.push(node);
      children.set(node.parent, siblings);
    }
  });
  function segment(key: string, x1: number, y1: number, x2: number, y2: number) {
    items.push({
      kind: 'edge',
      key,
      path: `M${x1} ${y1}L${x2} ${y2}`,
      minX: Math.min(x1, x2) - 0.5,
      maxX: Math.max(x1, x2) + 0.5,
      minY: Math.min(y1, y2) - 0.5,
      maxY: Math.max(y1, y2) + 0.5,
    });
  }
  for (const [key, siblings] of children) {
    const parent = byKey.get(key)!.node;
    const start = parent.x + parent.width;
    const spine = (start + siblings[0].x) / 2;
    segment(`parent:${key}`, start, parent.y, spine, parent.y);
    segment(`spine:${key}`, spine, siblings[0].y, spine, siblings[siblings.length - 1].y);
    for (const child of siblings) segment(`child:${child.key}`, spine, child.y, child.x, child.y);
  }
  return { byKey, tree: new RBush<SceneItem<T>>().load(items) };
}
