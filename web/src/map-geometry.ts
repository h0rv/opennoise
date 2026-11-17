export type Point = { x: number; y: number };
export type Box = { left: number; right: number; top: number; bottom: number };
export type Camera = Point & { scale: number };
type Label = Point & { scale: number; box: Box };

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max));

export function cameraAt(point: Point, scale: number, width: number, height: number): Camera {
  return {
    scale,
    x: (width / 2 - 500) / scale + 500 - point.x,
    y: (height / 2 - 285) / scale + 285 - point.y,
  };
}

export function project(point: Point, camera: Camera): Point {
  return {
    x: 500 + (point.x - 500 + camera.x) * camera.scale,
    y: 285 + (point.y - 285 + camera.y) * camera.scale,
  };
}

export function contains(point: Point, box: Box, padding = 8) {
  return (
    point.x >= box.left + padding &&
    point.x <= box.right - padding &&
    point.y >= box.top + padding &&
    point.y <= box.bottom - padding
  );
}

function labelAt(
  point: Point,
  width: number,
  zoom: number,
  viewport: Box,
  x: number,
  y: number,
): Label {
  const scale = Math.min(
    1,
    (viewport.right - viewport.left - 16) / (width * zoom),
    (viewport.bottom - viewport.top - 16) / (18 * zoom),
  );
  const w = width * zoom * scale;
  const left = clamp(point.x + x * zoom, viewport.left + 8, viewport.right - 8 - w);
  const baseline = clamp(
    point.y + y * zoom,
    viewport.top + 8 + 13 * zoom * scale,
    viewport.bottom - 8 - 5 * zoom * scale,
  );
  return {
    x: (left - point.x) / zoom,
    y: (baseline - point.y) / zoom,
    scale,
    box: {
      left,
      right: left + w,
      top: baseline - 13 * zoom * scale,
      bottom: baseline + 5 * zoom * scale,
    },
  };
}

export function genreLabel(point: Point, width: number, zoom: number, viewport: Box): Label | null {
  if (!contains(point, viewport)) return null;
  const x = point.x + (13 + width) * zoom > viewport.right - 8 ? -width - 13 : 13;
  return labelAt(point, width, zoom, viewport, x, 5);
}

export function overlap(a: Box, b: Box) {
  return (
    Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
    Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top))
  );
}

export function artistLabel(
  point: Point,
  width: number,
  zoom: number,
  viewport: Box,
  obstacles: Box[],
): Label | null {
  if (!contains(point, viewport, 10)) return null;
  const offsets = [
    [14, 5],
    [14, -21],
    [14, 31],
    [-width - 14, -21],
    [-width - 14, 31],
    [14, -47],
    [14, 57],
  ];
  let best: Label | null = null;
  let score = Infinity;
  for (const [x, y] of offsets) {
    const label = labelAt(point, width, zoom, viewport, x, y);
    const area = obstacles.reduce(
      (total, other) =>
        total +
        overlap(label.box, {
          left: other.left - 4,
          right: other.right + 4,
          top: other.top - 4,
          bottom: other.bottom + 4,
        }),
      0,
    );
    if (area < score) {
      best = label;
      score = area;
    }
    if (!score) break;
  }
  return best;
}
