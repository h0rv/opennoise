export type Branch<T> = { key: string; width: number; value: T; children: Branch<T>[] };
export type TreeNode<T> = {
  key: string;
  width: number;
  value: T;
  depth: number;
  parent: string | null;
  x: number;
  y: number;
};

export function layoutTree<T>(roots: Branch<T>[]) {
  const levels: number[] = [];
  function measure(branch: Branch<T>, depth: number) {
    levels[depth] = Math.max(levels[depth] || 0, branch.width);
    for (const child of branch.children) measure(child, depth + 1);
  }
  roots.forEach((root) => measure(root, 0));
  const columns = [28];
  levels.forEach((width, depth) => {
    columns[depth + 1] = columns[depth] + width + 64;
  });
  const nodes: TreeNode<T>[] = [];
  let row = 32;
  function place(branch: Branch<T>, depth: number, parent: string | null): TreeNode<T> {
    const node = {
      key: branch.key,
      width: branch.width,
      value: branch.value,
      depth,
      parent,
      x: columns[depth],
      y: row,
    };
    nodes.push(node);
    if (branch.children.length) {
      const children = branch.children.map((child) => place(child, depth + 1, branch.key));
      node.y = (children[0].y + children[children.length - 1].y) / 2;
    } else row += 56;
    return node;
  }
  for (const root of roots) {
    place(root, 0, null);
    row += 40;
  }
  return {
    nodes,
    width: Math.max(1, ...nodes.map((node) => node.x + node.width + 28)),
    height: Math.max(1, ...nodes.map((node) => node.y + 32)),
  };
}
