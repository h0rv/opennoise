export type Box = { left: number; top: number; right: number; bottom: number };

export function labelBox(
  x: number,
  y: number,
  width: number,
  size: number,
  viewport: { width: number; height: number },
) {
  const textX = x + width + 14 < viewport.width ? x + 9 : x - width - 9;
  const box = {
    left: Math.min(x - 5, textX - 3),
    right: Math.max(x + 5, textX + width + 3),
    top: y - size - 3,
    bottom: y + 6,
  };
  return box.left < 3 ||
    box.right > viewport.width - 3 ||
    box.top < 3 ||
    box.bottom > viewport.height - 3
    ? null
    : { box, textX };
}

export function priority(
  a: { id: string; count: number },
  b: { id: string; count: number },
  selected: string,
) {
  return (
    Number(b.id === selected) - Number(a.id === selected) ||
    b.count - a.count ||
    (a.id < b.id ? -1 : a.id === b.id ? 0 : 1)
  );
}

export function visibleDepth(scale: number, home: number) {
  return Math.max(0, Math.floor(Math.log2(scale / home) + 0.5));
}

export class LabelGrid {
  private cells = new Map<number, Map<number, Box[]>>();
  private size: number;
  constructor(size = 64) {
    if (!Number.isFinite(size) || size <= 0) throw new RangeError('Invalid grid size');
    this.size = size;
  }

  place(box: Box) {
    if (
      !Number.isFinite(box.left) ||
      !Number.isFinite(box.right) ||
      !Number.isFinite(box.top) ||
      !Number.isFinite(box.bottom) ||
      box.right < box.left ||
      box.bottom < box.top
    )
      throw new RangeError('Invalid label box');
    const left = Math.floor(box.left / this.size),
      right = Math.floor(box.right / this.size);
    const top = Math.floor(box.top / this.size),
      bottom = Math.floor(box.bottom / this.size);
    for (let x = left; x <= right; x++) {
      const column = this.cells.get(x);
      if (!column) continue;
      for (let y = top; y <= bottom; y++) {
        const cell = column.get(y);
        if (!cell) continue;
        for (const other of cell)
          if (
            box.left < other.right &&
            box.right > other.left &&
            box.top < other.bottom &&
            box.bottom > other.top
          )
            return false;
      }
    }
    for (let x = left; x <= right; x++) {
      let column = this.cells.get(x);
      if (!column) {
        column = new Map();
        this.cells.set(x, column);
      }
      for (let y = top; y <= bottom; y++) {
        const cell = column.get(y);
        if (cell) cell.push(box);
        else column.set(y, [box]);
      }
    }
    return true;
  }
}
